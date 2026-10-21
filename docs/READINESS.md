# GitHub preparation report

Completed 2026-10-20 on the live Ubuntu Jarvis installation.

## Result

The source is prepared for the public GitHub repository `Arnav210/Jarvis`. The local baseline includes the
previously uncommitted working source and launcher moves, source allowlists, setup and
architecture documentation, environment snapshots, model inventory, service templates,
existing regression checks, a synthetic music fixture, source/history audit tooling,
and a GitHub Actions workflow.

## Verified

- Exported the complete proposed Git source tree to a separate temporary directory and
  ran checks there, without copying ignored files, recordings, models, or environments.
- All 44 unit tests passed, along with the console design suite (55 layout scenarios),
  silent MPV duck/recovery checks, and music-panel integration checks.
- Music tests generate temporary silent WAVs and use temporary IPC/state directories;
  they do not read the household music library or use the room speaker.
- Source audit passed: Python parsing, shell syntax, first-party import visibility,
  source size/type checks, and 10 private-path exclusion probes.
- Reachable Git history and proposed files were checked for private/generated paths
  and recognizable credential patterns. No matches were found. Pattern scanning is not
  a guarantee that every possible secret is detectable.
- Repository service templates passed `systemd-analyze --user verify`.
- The preserved SAM3 patch applied cleanly to the recorded upstream file versions and
  reproduced the existing local changes in a temporary directory.
- Changes to the two optional depth helpers are whitespace only, with identical ASTs.
- Active voice/control scripts, launchers, the SAM3 processing script and checkout,
  and installed service files were preserved. No live units were installed or restarted.

## What changed

- The explicit Git allowlist now includes the current first-party modules and tests.
- `README.md`, `docs/SETUP.md`, architecture, operations, and repository policy explain
  the existing layout and recovery process.
- Version snapshots cover system Python and six dedicated Python environments.
- `docs/DEPENDENCIES.json` records upstream revisions, system packages, and the configured
  Ollama model digest where available; `docs/MODELS.json` records model file checksums.
- The wake templates include the installed one-command override. The SAM3 template
  points to `bin/run_sam.sh`; portable templates use `%h` and a configurable stream microphone.
- Existing tests no longer depend on private music or installed command shortcuts;
  stale microphone-test stubs were updated to the current command ownership interface.
- GitHub Actions runs the audit and isolated checks after publication.

## Private data excluded

All `data/` contents, including Captain's Log recordings and music; `Footage/`; `Masks/`;
`VoiceProfiles/`; model/voice downloads; environments; caches; credentials; and generated
state remain local. The history audit found no such paths in reachable commits.
Git is not a backup for these files; preserve them separately.

## Verification limits

The clean source snapshot was tested using the existing Python 3.12 test interpreter and
system MPV. A fresh full dependency installation, live wake detection, audible speech,
camera capture, and SAM3/depth inference were not run. Environment files are observed
snapshots, not a claim of portable hardware setup. The GitHub Actions job is configured
and its commands passed locally; a hosted Actions run requires the future GitHub push.

## Publication status

The public repository is https://github.com/Arnav210/Jarvis. The reviewed source and
existing local history will be joined with its initial README commit without a force push.
First-party open-source licensing has not been selected; third-party notices are preserved.
No private runtime data or media is included. Publication does not deploy service templates.

## Source organization update — 2026-10-21

First-party modules are now organized under `src/jarvis/`, tests consolidated under
`tests/`, and computer-awareness documentation moved into `docs/`. Launchers,
subprocess paths, installed user-service definitions, and repository templates were
updated together. `Footage/` and `Masks/` remain top-level private directories.
The wake listener and SAM3 watcher returned to active state after migration. This
does not establish physical wake detection, room audibility, or model inference.
The depth system service uses a compatibility entry point until an administrator
changes its root-owned unit. Third-party checkouts and model environments stay put.

## Public-release review — 2026-10-21

The current organized source and reachable Git history passed the source/privacy audit.
All 72 unit tests and the three existing console/music integration suites passed.
The tests used isolated state, synthetic audio, and silent MPV output. No live service
was restarted and no hardware capture or playback test was performed for publication.
SAM3 patch attribution and the original third-party license are retained. Local media,
recordings, birthday settings, briefing contents, model files, and credentials remain excluded.
