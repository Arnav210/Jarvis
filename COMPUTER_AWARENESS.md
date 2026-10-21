# Jarvis computer awareness

This upgrade adds a local AI planner that selects read-only inspection tools and can use one tool's result to choose the next inspection. Measurements in spoken replies come from computed tool summaries.

## Voice examples

Say a fresh "Hey Jarvis" before each command:

- "How much storage does the music folder take up?"
- "Which folders inside Jarvis take up the most space?"
- "Find the Downloads folder and tell me how big it is."
- "What are the largest files in that folder?"
- "How much free disk space do we have?"
- "How much memory is available?"
- "Is the jarvis-wake service running?"

Folder context expires after ten minutes. Music, playback ducking, and one command per wake remain handled by their existing routes.

## Limits and behavior

- Filesystem inspection is limited to the user's home directory. The tools inspect metadata and names, not file contents.
- Folder sizes are sums of logical file sizes, not allocated disk blocks. Links and other mounted filesystems are skipped during size scans. Partial scans are labeled.
- Size scans have time and entry limits. Filename searches also have limits.
- CPU figures are load averages, not utilization percentages.
- Service inspection reads state only. It cannot restart services.
- No arbitrary terminal command, file modification, installation, or deletion tool is exposed.
- Runtime context and the latest tool trace are stored under `$XDG_RUNTIME_DIR/jarvis-computer-<uid>/`, with private permissions.
- Normal chat continues using its current model. Computer inspection uses `JARVIS_COMPUTER_MODEL` (default `qwen3.5:2b`).

## Files and commands on Ubuntu

Source: `/home/toby/Jarvis/jarvis_computer.py`; integration: `/home/toby/Jarvis/jarvis_ai.py`.

Silent typed use:

```bash
jarvis-computer "How much storage does the music folder take up?"
jarvis-computer --help
```

The CLI prints answers without playing audio. Voice requests use Jarvis's existing speaker and terminal display. It needs no new service. Functional tests run with `python3 -m unittest test_jarvis_computer` from the Jarvis directory.
