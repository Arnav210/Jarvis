# Repository policy and organization

## Tracked source

First-party Python code lives in `src/jarvis/`, grouped by function. Terminal commands
are in `bin/`. Core tests are in `tests/`, with one runner under `tools/`.
Website-specific tests live under `Jarvis-Web/tests/`.
Documentation, service templates, example settings, dependency snapshots, and
the SAM3 compatibility patch are included explicitly in `.gitignore`.
Third-party source and model weights are provisioned separately; see `SETUP.md`.

## Private files

Never include `data/` (including all Captain's Log recordings and music), `Footage/`,
`Masks/`, `VoiceProfiles/`, `models/`, `voices/`, virtual environments, caches, credentials,
or runtime state. Keep a separate private backup of irreplaceable recordings and profiles.
`sam3/`, `whisper.cpp/`, and `Depth-Anything-3/` are excluded.
For `Jarvis-Web/`, only `frontend/index.html`, `frontend/app.js`,
`frontend/style.css`, `backend/server.py`, `tests/test_history.py`, and
`tests/test_masks.py` are explicitly included. All other website files remain
excluded, including backups, tools, credentials, logs, and generated data.
The website reads private captures and masks at runtime; those assets are never
part of the source repository.
Old editor backups and the stray diagnostic text file are preserved under ignored `archive/`.

Ignore rules do not remove already committed data. Run `tools/check_repository.py --history`
before publication; it inspects reachable file paths and recognizable credential patterns.
Review content as well: a pattern scan cannot prove the absence of every possible secret.

## Review and publication

Use explicit paths for staging and inspect the full staged diff. Moving a launcher is a
deletion of the old path plus an addition under `bin/`; review both together.
Run the source audit and isolated regression checks before a baseline commit.
No GitHub remote is required for local preparation. The publication target is the public repository `Arnav210/Jarvis`.
First-party open-source licensing has not been selected; visibility does not grant an
additional reuse license. Third-party licenses remain separate.

## Service reconciliation

Repository templates and installed user units now use the `src/jarvis/` paths.
The SAM3 watcher uses `bin/run_sam.sh`; its processor source is byte-identical to
the baseline. Existing user-service overrides and hardware configuration remain.
The wake and SAM3 watcher services were restarted because they were already active.

The root-owned system depth unit retains `depth_service.py`, a compatibility entry
point forwarding to `src/jarvis/vision/depth_service.py`. Updating the system unit
itself requires an administrator. See `REORGANIZATION.md` for the scope of this phase.
