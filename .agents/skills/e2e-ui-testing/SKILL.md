---
name: e2e-ui-testing
description: How to drive the vision-app-creator web UI end-to-end in scripted mode (app creation, video upload, calibration, runs) with computer-use tools
---

# E2E UI testing for vision-app-creator

## Server

- `bash scripts/run-local.sh` (scripted mode) or `scripts/run-live.sh` (Gemini) serves the built bundle + API at http://127.0.0.1:8000. Verify with `curl -s http://127.0.0.1:8000/v1/runtime` — scripted mode reports `"analysis_mode":"scripted"`.
- Scripted mode is fixture-driven: every uploaded MP4 yields the same result — 1 event, `machine_decision: supported`, `source_range` 2900–3100 ms, evidence thumbnail+clip available. Run completes in ~1s (no real detection).
- State persists in the data dir's `local-state.json` (e.g. /tmp/vision-app-e2e). App/run/event/asset ids increment (`app-NNNN`, `run-NNNN`, `media_*`).

## UI flow (exact controls)

- App list (`#/`): "New app" button → `#/app/<id>` (workspace = creation page).
- Workspace: chat textbox labelled "Message" + "Send". A supported prompt (e.g. "detect cars crossing the stop line while the light is red") returns a proposal card with "Accept proposal". Unsupported prompts show "Request not supported" and no Accept button.
- Source: `input[type=file]` inside "Upload source video" panel. **Computer-use cannot set file inputs directly** — click "Choose File", then in the GTK file chooser press `ctrl+l`, type the absolute path, Enter (or click the file in the list if the chooser remembers the directory).
- Calibration: the editor pre-loads the standard stop-line + ROI geometry (no drawing tools). Click "Confirm calibration" → status text "Source ready and calibration confirmed."
- Use page (`#/app/<id>/use`): reached via the workspace's "Run app" button or "← App" link on a run page. Has a "Run app" button (runs the currently attached source), an "Upload a video" file input (upload → auto-calibrate if needed → auto-run → navigates to the run page), and a "Run history" section linking to each run.
- Run page (`#/app/<id>/run/<runId>`): polls until status text "Run succeeded". Result banner (`aria-label="Run result"`) shows "1 finding" (red) for supported/candidate events, "No matches" (green), "Needs review" (amber), "Run failed" (red). "Findings timeline" markers (`aria-label="Jump to finding at X.Ys"`) seek the source video and select the event; evidence thumbnail (`alt="evidence"`) and clip ref appear. There is NO review UI (no Approve/Reject) and no event filter chips.

## Fixture videos

`/home/ubuntu/repos/vision-app-creator/fixtures/synthetic/video/*.mp4` (red_light_violation.mp4, green_light_crossing.mp4, etc.). All produce the same fixture finding in scripted mode — differing content does NOT change results.

## Tooling gotchas

- Launching Chrome with `--new-window` may leave a stray "New Tab" window that steals CDP/devtools focus; close it (`wmctrl -c "New Tab - Google Chrome"`) if `browser_console`/`read_dom` return the wrong page.
- The browser_console tool can lose its CDP binding when a window closes; screenshots alone already prove seeks (video shows `0:02 / 0:05` and the frame changes from green to red signal at the event time).

## Devin Secrets Needed

- None for scripted mode. `GEMINI_API_KEY` only for live/Gemini mode.
