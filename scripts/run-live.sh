#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VISION_APP_ANALYSIS_MODE=gemini
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.6-flash}"
export VISION_APP_DATA_DIR="${VISION_APP_DATA_DIR:-/tmp/vision-app-live-acceptance}"
exec bash "$ROOT/scripts/run-local.sh"
