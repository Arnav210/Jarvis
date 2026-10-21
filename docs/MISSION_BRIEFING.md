# Daily mission briefing

Edit the private text file before class:

```bash
nano ~/Jarvis/data/mission-briefing.txt
```

For example, replace the starter with your actual class plan:

```text
DATE: 2026-10-21
MISSION: Bring gesture controls online

TASKS:
- Test detection under classroom lighting
- Tune the gesture thresholds
- Demonstrate three working gestures

ASSIGNMENTS:
- Team member: test and record results

SUCCESS: Each gesture works five times in a row.
```

DATE, MISSION, and at least one TASK are required. ASSIGNMENTS and SUCCESS are optional.
Use an actual YYYY-MM-DD date and UTF-8 text. Lines beginning with # are comments.
Each list supports up to 12 items, with 240 characters per item. The file is limited
to 16 KiB. Text is read directly: it is not executed or interpreted by the AI.

Check it silently from the terminal:

```bash
~/Jarvis/bin/jarvis-briefing --preview
```

Then say **Hey Jarvis**, followed by **mission briefing**. The reactor starts up,
Jarvis reads the mission, tasks, optional team assignments, and success condition,
and the console keeps the briefing visible until the next command or reset.
Up/Down scroll on smaller screens. R cancels/resets; Q closes the current view.
If a console was already open during installation, close and reopen it once with
`jarvis-status` to load the new renderer.

A date different from today produces a visible and spoken date warning. A missing,
blank, or malformed file produces an explanation rather than invented tasks.
The installed starter is intentionally blank so it cannot masquerade as today's plan.
The briefings are manually triggered; no class-time schedule is assumed.

`JARVIS_BRIEFING_FILE` can select a different text file. Otherwise the default is
`$JARVIS_HOME/data/mission-briefing.txt`, with JARVIS_HOME defaulting to `$HOME/Jarvis`.
Actual class briefings stay under ignored `data/`; only the blank template is tracked.
No Google account or network connection is required.


## Mission-control styling

The briefing uses bordered objective, task, assignment, and success panels, with a
date header and directive count. Wider/taller terminals show an animated reactor
sidebar; roomy displays use the larger reactor. Small screens retain scrolling and
keep short task lists visible. The startup has a reactor reveal and a short text
accent; no tasks are marked complete automatically. R and Q retain their behavior.
Close and reopen an existing console once after a renderer update to load it.
