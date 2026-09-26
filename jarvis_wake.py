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
BARGE_IN_COMMAND = PROJECT / "jarvis_bargein.py"
CANCEL_EXIT_STATUS = 10
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


def run_command_cycle(model: Model, score: float) -> None:
    stop_recorder()
    log(f"Hey Jarvis detected (confidence {score:.2f})")
    environment = os.environ.copy()
    environment["JARVIS_MIC_DEVICE"] = MIC_DEVICE
    command: subprocess.Popen[object] | None = None
    barge_in: subprocess.Popen[object] | None = None
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
                break

            if not running:
                stop_process_group(command)
                log("Command cycle stopped with wake service")
                break

            if barge_in is not None and barge_in.poll() is not None:
                if barge_in.returncode == CANCEL_EXIT_STATUS:
                    log("Barge-in cancellation detected")
                    stop_process_group(command)
                    log("Command cycle cancelled")
                    break
                log(f"Barge-in monitor exited with status {barge_in.returncode}")
                barge_in = None

            if time.monotonic() >= deadline:
                stop_process_group(command)
                log("Command cycle timed out")
                break
            time.sleep(0.1)
    except OSError as error:
        log(f"Could not launch jarvis-listen: {error}")
    finally:
        stop_process(barge_in)

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
