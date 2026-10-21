# Setup and recovery

This repository contains Jarvis source, not a full machine image. The checked installation
is Ubuntu 24.04 on an Intel Mac mini. The voice path uses PipeWire, local Whisper, Ollama,
openWakeWord, speaker recognition, and Piper. A microphone and speaker are needed for voice;
the optional camera path requires a supported webcam. Use `$HOME/Jarvis` for the checkout:
several modules still use that location directly even when launchers accept `JARVIS_HOME`.

## Check the source without hardware

On a separate checkout or development machine:

```bash
cd "$HOME/Jarvis"
python3.12 -m venv .venv-test
.venv-test/bin/python -m pip install -r requirements/test.txt
# MPV is required by the silent integration checks.
sudo apt-get install mpv
.venv-test/bin/python tools/check_repository.py --history
.venv-test/bin/python tools/run_checks.py
```

Tests create temporary state and synthetic WAVs. Integration players use `--ao=null` and
private temporary sockets. They do not need your recordings, music, camera, microphone,
enrolled speakers, or model downloads. All tests live in `tests/`; `tools/run_checks.py` runs the unit suite and the three
standalone integration scripts against the package under `src/`.

## System tools

The following package list covers the commands used by the core launchers and optional
media/gesture tools on Ubuntu. Install components you use; this command does not start Jarvis:

```bash
sudo apt-get install python3.12-venv python3-pip git build-essential cmake \
  ffmpeg alsa-utils pipewire pipewire-pulse wireplumber mpv espeak-ng \
  inotify-tools playerctl pulseaudio-utils
```

The system Python entry points use `/usr/bin/python3`. The inspected machine also has a
Conda base interpreter, so the meaning of `python3` in an interactive shell can differ.
Record that distinction when debugging; do not replace the operating system Python.
`requirements/observed-environments.json` records interpreter versions and package versions
without exporting access tokens, package-index credentials, or local installation URLs.
`requirements/observed-conda.json` additionally records native Conda package versions and
builds for the three optional vision environments, which Python package metadata alone
does not fully describe. These snapshots target Linux x86_64.

## Voice environments

The `requirements/*-observed.txt` files pin packages observed in each working environment.
They are recovery snapshots, not a cross-platform lockfile. On a separate machine, use the
recorded Python minor version for each environment, create it at the expected location,
and install its matching requirements. For wake and speaker recognition:

```bash
python3.12 -m venv .venv-wake
.venv-wake/bin/python -m pip install -r requirements/wake-observed.txt
python3.12 -m venv .venv-speaker
.venv-speaker/bin/python -m pip install -r requirements/speaker-observed.txt
```

The current `.venv-tts` uses Python 3.14, separately from wake/speaker Python 3.12.
Create that environment with a Python 3.14 interpreter and install `tts-observed.txt`.
Do not merge these environments or run installation commands over the active machine
as part of repository cleanup.

Whisper is built separately under `whisper.cpp/`. Use the upstream URL and exact revision
recorded in `docs/DEPENDENCIES.json`, then build its server and CLI:

```bash
git clone https://github.com/ggml-org/whisper.cpp.git
# Read the matching commit from docs/DEPENDENCIES.json before continuing.
git -C whisper.cpp checkout <recorded-whisper-commit>
cmake -S whisper.cpp -B whisper.cpp/build -DGGML_CUDA=OFF
cmake --build whisper.cpp/build --config Release --parallel 4
```

The template transcription service expects `whisper-server`, `ggml-tiny.en.bin`, and
`ggml-silero-v6.2.0.bin` in the paths recorded in `docs/MODELS.json`. Obtain the weights
using the pinned upstream checkout's download instructions. Models stay ignored by Git.

Ollama is a separate local service. The configured model is `qwen3.5:0.8b`, with local
endpoint `http://127.0.0.1:11434`. Recreate it with the Ollama tooling on the destination
machine. `docs/DEPENDENCIES.json` records the observed model digest where available.

