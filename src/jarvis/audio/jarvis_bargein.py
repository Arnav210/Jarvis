#!/usr/bin/env python3
"""Listen for strict cancellation phrases while a Jarvis command is active."""

from __future__ import annotations

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path.home() / "Jarvis"
WHISPER = PROJECT / "whisper.cpp" / "build" / "bin" / "whisper-cli"
MODEL = PROJECT / "whisper.cpp" / "models" / "ggml-base.en.bin"
MIC_DEVICE = os.environ.get("JARVIS_MIC_DEVICE", "pipewire")
WINDOW_SECONDS = max(1, int(os.environ.get("JARVIS_BARGE_IN_SECONDS", "2")))
CANCEL_EXIT_STATUS = 10
CANCEL_PATTERN = re.compile(
    r"\b(?:jarvis\s+(?:please\s+)?(?:stop|cancel|be\s+quiet|quiet|shut\s+up)"
    r"|cancel\s+(?:that|it|this)|never\s+mind|be\s+quiet)\b"
)

running = True
child: subprocess.Popen[object] | None = None


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def is_cancel_phrase(text: str) -> bool:
    return bool(CANCEL_PATTERN.search(normalize(text)))


def stop_child() -> None:
    global child
    if child is None or child.poll() is not None:
        child = None
        return
    child.terminate()
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=2)
    child = None


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False
    stop_child()


def run(command: list[str]) -> int:
    global child
    child = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    returncode = child.wait()
    child = None
    return returncode


def main() -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if not WHISPER.is_file() or not MODEL.is_file():
        print("Barge-in speech recognition is not ready.", file=sys.stderr)
        return 1

    while running:
        with tempfile.TemporaryDirectory(prefix="jarvis-bargein-") as folder:
            work = Path(folder)
            audio = work / "phrase.wav"
            transcript_base = work / "transcript"

            record_status = run(
                [
                    "arecord",
                    "-q",
                    "--device",
                    MIC_DEVICE,
                    "--duration",
                    str(WINDOW_SECONDS),
                    "--format",
                    "S16_LE",
                    "--rate",
                    "16000",
                    "--channels",
                    "1",
                    str(audio),
                ]
            )
            if not running:
                break
            if record_status != 0:
                print("Barge-in microphone capture failed.", file=sys.stderr)
                return 1

            transcribe_status = run(
                [
                    str(WHISPER),
                    "--model",
                    str(MODEL),
                    "--file",
                    str(audio),
                    "--language",
                    "en",
                    "--no-timestamps",
                    "--no-prints",
                    "--output-txt",
                    "--output-file",
                    str(transcript_base),
                ]
            )
            if not running:
                break
            transcript_path = transcript_base.with_suffix(".txt")
            if transcribe_status != 0 or not transcript_path.is_file():
                continue

            transcript = transcript_path.read_text(encoding="utf-8").replace("\n", " ")
            if is_cancel_phrase(transcript):
                print(f"Cancellation phrase heard: {normalize(transcript)}", flush=True)
                return CANCEL_EXIT_STATUS

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
