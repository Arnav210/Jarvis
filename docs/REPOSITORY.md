# Repository policy and organization

## Tracked source

First-party Python modules remain at their existing paths. Terminal commands are in `bin/`.
Tests remain in their two current locations, with a single runner under `tools/`.
Documentation, service templates, example settings, dependency snapshots, and the preserved
SAM3 compatibility patch are included explicitly in `.gitignore`.
Third-party source and model weights are provisioned separately; see `SETUP.md`.

## Private files

Never include `data/` (including all Captain's Log recordings and music), `Footage/`,
`Masks/`, `VoiceProfiles/`, `models/`, `voices/`, virtual environments, caches, credentials,
or runtime state. Keep a separate private backup of irreplaceable recordings and profiles.
`sam3/`, `whisper.cpp/`, `Depth-Anything-3/`, and `Jarvis-Web/` are excluded. The web project
is not included implicitly; it needs its own explicit scope and review.
Editor backups and the stray `ha256sum jarvis_console_layout.py` file remain ignored.

Ignore rules do not remove already committed data. Run `tools/check_repository.py --history`
before publication; it inspects reachable file paths and recognizable credential patterns.
Review content as well: a pattern scan cannot prove the absence of every possible secret.

## Review and publication

Use explicit paths for staging and inspect the full staged diff. Moving a launcher is a
deletion of the old path plus an addition under `bin/`; review both together.
Run the source audit and isolated regression checks before a baseline commit.
No GitHub remote is required for local preparation. The first repository should be private;
first-party public licensing has not been selected. Do not grant third-party rights implicitly.

## Service reconciliation

The installed wake service stores the one-command setting in `20-single-command.conf`.
The repository now follows the same structure and retains `30-music-duck.conf`.
The installed SAM3 unit still names the old root launcher; the repository template uses
the current `bin/run_sam.sh` path. Templates now use `%h` instead of a particular username.
The stream template accepts `JARVIS_STREAM_MIC` rather than embedding a device serial.
These changes prepare future installation; live units are not replaced or restarted.

## Future refactoring

Moving Python modules into a package and consolidating tests are separate code changes:
imports, launchers, service paths, and path-sensitive tests must move together.
The current preparation keeps deployed paths stable.
