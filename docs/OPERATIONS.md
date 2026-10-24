# Operations

These checks are silent and read-only.

```bash
cd "$HOME/Jarvis"
systemctl --user is-active jarvis-wake.service
systemctl --user is-active jarvis-sam3.service
systemctl --user status jarvis-stream.service --no-pager
pgrep -af "$HOME/Jarvis"
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


## Automatic room observations

`jarvis-capture.timer` takes one picture every ten minutes from 8:10 AM
through 3:40 PM, including both endpoints, Monday through Friday in America/Los_Angeles
(Pacific time, following daylight saving changes). This is 46 scheduled
pictures per weekday; no scheduled pictures are taken overnight or on weekends.
The photo command also rejects manual captures on Saturdays and Sundays in Pacific time
before accessing the camera. There is no weekend override.
Each complete picture is published atomically to `Footage/`. The existing
`jarvis-sam3.service` processes it into `Masks/runs/`, then the object monitor
saves the people count for the website's daily occupancy graph. Processing
can take several minutes. Failed camera captures do not publish partial files. When the shared local
camera feed is active, snapshots reuse it so the room stream can continue.
The timer does not replay missed pictures after downtime.

Install the two `systemd/user/jarvis-capture.*` files in
`~/.config/systemd/user/`, then run `systemctl --user daemon-reload` and
`systemctl --user enable --now jarvis-capture.timer`. The watcher must include
`moved_to` events for atomic capture publishing. Restart it after updating
`bin/run_sam.sh`. User lingering is enabled on the live host so the timer
continues without an SSH session. Camera permissions currently come from the
active Ubuntu desktop login: keep toby logged into the desktop and the Mac
mini awake. Logging out or rebooting to the login screen can remove webcam
access until the next desktop login.

Check the schedule with `systemctl --user list-timers jarvis-capture.timer`.
Check failures with `journalctl --user -u jarvis-capture.service` and
`journalctl --user -u jarvis-sam3.service`. Pause scheduled capture with
`systemctl --user disable --now jarvis-capture.timer`; resume with
`systemctl --user enable --now jarvis-capture.timer`. Originals and generated
masks remain private ignored runtime files. There is no automatic retention
cleanup; monitor disk space as the archive grows.


### Website capture status

The live capture-status panel reads systemd timer/service state and saved pictures
without opening the webcam. It displays the next actual timer trigger, the last
picture's analysis, and today's scheduled-slot progress separately from other
pictures. A picture within the minute after a scheduled slot satisfies that slot;
misses before the timer was enabled are excluded. Missing captures have a
one-minute grace period, and incomplete analysis is flagged after 15 minutes.
Unknown scheduler state is displayed as unavailable. The panel always describes
today's live system, even when the gallery is displaying a historical date.


## People count and overlapping detections

From the person-overlap update onward, `object_monitor.py` counts every SAM3
`person` detection with a score of at least 0.50. Bounding-box overlap and
containment do not remove person detections. Duplicate suppression still applies
to other object categories. This deliberately trusts SAM3's separate person
masks, including heavily overlapping boxes; genuinely duplicate person masks may
therefore inflate the estimate.

New per-capture reports record
`person_count_method: sam3_score_0.50_no_overlap_filter`. The running watcher
launches the monitor afresh after each successful analysis, so the next completed
capture uses this rule without a service restart or an extra photograph. Existing
reports and historical counts retain their original values; no historical
capture, event, or inventory record is rewritten by this source change.
The website and spoken room questions consume the newly saved counts as usual.
