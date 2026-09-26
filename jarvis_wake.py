#!/usr/bin/env python3
"""Continuously detect 'Hey Jarvis', then run a bounded conversation session."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import wave
from collections import deque
from pathlib import Path

import numpy as np
import openwakeword
from openwakeword.model import Model


PROJECT = Path.home() / "Jarvis"
LISTEN_COMMAND = Path.home() / ".local" / "bin" / "jarvis-listen"
BARGE_IN_COMMAND = PROJECT / "jarvis_bargein.py"
CANCEL_EXIT_STATUS = 10
MIC_DEVICE = os.environ.get("JARVIS_MIC_DEVICE", "pipewire")
THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
FRAME_SAMPLES = 1280  # 80 ms of 16 kHz, signed 16-bit mono audio
FRAME_BYTES = FRAME_SAMPLES * 2
COOLDOWN_SECONDS = float(os.environ.get("JARVIS_WAKE_COOLDOWN", "1.5"))
COMMAND_PRE_ROLL_SECONDS = float(os.environ.get("JARVIS_COMMAND_PRE_ROLL", "1.2"))
COMMAND_MAX_SECONDS = float(os.environ.get("JARVIS_COMMAND_MAX_SECONDS", "8"))
COMMAND_MIN_SECONDS = float(os.environ.get("JARVIS_COMMAND_MIN_SECONDS", "0.6"))
COMMAND_START_TIMEOUT = float(os.environ.get("JARVIS_COMMAND_START_TIMEOUT", "2"))
COMMAND_SILENCE_SECONDS = float(os.environ.get("JARVIS_COMMAND_SILENCE_SECONDS", "0.8"))
COMMAND_RMS_THRESHOLD = float(os.environ.get("JARVIS_COMMAND_RMS_THRESHOLD", "450"))
FOLLOW_UP_WAIT_SECONDS = float(os.environ.get("JARVIS_FOLLOW_UP_WAIT_SECONDS", "5"))
CONVERSATION_MAX_TURNS = max(1, int(os.environ.get("JARVIS_CONVERSATION_MAX_TURNS", "4")))
END_SESSION_PATTERN = re.compile(
    r"\b(?:that's all|that is all|goodbye|bye jarvis|end (?:the )?conversation|"
    r"stop listening|no thanks|nothing else)\b"
)

running = True
recorder: subprocess.Popen[bytes] | None = None


def log(message: str) -> None:
    print(message, flush=True)


def stop_recorder() -> None:
    global recorder
    if recorder is None:
        return
    if recorder.poll() is None:
        recorder.terminate()
        try:
            recorder.wait(timeout=2)
        except subprocess.TimeoutExpired:
            recorder.kill()
            recorder.wait(timeout=2)
    recorder = None


def stop_service(_signum: int, _frame: object) -> None:
    global running
    running = False
    stop_recorder()


def start_recorder() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "arecord",
            "-q",
            "--device",
            MIC_DEVICE,
            "--format",
            "S16_LE",
            "--rate",
            "16000",
            "--channels",
            "1",
            "--file-type",
            "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )


def read_frame(stream: object) -> bytes:
    data = bytearray()
    while running and len(data) < FRAME_BYTES:
        chunk = stream.read(FRAME_BYTES - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def capture_command(
    stream: object,
    pre_roll: tuple[bytes, ...],
    *,
    start_timeout: float = COMMAND_START_TIMEOUT,
    require_speech: bool = False,
    label: str = "one-shot command",
) -> Path | None:
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    file_descriptor, audio_name = tempfile.mkstemp(
        prefix="jarvis-command-",
        suffix=".wav",
        dir=runtime_dir,
    )
    os.close(file_descriptor)
    audio_path = Path(audio_name)

    frames = list(pre_roll)
    new_frame_count = 0
    speech_frame_count = 0
    speech_seen = False
    silent_frame_count = 0
    capture_window = COMMAND_MAX_SECONDS + (start_timeout if require_speech else 0)
    max_frames = max(1, int(capture_window * 16000 / FRAME_SAMPLES))
    command_max_frames = max(1, int(COMMAND_MAX_SECONDS * 16000 / FRAME_SAMPLES))
    minimum_frames = max(1, int(COMMAND_MIN_SECONDS * 16000 / FRAME_SAMPLES))
    start_timeout_frames = max(1, int(start_timeout * 16000 / FRAME_SAMPLES))
    silence_frames_needed = max(1, int(COMMAND_SILENCE_SECONDS * 16000 / FRAME_SAMPLES))

    try:
        while running and new_frame_count < max_frames:
            raw = read_frame(stream)
            if len(raw) != FRAME_BYTES:
                break
            frames.append(raw)
            new_frame_count += 1

            frame = np.frombuffer(raw, dtype=np.int16)
            rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
            if rms >= COMMAND_RMS_THRESHOLD:
                speech_seen = True
                silent_frame_count = 0
            elif speech_seen:
                silent_frame_count += 1
            if speech_seen:
                speech_frame_count += 1


            if new_frame_count >= minimum_frames:
                if speech_seen and silent_frame_count >= silence_frames_needed:
                    break
                if speech_seen and speech_frame_count >= command_max_frames:
                    break
                if not speech_seen and new_frame_count >= start_timeout_frames:
                    break

        if require_speech and not speech_seen:
            audio_path.unlink(missing_ok=True)
            log("No follow-up heard; conversation session ended")
            return None

        with wave.open(str(audio_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"".join(frames))
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise

    duration = len(frames) * FRAME_SAMPLES / 16000
    log(f"Captured {label} ({duration:.2f}s)")
    return audio_path


def load_model() -> Model:
    package_dir = Path(openwakeword.__file__).parent
    matches = list(package_dir.rglob("hey_jarvis_v0.1.onnx"))
    if not matches:
        raise FileNotFoundError("The Hey Jarvis wake-word model is missing")
    log(f"Loading wake-word model: {matches[0]}")
    return Model(wakeword_model_paths=[str(matches[0])])


def stop_process(process: subprocess.Popen[object] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def stop_process_group(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def normalize_transcript(text: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def is_end_session_phrase(text: str) -> bool:
    return bool(END_SESSION_PATTERN.search(normalize_transcript(text)))


def capture_follow_up() -> Path | None:
    global recorder
    recorder = start_recorder()
    if recorder.stdout is None:
        log("Follow-up microphone stream could not be opened")
        stop_recorder()
        return None
    log(f"Waiting up to {FOLLOW_UP_WAIT_SECONDS:.1f}s for a follow-up")
    try:
        return capture_command(
            recorder.stdout,
            (),
            start_timeout=FOLLOW_UP_WAIT_SECONDS,
            require_speech=True,
            label="follow-up",
        )
    finally:
        stop_recorder()


def run_command_cycle(audio_path: Path) -> tuple[str, str]:
    stop_recorder()
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    descriptor, transcript_name = tempfile.mkstemp(
        prefix="jarvis-transcript-",
        suffix=".txt",
        dir=runtime_dir,
    )
    os.close(descriptor)
    transcript_path = Path(transcript_name)
    environment = os.environ.copy()
    environment["JARVIS_MIC_DEVICE"] = MIC_DEVICE
    environment["JARVIS_AUDIO_FILE"] = str(audio_path)
    environment["JARVIS_TRANSCRIPT_FILE"] = str(transcript_path)
    command: subprocess.Popen[object] | None = None
    barge_in: subprocess.Popen[object] | None = None
    outcome = "error"
    transcript = ""
    try:
        command = subprocess.Popen(
            [str(LISTEN_COMMAND)],
            env=environment,
            start_new_session=True,
        )
        if BARGE_IN_COMMAND.is_file():
            barge_in = subprocess.Popen(
                [sys.executable, str(BARGE_IN_COMMAND)],
                env=environment,
            )

        deadline = time.monotonic() + 180
        while True:
            returncode = command.poll()
            if returncode is not None:
                log(f"Command cycle finished with status {returncode}")
                outcome = "completed" if returncode == 0 else "error"
                break

            if not running:
                stop_process_group(command)
                outcome = "stopped"
                log("Command cycle stopped with wake service")
                break

            if barge_in is not None and barge_in.poll() is not None:
                if barge_in.returncode == CANCEL_EXIT_STATUS:
                    log("Barge-in cancellation detected")
                    stop_process_group(command)
                    outcome = "cancelled"
                    log("Command cycle cancelled")
                    break
                log(f"Barge-in monitor exited with status {barge_in.returncode}")
                barge_in = None

            if time.monotonic() >= deadline:
                stop_process_group(command)
                outcome = "timeout"
                log("Command cycle timed out")
                break
            time.sleep(0.1)
    except OSError as error:
        log(f"Could not launch jarvis-listen: {error}")
    finally:
        stop_process(barge_in)
        audio_path.unlink(missing_ok=True)
        try:
            transcript = transcript_path.read_text(encoding="utf-8").strip()
        except OSError:
            transcript = ""
        transcript_path.unlink(missing_ok=True)

    return outcome, transcript


def run_conversation(model: Model, first_audio: Path) -> None:
    audio_path: Path | None = first_audio
    for turn in range(1, CONVERSATION_MAX_TURNS + 1):
        outcome, transcript = run_command_cycle(audio_path)
        if not running or outcome != "completed":
            break
        if is_end_session_phrase(transcript):
            log("Conversation ended by spoken phrase")
            break
        if turn >= CONVERSATION_MAX_TURNS:
            log(f"Conversation reached the {CONVERSATION_MAX_TURNS}-turn limit")
            break
        audio_path = capture_follow_up()
        if audio_path is None:
            break

    if hasattr(model, "reset"):
        model.reset()
    time.sleep(COOLDOWN_SECONDS)


def main() -> int:
    global recorder
    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    if not LISTEN_COMMAND.exists():
        log(f"Missing command: {LISTEN_COMMAND}")
        return 1

    model = load_model()
    log(f"Wake listener ready on {MIC_DEVICE}; threshold={THRESHOLD:.2f}")
    pre_roll_frame_count = max(1, int(COMMAND_PRE_ROLL_SECONDS * 16000 / FRAME_SAMPLES))

    while running:
        recent_audio: deque[bytes] = deque(maxlen=pre_roll_frame_count)
        recorder = start_recorder()
        if recorder.stdout is None:
            log("Microphone stream could not be opened")
            stop_recorder()
            time.sleep(2)
            continue

        while running and recorder.poll() is None:
            raw = read_frame(recorder.stdout)
            if len(raw) != FRAME_BYTES:
                break
            recent_audio.append(raw)
            frame = np.frombuffer(raw, dtype=np.int16)
            predictions = model.predict(frame)
            score = max((float(value) for value in predictions.values()), default=0.0)
            if score >= THRESHOLD:
                log(f"Hey Jarvis detected (confidence {score:.2f})")
                audio_path = capture_command(recorder.stdout, tuple(recent_audio))
                if not running:
                    audio_path.unlink(missing_ok=True)
                    break
                run_conversation(model, audio_path)
                break

        stop_recorder()
        if running:
            time.sleep(1)

    log("Wake listener stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
