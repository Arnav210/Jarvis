# Architecture

Snapshot: September 25, 2026.

## Voice pipeline

- `jarvis-wake.service` runs `.venv-wake/bin/python jarvis_wake.py` continuously.
- `jarvis_wake.py` reads 16 kHz mono audio through PipeWire and detects `hey_jarvis_v0.1.onnx` with openWakeWord.
- On detection it releases the microphone and starts `~/.local/bin/jarvis-listen`.
- `jarvis-listen` records five seconds, transcribes with Whisper.cpp, labels the closest enrolled speaker with `jarvis_speaker.py`, and invokes `jarvis_assistant.py`.
- While that command is active, `jarvis_bargein.py` listens in short local-only windows for strict cancellation phrases and terminates the command process group without a spoken acknowledgment.
- `jarvis_assistant.py` runs deterministic routes first and calls `jarvis_ai.py` only for unmatched requests.
- `jarvis_ai.py` calls Ollama at localhost through an explicit function allowlist. It has no arbitrary shell tool.
- `jarvis-speak` uses Piper, falls back to eSpeak-NG, and plays through PipeWire.

## Vision pipeline

- `jarvis-camera` captures one 640x480 JPEG from `/dev/video0` into `Footage/` with a microsecond timestamp.
- `jarvis-sam3.service` runs `run_sam.sh`, which watches `Footage/` for completed JPEG writes.
- `sam3_process.py` uses the dedicated Python 3.12 SAM3 environment and CPU inference.
- Each completed analysis is stored in `Masks/runs/<capture-timestamp>/` with the original, raw masks, per-mask overlays, a combined overlay, and `manifest.json`.
- `Masks/latest` is a symlink to the newest complete run. It is required by the scene tools and object monitor.
- `object_monitor/object_monitor/object_monitor.py` compares detections with persistent state and appends events. State and event files are intentionally not tracked.

## Services

Tracked templates are in `systemd/user/`. Live units reside in `~/.config/systemd/user/`.

- `jarvis-wake.service`: enabled and active at the snapshot.
- `jarvis-sam3.service`: enabled and active at the snapshot.
- `jarvis-stream.service`: disabled and failed at the snapshot; it is separate from photo analysis.

## Private and generated data

Never commit:

- `Footage/` and `Masks/`
- `VoiceProfiles/`
- `data/conversation_history.json`
- `models/`, `voices/`, and model binaries
- `.venv-*`, caches, or runtime state
- nested third-party repositories
