#!/usr/bin/env bash
# Start the Vision App Creator backend in local/demo mode.
# No API keys are required. The built frontend is served from / on port 8000.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE_OVERRIDE="${VISION_APP_ANALYSIS_MODE-}"
MODEL_OVERRIDE="${GEMINI_MODEL-}"
DATA_OVERRIDE="${VISION_APP_DATA_DIR-}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi

export VISION_APP_ANALYSIS_MODE="${MODE_OVERRIDE:-${VISION_APP_ANALYSIS_MODE:-scripted}}"
export GEMINI_MODEL="${MODEL_OVERRIDE:-${GEMINI_MODEL:-gemini-3.6-flash}}"
export VISION_APP_DATA_DIR="${DATA_OVERRIDE:-${VISION_APP_DATA_DIR:-/tmp/vision-app-data}}"
export VISION_APP_TEST_TOKEN="${VISION_APP_TEST_TOKEN:-token-local}"
export VISION_APP_TEST_WORKSPACE="${VISION_APP_TEST_WORKSPACE:-workspace-local}"
export VISION_APP_TEST_USER="${VISION_APP_TEST_USER:-local-user}"
export VISION_APP_FIXTURE_ANNOTATION="${VISION_APP_FIXTURE_ANNOTATION:-fixtures/synthetic/annotations/red_light_violation.json}"
export PYTHONPATH="backend/src"

pnpm --filter @vision-app/web build
uv run python -m vision_app.main
