#!/usr/bin/env python3
"""Continuously detect 'Hey Jarvis', then run one Jarvis command cycle."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import openwakeword
from openwakeword.model import Model


PROJECT = Path.home() / "Jarvis"
LISTEN_COMMAND = Path.home() / ".local" / "bin" / "jarvis-listen"
MIC_DEVICE = os.environ.get("JARVIS_MIC_DEVICE", "pipewire")
THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
FRAME_SAMPLES = 1280  # 80 ms of 16 kHz, signed 16-bit mono audio
FRAME_BYTES = FRAME_SAMPLES * 2
COOLDOWN_SECONDS = float(os.environ.get("JARVIS_WAKE_COOLDOWN", "1.5"))

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


def load_model() -> Model:
    package_dir = Path(openwakeword.__file__).parent
    matches = list(package_dir.rglob("hey_jarvis_v0.1.onnx"))
    if not matches:
        raise FileNotFoundError("The Hey Jarvis wake-word model is missing")
    log(f"Loading wake-word model: {matches[0]}")
    return Model(wakeword_model_paths=[str(matches[0])])


def run_command_cycle(model: Model, score: float) -> None:
    stop_recorder()
    log(f"Hey Jarvis detected (confidence {score:.2f})")
    environment = os.environ.copy()
    environment["JARVIS_MIC_DEVICE"] = MIC_DEVICE
    try:
        result = subprocess.run(
            [str(LISTEN_COMMAND)],
            env=environment,
            timeout=180,
            check=False,
        )
        log(f"Command cycle finished with status {result.returncode}")
    except subprocess.TimeoutExpired:
        log("Command cycle timed out")
    except OSError as error:
        log(f"Could not launch jarvis-listen: {error}")

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

    while running:
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
            frame = np.frombuffer(raw, dtype=np.int16)
            predictions = model.predict(frame)
            score = max((float(value) for value in predictions.values()), default=0.0)
            if score >= THRESHOLD:
                run_command_cycle(model, score)
                break

        stop_recorder()
        if running:
            time.sleep(1)

    log("Wake listener stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
