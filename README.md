# Jarvis

Local voice and vision assistant running on the Ubuntu Mac mini at `/home/toby/Jarvis`.

## Architecture

Jarvis has two main pipelines:

1. Voice: PipeWire microphone -> openWakeWord -> `jarvis-listen` -> Whisper.cpp and speaker recognition -> deterministic router -> local Ollama fallback -> Piper speech.
2. Vision: `jarvis-camera` -> `Footage/` -> `run_sam.sh` -> SAM3 -> timestamped `Masks/runs/` output -> `Masks/latest` -> object monitor and scene-summary tools.

See `docs/ARCHITECTURE.md` for the tracked component map and `docs/OPERATIONS.md` for safe checks.

## Repository policy

This repository tracks behavior, not household data. The `.gitignore` is a privacy-first allowlist. It excludes photographs, masks, voice profiles, conversation history, models, virtual environments, caches, generated state, backup copies, and nested third-party repositories.

When adding a new Jarvis source file, add an explicit allow rule to `.gitignore`, review `git status --short`, and inspect the staged diff before committing.

## Safe change workflow

```bash
git switch -c feature/short-name
# Edit and test one feature.
git diff
git add <specific-files>
git diff --cached
git commit -m "Describe the change"
```

After deployment, restart only the affected service and verify its status and journal. Prefer `git revert <commit>` for a committed rollback.

## Local-only identity

The initial repository uses the repository-local identity `Jarvis Maintainer <jarvis@localhost>`. It does not change global Git settings and can be replaced later with the maintainer's preferred identity.
