# Authorized real development dataset

This directory is a framework only. **No real footage or permission is included.** Only an authorized human operator may add source references and rights records. Never commit restricted media, credentials, personal data, or a claim of permission created by an agent.

## Format

`manifest.schema.json` documents schema version 1 and `manifest.template.json` shows video and prompt entries. Create the operator-owned `manifest.json` here. Every case records provenance, stable source/recording and camera groups, fixture type (`real` or honestly declared `staged`), split, rights record, and independent human label review.

Video entries use integer source milliseconds and a SHA-256 of the exact source bytes. Truth intervals contain `start_ms`, `end_ms`, non-negative `uncertainty_ms`, and `positive`, `negative`, or `unknown`. The supported traffic footage must visibly contain the governing signal, stop line, and approach lane; all three evidence markers must be true. A model must not be the sole ground-truth reviewer.

## Adding authorized data

1. Obtain human authorization and retention/use terms before copying or referencing anything.
2. Put the approval record in `../licenses/` using its template. The approver must be real and authorized; do not manufacture values.
3. Keep restricted bytes outside version control. Set `source_path` relative to this manifest (it may point to an operator-controlled local mount), then compute `sha256sum` over the exact bytes.
4. Copy and edit `manifest.template.json` into the untracked/operator-managed `manifest.json`. Use `development` here. Group every clip from one recording/camera with stable `source_id` and `camera_group` values.
5. Have a human review labels and evidence, then run `uv run python tools/validate_dataset.py`. Inventory shortfalls or absent media report `BLOCKED`; they are not success.

Synthetic fixtures stay in `fixtures/synthetic/` and never count toward real-video quality evidence. Target inventory is 30 labeled video cases and 20 prompt cases overall, with positive/negative/unknown video coverage and a separately frozen held-out portion.
