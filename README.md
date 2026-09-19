# Vision App Creator

Create reusable video-analysis apps from a prompt and a seed video, then run them on new videos with cloud Gemini.

## Bootstrap

```sh
uv python install 3.12
uv sync
pnpm install --frozen-lockfile
```

## Run with cloud Gemini

The only required credential is `GEMINI_API_KEY`, available from
[Google AI Studio](https://aistudio.google.com/apikey). Supply it to the backend's
environment or the ignored `.env` file. In Devin, save it as a secret named
`GEMINI_API_KEY` and inject that secret when starting the server.

```sh
VISION_APP_DATA_DIR="$HOME/.local/share/vision-app-live" bash scripts/run-live.sh
```

Open http://127.0.0.1:8000. The default model is `gemini-3.6-flash`;
`GEMINI_MODEL` can select another model with video and structured-output support.
The server sends the prompt and video to Google for billable analysis. Keys stay
on the server. Cloud failures are reported and never replaced by fixture detections.
Use one server process per data directory.

1. Choose **New app**, upload a seed MP4, and describe the visible activity to detect.
2. Send the prompt and **Accept proposal** to save the reusable definition.
3. Select **Run app** to open its separate use page.
4. Upload another video. Analysis starts automatically and shows a plain result.

Prompts can describe traffic or other observable activity, such as a moving
object, visible smoke, an animal entering a scene, or a package being left
behind. Gemini compiles the instruction into reusable visual conditions; each
new video is analyzed independently. A seed containing a match does not force
later videos to match.

Current scope: MP4 videos up to **60 seconds and 14 MB**, with **1–3 visual
conditions** per app. This supports general visual-event detection, not every
possible vision task: identity recognition, guaranteed exact counts,
deterministic tracking, and definitive legal judgments are unsupported.
Uncertain observations remain uncertain in the result.

`bash scripts/run-local.sh` is the separate scripted demo. Its fixture results
do not depend on video content, and the UI explicitly says the video was not
analyzed.

### Live acceptance test

With the Gemini server running and the key configured:

```sh
E2E_LIVE_APPROVED=1 E2E_MODE=gemini node scripts/e2e-reusable-app.mjs
```

This makes real provider calls and checks the same app/version on
`fixtures/synthetic/video/red_light_violation.mp4` (red-light crossing) and
`fixtures/synthetic/video/green_light_crossing.mp4` (no red-light crossing).
Synthetic checks do not establish accuracy for arbitrary real-world footage.

## Verify

```sh
uv run python tools/verify.py static
uv run python tools/verify.py contracts
uv run python tools/verify.py component --area fixtures
pnpm --filter @vision-app/web test
pnpm --filter @vision-app/web typecheck
```

Core imports are CPU-only. Install optional dependencies explicitly with `uv sync --extra vision`, `--extra cloud`, or `--extra evals`. Secrets are supplied only through environment variables; none are committed.
