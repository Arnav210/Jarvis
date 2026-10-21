# Architecture

Source inventory updated 2026-10-20. This describes components, not a live health check.

## Voice and command path

PipeWire microphone → `jarvis_wake.py` / openWakeWord → captured command WAV →
`bin/jarvis-listen` → local Whisper server and `jarvis_speaker.py` →
`jarvis_assistant.py` deterministic routing → optional `jarvis_ai.py` / local Ollama →
`bin/jarvis-speak` / Piper (eSpeak fallback) → PipeWire playback.

`jarvis_bargein.py` handles cancellation. The wake override sets one command per wake
phrase. `jarvis_listen_control.py`, `jarvis_manual_listen.py`, and `jarvis_reset.py`
coordinate command ownership and reset state. `jarvis_mic_meter.py` derives display levels.

`jarvis_status.py`, `jarvis_console_layout.py`, `jarvis_reactor.py`, `jarvis_remarks.py`,
`jarvis_activity.py`, `jarvis_idle_drone.py`, and `jarvis_halloween.py` implement console
state and presentation. `jarvis_vitals.py` provides system telemetry. `jarvis_computer.py`
provides bounded local inspection; `jarvis_image_view.py` displays requested images.

`jarvis_music.py` controls a local MPV user service through a private IPC socket.
`jarvis_music_duck.py` lowers only that player's level during commands and restores it;
`jarvis_music_panel.py` provides telemetry. `jarvis_spotify.py` is a separate optional path.

## Recording and vision

`jarvis_camera_feed.py` provides the shared loopback MJPEG feed at port 8766.
`jarvis_log.py` records requested Captain's Logs under `data/captains-log/`;
`jarvis_preview.py` handles preview. The remote stream consumes the shared feed and
PipeWire microphone separately from photo analysis.

`bin/jarvis-camera` writes captures to `Footage/`; `bin/run_sam.sh` watches for completed
JPEG writes and invokes `sam3_process.py` in the dedicated SAM3 environment. Completed
results are stored under `Masks/runs/`, with `Masks/latest` identifying the newest run.
`object_monitor/object_monitor/object_monitor.py` compares observations with local state.

Optional `depth_service.py` and `measure_photo.py` use Depth Anything 3.
`gesture_controller.py`, `gesture_analyzer.py`, `mediapipe_tracker.py`, and `config.py`
implement camera-based gesture control. These are separate optional components, not
requirements for running the source regression checks.

## Services and dependencies

Repository templates live in `systemd/user/`; installed units live under
`~/.config/systemd/user/`. They are deployed separately. The wake templates include the
single-command and music-recovery drop-ins. The SAM3 template points to `bin/run_sam.sh`.
See `SETUP.md` for environment boundaries and `DEPENDENCIES.json` for observed revisions.

## State boundaries

Recordings, footage, masks, voice profiles, conversation history, music, models,
credentials, and generated state stay outside version control. The console uses
per-user runtime state. The source checks and regression tests use temporary state.
See `REPOSITORY.md` for the explicit Git boundary.
