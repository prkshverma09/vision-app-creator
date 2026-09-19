#!/usr/bin/env bash
set -euo pipefail

# R01 is intentionally opt-in: report names/status only and never print secret values.
required=(
  GOOGLE_CLOUD_PROJECT
  GCS_BUCKET
  FIRESTORE_DATABASE
  FIREBASE_PROJECT_ID
  GEMINI_API_KEY
  MODAL_TOKEN_ID
  MODAL_TOKEN_SECRET
  R01_SAMPLE_FRAME
  R01_DATA_RIGHTS_CONFIRMED
)
optional=(
  GOOGLE_APPLICATION_CREDENTIALS
  GEMINI_MODEL
  GEMINI_MODEL_REVISION
  VISION_APP_MODAL_RUNNER
  R01_MODAL_APP
  R01_MODAL_RFDETR_FUNCTION
  R01_SAMPLE_FRAME_CONTENT_TYPE
  R01_STAGING_BASE_URL
)

printf '%s\n' 'R01 live acceptance environment (values are never displayed):'
missing=()
for name in "${required[@]}"; do
  if [[ -n "${!name:-}" ]]; then
    printf '  [set]     %s\n' "$name"
  else
    printf '  [missing] %s\n' "$name"
    missing+=("$name")
  fi
done
for name in "${optional[@]}"; do
  if [[ -n "${!name:-}" ]]; then
    printf '  [set]     %s (optional)\n' "$name"
  else
    printf '  [unset]   %s (optional)\n' "$name"
  fi
done

if ((${#missing[@]})); then
  printf '\nR01 remains BLOCKED; no live or paid calls were made.\n'
  printf 'Set every required variable only after operator, budget, and data-rights approval.\n'
  exit 0
fi

if [[ "${R01_DATA_RIGHTS_CONFIRMED}" != "yes" ]]; then
  printf '\nR01 remains BLOCKED: R01_DATA_RIGHTS_CONFIRMED must explicitly equal yes.\n'
  exit 0
fi

if [[ -n "${FIREBASE_AUTH_EMULATOR_HOST:-}" ]]; then
  printf '\nR01 aborted: FIREBASE_AUTH_EMULATOR_HOST must be unset for the live gate.\n' >&2
  exit 2
fi

printf '\nAll automated-smoke prerequisites are explicit; starting real cloud/provider tests.\n'
uv run python -m pytest \
  backend/src/vision_app/evaluation/acceptance.py \
  -m 'live and cloud' -v
