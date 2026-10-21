# Existing SAM3 compatibility patch

`sam3-local-cpu.patch` preserves the local changes already present in the SAM3 checkout
on 2026-10-20. Upstream: https://github.com/facebookresearch/sam3.git
Base revision: `660a5e9e1b8b4c02c0ad97229b88a09a6e4ff5b7`.
The accompanying upstream license is retained as `SAM3-LICENSE`.
See `docs/SETUP.md` for applying the patch on a fresh checkout. The preparation process
does not apply it to the active checkout and does not establish CPU inference performance.
