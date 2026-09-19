# Project verification and live-mode notes

- `bash scripts/run-live.sh` starts the local-storage Gemini mode on 127.0.0.1:8000; `scripts/run-local.sh` defaults to explicitly scripted mode. Both load the ignored `.env` without printing credentials.
- `GEMINI_API_KEY` is server-only. The verified generation model on 2026-09-19 is `gemini-3.6-flash`; model metadata availability alone does not prove generation access.
- Live inputs are MP4, at most 14 MB and 60 seconds. External processing requires explicit user consent; never silently fall back to fixture detections.
- Run `uv run python tools/verify.py --profile cpu all`, `uv run python -m pytest backend/tests/integration/system backend/tests/integration/security -q`, and `pnpm exec playwright test --config infra/playwright.config.ts` for regression verification.
- With explicit permission for provider charges/video transfer, run `E2E_LIVE_APPROVED=1 E2E_MODE=gemini node scripts/e2e-reusable-app.mjs`. This records same-app/same-version reuse on distinct red- and green-signal videos. The older e2e-real-backend script tests separate scripted apps, not reuse or real accuracy.
- Distinguish model-reported candidate findings, inconclusive findings, genuine completed no-match runs, and failed runs. Synthetic smoke-test success is not general real-world accuracy.
- Local-state JSON snapshots persist apps, versions, media metadata, runs and reviews. Use one server process per data directory; do not delete data or restart an older in-memory demo without permission.
