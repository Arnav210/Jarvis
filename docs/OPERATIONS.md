# Operations

These checks are silent and read-only.

```bash
cd /home/toby/Jarvis
systemctl --user is-active jarvis-wake.service
systemctl --user is-active jarvis-sam3.service
systemctl --user status jarvis-stream.service --no-pager
pgrep -af '/home/toby/Jarvis'
readlink -f Masks/latest
python3 -m json.tool Masks/latest/manifest.json | head -80
journalctl --user -u jarvis-wake.service -n 50 --no-pager
journalctl --user -u jarvis-sam3.service -n 80 --no-pager
du -sh Footage Masks
```

## Source validation

With test dependencies installed in a development environment:

```bash
python tools/check_repository.py --history
python tools/run_checks.py
systemd-analyze --user verify systemd/user/*.service
```

The audit does not import optional vision modules. Some load models at import time.
The regression runner isolates state and uses synthetic media with silent output.
Service validation checks templates only and does not install or start them.

## Before a commit

```bash
git status --short
git diff
git diff --cached --name-only
git diff --cached
```

Do not trigger audio playback, alarms, volume changes, camera capture, enrollment, or destructive cleanup as part of routine health verification.

## Command console

`jarvis-status --open` opens the desktop view without recording or playback. `jarvis-status` views it in the current terminal; press Q to close the view. Check `$XDG_RUNTIME_DIR/jarvis-status/window.log` if a desktop window fails to open. The console uses the existing desktop session and opens no network port.
