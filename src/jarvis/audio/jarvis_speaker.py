#!/usr/bin/env python3
"""Enroll and identify household speakers using local ONNX embeddings."""

from __future__ import annotations

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import os
import sys
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx


PROJECT = Path.home() / "Jarvis"
MODEL = Path(
    os.environ.get(
        "JARVIS_SPEAKER_MODEL",
        str(PROJECT / "models" / "nemo_en_titanet_small.onnx"),
    )
)
SAMPLES = PROJECT / "VoiceProfiles" / "samples"
PROFILES = PROJECT / "VoiceProfiles" / "profiles"
ALLOWED = {
    "arnav": "Arnav",
    "shriya": "Shriya",
    "soni": "Soni",
    "xavier": "Xavier",
}
THRESHOLD = float(os.environ.get("JARVIS_SPEAKER_THRESHOLD", "0.70"))
MIN_MARGIN = float(os.environ.get("JARVIS_SPEAKER_MARGIN", "0.10"))


def extractor() -> sherpa_onnx.SpeakerEmbeddingExtractor:
    if not MODEL.is_file():
        raise FileNotFoundError(f"Speaker model is missing: {MODEL}")
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODEL),
        num_threads=2,
        debug=False,
        provider="cpu",
    )
    if not config.validate():
        raise RuntimeError("The speaker model configuration is invalid")
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError(f"Expected 16-bit mono WAV: {path}")
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    return np.ascontiguousarray(samples.astype(np.float32) / 32768.0), rate


def trim_silence(samples: np.ndarray, rate: int) -> np.ndarray:
    """Remove leading/trailing room silence while retaining natural pauses."""
    frame_size = max(1, int(rate * 0.02))
    frame_count = len(samples) // frame_size
    if frame_count == 0:
        raise ValueError("Audio is empty")

    framed = samples[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(framed), axis=1) + 1e-12)
    peak = float(np.max(rms))
    noise = float(np.percentile(rms, 20))
    cutoff = max(0.003, peak * 0.10, noise * 2.5)
    voiced = np.flatnonzero(rms >= cutoff)
    if len(voiced) < 15:
        raise ValueError("Not enough speech was detected")

    padding = int(rate * 0.18)
    start = max(0, int(voiced[0]) * frame_size - padding)
    stop = min(len(samples), (int(voiced[-1]) + 1) * frame_size + padding)
    return np.ascontiguousarray(samples[start:stop])


def embedding(path: Path, model: sherpa_onnx.SpeakerEmbeddingExtractor) -> np.ndarray:
    samples, rate = load_wav(path)
    samples = trim_silence(samples, rate)
    stream = model.create_stream()
    stream.accept_waveform(sample_rate=rate, waveform=samples)
    stream.input_finished()
    if not model.is_ready(stream):
        raise ValueError(f"Audio is too short for speaker recognition: {path}")
    value = np.asarray(model.compute(stream), dtype=np.float32)
    norm = float(np.linalg.norm(value))
    if norm == 0:
        raise ValueError(f"No usable voice was found in: {path}")
    return value / norm


def canonical_name(value: str) -> str:
    key = value.strip().lower()
    if key not in ALLOWED:
        raise ValueError("Name must be one of: Arnav, Shriya, Soni, Xavier")
    return ALLOWED[key]


def build_profile(name_value: str) -> int:
    name = canonical_name(name_value)
    paths = sorted((SAMPLES / name.lower()).glob("*.wav"))
    if len(paths) < 3:
        raise ValueError(f"At least 3 enrollment samples are required for {name}")

    model = extractor()
    vectors = [embedding(path, model) for path in paths]
    embeddings = np.stack(vectors)
    profile = np.mean(embeddings, axis=0)
    profile /= np.linalg.norm(profile)
    PROFILES.mkdir(parents=True, exist_ok=True)
    np.savez(PROFILES / f"{name.lower()}.npz", embeddings=embeddings, centroid=profile)
    print(f"Enrolled {name} from {len(paths)} samples")
    return 0


def score_profile(query: np.ndarray, embeddings: np.ndarray, centroid: np.ndarray) -> float:
    similarities = np.sort(embeddings @ query)[::-1]
    robust_count = min(3, len(similarities))
    robust_score = float(np.mean(similarities[:robust_count]))
    centroid_score = float(np.dot(query, centroid))
    return 0.60 * centroid_score + 0.40 * robust_score


