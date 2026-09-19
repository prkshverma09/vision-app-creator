# Authorized held-out dataset

This directory contains only the held-out framework; no footage or authorization is supplied. Access and labels are evaluator-controlled. Never commit restricted bytes or invent permission.

Copy `manifest.template.json` to an operator-managed `manifest.json` only after following `../real/README.md` and creating a genuine rights record in `../licenses/`. The format is schema version 1 from `../real/manifest.schema.json`. Use split `heldout`, exact source SHA-256 values, human-reviewed truth intervals, and explicit signal/stop-line/approach-lane evidence.

Freeze `frozen_at`, manifests, labels, model settings, thresholds, and prompts before evaluation. Development and held-out cases must be separated by recording **and camera group**, not adjacent frames or clips. Never optimize prompts against held-out labels. Synthetic/staged results must be reported separately and cannot unblock missing real footage.

Run `uv run python tools/validate_dataset.py`. A missing authorized source or inventory shortfall deliberately returns status `BLOCKED` (exit 2), while malformed metadata, rights, hashes, evidence, labels, or split overlap returns `INVALID` (exit 1).
