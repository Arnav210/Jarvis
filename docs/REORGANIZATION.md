# Source organization migration

First-party code now lives in `src/jarvis/`, grouped by assistant, audio, vision,
computer, music, UI, and recording. Imports use explicit package paths. Direct
script execution bootstraps `src/` for dedicated runtime environments without
installing or changing their dependencies. `pyproject.toml` supports fresh installs.

Unit tests live in `tests/unit_*.py`. The three existing standalone integration
scripts retain `tests/test_*.py` names. Run `tools/run_checks.py` for both kinds;
it uses isolated state, synthetic audio, and silent MPV output.

`Footage/` and `Masks/` remain separate top-level private directories. Other runtime
data, virtual environments, and third-party checkouts retain their current locations.
The object monitor keeps its existing private state directory. SAM3 source content
is unchanged. No model inference or camera capture is required for this migration.

`depth_service.py` is a small compatibility entry point for the root-owned installed
depth service. Its implementation is in `src/jarvis/vision/depth_service.py`. It can
be removed after an administrator updates that system unit to the new path.

Repository service templates and installed user-service paths move together.
Only already-running affected services need a restart. The separate web application
and third-party environments are outside this first-party source migration.