def load_profiles() -> list[tuple[str, np.ndarray, np.ndarray]]:
    profiles: list[tuple[str, np.ndarray, np.ndarray]] = []
    for key, name in ALLOWED.items():
        profile_path = PROFILES / f"{key}.npz"
        legacy_path = PROFILES / f"{key}.npy"
        if profile_path.is_file():
            data = np.load(profile_path)
            profiles.append((name, data["embeddings"], data["centroid"]))
        elif legacy_path.is_file():
            centroid = np.load(legacy_path)
            profiles.append((name, centroid.reshape(1, -1), centroid))
    return profiles


def identify(path_value: str) -> int:
    path = Path(path_value)
    profiles = load_profiles()

    if not profiles:
        print("Unknown|0.000|0.000")
        return 0

    query = embedding(path, extractor())
    scores = [
        (name, score_profile(query, embeddings, centroid))
        for name, embeddings, centroid in profiles
    ]
    scores.sort(key=lambda item: item[1], reverse=True)
    name, score = max(scores, key=lambda item: item[1])
    runner_up = scores[1][1] if len(scores) > 1 else -1.0
    margin = score - runner_up
    print(f"{name}|{score:.3f}|{margin:.3f}")
    return 0


def calibrate() -> int:
    available: dict[str, list[Path]] = {
        name: sorted((SAMPLES / key).glob("*.wav"))
        for key, name in ALLOWED.items()
        if (SAMPLES / key).is_dir()
    }
    available = {name: paths for name, paths in available.items() if len(paths) >= 3}
    if len(available) < 2:
        raise ValueError("At least two enrolled speakers are needed for calibration")

    model = extractor()
    vectors = {
        name: np.stack([embedding(path, model) for path in paths])
        for name, paths in available.items()
    }
    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    margins: list[float] = []

    print("Leave-one-out speaker calibration")
    for name, speaker_vectors in vectors.items():
        for index, query in enumerate(speaker_vectors):
            own = np.delete(speaker_vectors, index, axis=0)
            own_centroid = np.mean(own, axis=0)
            own_centroid /= np.linalg.norm(own_centroid)
            genuine = score_profile(query, own, own_centroid)
            rivals = []
            for other_name, other_vectors in vectors.items():
                if other_name == name:
                    continue
                other_centroid = np.mean(other_vectors, axis=0)
                other_centroid /= np.linalg.norm(other_centroid)
                rivals.append((other_name, score_profile(query, other_vectors, other_centroid)))
            rival_name, impostor = max(rivals, key=lambda item: item[1])
            margin = genuine - impostor
            genuine_scores.append(genuine)
            impostor_scores.append(impostor)
            margins.append(margin)
            verdict = "PASS" if genuine >= THRESHOLD and margin >= MIN_MARGIN else "REVIEW"
            print(
                f"{name} sample-{index + 1}: own={genuine:.3f} "
                f"closest={rival_name}:{impostor:.3f} margin={margin:.3f} {verdict}"
            )

    print(
        f"Summary: min-own={min(genuine_scores):.3f} "
        f"max-other={max(impostor_scores):.3f} min-margin={min(margins):.3f}"
    )
    print(f"Active policy: score>={THRESHOLD:.2f} and margin>={MIN_MARGIN:.2f}")
    return 0


def list_profiles() -> int:
    for key, name in ALLOWED.items():
        state = "enrolled" if any(
            (PROFILES / f"{key}{suffix}").is_file() for suffix in (".npz", ".npy")
        ) else "not enrolled"
        print(f"{name}: {state}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("name")
    identify_parser = subparsers.add_parser("identify")
    identify_parser.add_argument("wav")
    subparsers.add_parser("list")
    subparsers.add_parser("calibrate")
    args = parser.parse_args()

    if args.command == "build":
        return build_profile(args.name)
    if args.command == "identify":
        return identify(args.wav)
    if args.command == "calibrate":
        return calibrate()
    return list_profiles()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Speaker recognition error: {error}", file=sys.stderr)
        raise SystemExit(1)