Piper expects `voices/en_GB-alan-medium/en_GB-alan-medium.onnx` and its adjacent JSON
configuration. Speaker recognition expects `models/nemo_en_titanet_small.onnx`.
Wake models come from the openWakeWord package resources. Use the source locations and
observed checksums in `docs/MODELS.json`; provision models separately and review their
upstream terms before redistribution. Enrollment recordings and profiles are never setup assets.

## Optional vision components

`sam3/` and `Depth-Anything-3/` are separate upstream checkouts, deliberately excluded
from this repository. Their revisions and origins are recorded in `docs/DEPENDENCIES.json`.
The SAM3 interpreter is `$HOME/miniconda3/envs/sam3/bin/python` (Python 3.12).
The depth environment is separately recorded as `da3_env`; the gesture environment is
recorded as `jarvis`. `requirements/*-observed.txt` preserves their installed package lists.
Do not treat the SAM3 snapshot's NVIDIA packages as a hardware requirement for this Mac mini;
the current inference wrapper requests CPU execution. Continuous CPU inference performance
is not established by source checks.

The current SAM3 checkout contains local CPU compatibility edits. After checking out the
recorded SAM3 revision on a fresh machine, inspect and apply the preserved patch:

```bash
git -C sam3 apply --check ../patches/sam3-local-cpu.patch
git -C sam3 apply ../patches/sam3-local-cpu.patch
```

The patch captures existing edits. The source reorganization moves the byte-identical
SAM3 processor to `src/jarvis/vision/sam3_process.py`; the third-party checkout is unchanged. Build/install the upstream project in the dedicated
environment following its pinned checkout. SAM3 checkpoint access uses your own existing
model-provider account and terms; authentication tokens stay outside the repository.

Gesture tracking additionally requires `hand_landmarker.task` in the checkout root,
obtained separately from MediaPipe. Depth helpers refer to `depth-anything/DA3-SMALL`.
Optional components have source validation and recorded dependencies; full model inference
and hardware behavior have not been reproduced on a fresh installation during this cleanup.

## Commands and configuration

Review the launchers, then install user shortcuts on the destination machine:

```bash
mkdir -p "$HOME/.local/bin"
for command in "$HOME/Jarvis"/bin/jarvis-*; do
  ln -s "$command" "$HOME/.local/bin/$(basename "$command")"
done
```

`ln -s` fails rather than replacing an existing command. Keep `$HOME/.local/bin` on `PATH`.
Configuration is through the environment and service overrides; no `.env` file is loaded
automatically. See `config/jarvis.env.example` for common settings. For an individual command,
export the selected settings in the shell. For a user service, create a private local
environment file and a drop-in with `EnvironmentFile=%h/.config/jarvis/jarvis.env`.

Optional Spotify uses your own developer application/client ID, redirect URI, and local
receiver. OAuth tokens and go-librespot configuration live under the user's private state
and configuration directories. They must not be copied into this repository. Local music
requires a separately created `data/music/library.json` and media library.

## Service templates and installation

`systemd/user/` contains portable templates for the `$HOME/Jarvis` layout. `%h` and `%t`
refer to the service user's home and runtime directory. The wake service's
`20-single-command.conf` sets one command per wake phrase; `30-music-duck.conf` handles
abnormal-exit player recovery. The SAM3 template uses the current `bin/run_sam.sh` path.

The stream template uses the default Pulse/PipeWire microphone. The existing machine's
installed stream and log configuration selects its BRIO explicitly; configure
`JARVIS_STREAM_MIC` and `JARVIS_LOG_AUDIO_SOURCE` on a new machine as needed. The remote
stream listens on TCP port 5000 when explicitly started; use your existing private network.

On a new machine, compare templates and configure hardware before copying selected units
to `~/.config/systemd/user/`. Copy the wake override directory along with the wake unit.
Then run `systemctl --user daemon-reload` and start only the services you intend to use.
Captain's Log and music are on-demand services. Starting wake/camera/stream services
activates the corresponding hardware. The source migration updated installed user-service paths and restarted only the
previously active wake listener and SAM3 watcher. A fresh installation still requires
reviewing and installing the templates explicitly.

## Recovery data

Back up private recordings, footage, masks, voice profiles, local music, model caches,
and credentials separately. Git restores source only. `docs/READINESS.md` records which
checks were run and the limits of the setup verification.
