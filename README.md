# Jarvis

A local voice and vision assistant for an Ubuntu computer, with wake-word detection,
local transcription and responses, speaker recognition, a terminal console, music controls,
and optional camera analysis and Captain's Log recording.

## Start here

- [Iron Man: Skyfall](docs/IRON_MAN.md): 54-second 3D ASCII film.

- [Daily mission briefing](docs/MISSION_BRIEFING.md): local text file, voice command, and silent preview.

- [Setup and recovery](docs/SETUP.md): environments, dependencies, models, configuration, and service installation.
- [Architecture](docs/ARCHITECTURE.md): component map and source layout.
- [Operations](docs/OPERATIONS.md): inspection and maintenance commands.
- [Repository policy](docs/REPOSITORY.md): source inclusion and private data boundaries.
- [Readiness report](docs/READINESS.md): preparation checks and verification limits.
- [Computer awareness](docs/COMPUTER_AWARENESS.md): bounded local inspection capabilities.

See [the migration notes](docs/REORGANIZATION.md) for compatibility and recovery details.

## Source layout

| Location | Purpose |
| --- | --- |
| `bin/` | User command launchers. |
| `src/jarvis/` | First-party package: assistant, audio, vision, computer, music, UI, and recording. |
| `systemd/user/` | Service templates and wake overrides. |
| `tests/` | Consolidated unit and silent integration checks, plus synthetic fixtures. |
| `tools/` | Repository audit and isolated test runner. |
| `requirements/`, `config/` | Observed dependency versions and example settings. |
| `patches/` | Preserved third-party SAM3 compatibility changes and upstream notice. |
| `docs/` | Setup, component map, model inventory, and operations. |

Keep the runtime checkout at `$HOME/Jarvis`: several modules assume this location.
Command shortcuts under `~/.local/bin/` point to the launchers in `bin/`.

## Private data stays local

Git tracks source and documentation. Captain's Log recordings under `data/`, camera footage
under `Footage/`, masks under `Masks/`, voice profiles, music, models, credentials, caches,
and virtual environments stay excluded. Third-party checkouts remain separate.
The allowlist requires each new source file or category to be explicitly included.

## Development checks

Install the test dependencies and MPV as described in the setup guide, then run:

```bash
python tools/check_repository.py --history
python tools/run_checks.py
```

These checks use temporary state and silent synthetic media. They do not establish that
live wake detection, room playback, camera capture, or model inference work on a new machine.

## Change workflow

Work on a branch, review `git diff`, stage explicit paths, and inspect `git diff --cached`
before committing. After a deployed code change, restart only the affected service and
verify its behavior. Repository templates are not automatically installed.
Use `git revert` for a committed rollback; keep private recovery backups separately.

No open-source license is selected for first-party code. This public repository shares the Jarvis3000 source for inspection.
No additional reuse license is granted for first-party code; choose a license deliberately
before offering it for public reuse. Third-party
code and model licenses remain separate. Git identity is repository-local.
