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

```bash
bash -n jarvis-ai jarvis-camera jarvis-enroll jarvis-identify jarvis-listen jarvis-speak run_sam.sh
python3 -m py_compile jarvis_ai.py jarvis_assistant.py jarvis_speaker.py jarvis_wake.py sam3_process.py object_monitor/object_monitor/object_monitor.py
systemd-analyze --user verify systemd/user/*.service
```

## Before a commit

```bash
git status --short
git diff
git diff --cached --name-only
git diff --cached
```

Do not trigger audio playback, alarms, volume changes, camera capture, enrollment, or destructive cleanup as part of routine health verification.
