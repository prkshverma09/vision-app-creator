#!/usr/bin/env bash
# Automated end-to-end API test for the local backend.
# Runs the full Viso-style flow: create app → chat → upload → calibrate → run → event.
set -euo pipefail

API="${VISION_APP_API:-http://127.0.0.1:8000}"
TOKEN="${VISION_APP_TEST_TOKEN:-token-local}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO="${VISION_APP_TEST_VIDEO:-$ROOT/fixtures/synthetic/video/red_light_violation.mp4}"

echo "=== Creating app ==="
APP=$(curl -s -X POST "$API/v1/apps" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"Red light crossing"}')
APP_ID=$(echo "$APP" | uv run python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "App: $APP_ID"

echo "=== Builder turn ==="
TURN=$(curl -s -X POST "$API/v1/apps/$APP_ID/turns" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"Detect cars crossing a stop line during a red signal"}')
echo "$TURN" | uv run python -m json.tool || true

echo "=== Accepting proposal ==="
SPEC=$(echo "$TURN" | uv run python -c "import sys,json; print(json.dumps(json.load(sys.stdin)['outcome']['version']['spec']))")
curl -s -X POST "$API/v1/apps/$APP_ID/versions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"spec\":$SPEC}" | uv run python -m json.tool || true

echo "=== Uploading video ==="
SIZE=$(stat -f%z "$VIDEO")
INIT=$(curl -s -X POST "$API/v1/uploads" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"filename\":\"red.mp4\",\"content_type\":\"video/mp4\",\"size_bytes\":$SIZE}")
UPLOAD_ID=$(echo "$INIT" | uv run python -c "import sys,json; print(json.load(sys.stdin)['upload_id'])")
UPLOAD_URL=$(echo "$INIT" | uv run python -c "import sys,json; print(json.load(sys.stdin)['upload_url'])")
echo "Upload: $UPLOAD_ID"
curl -s -X PUT "$API$UPLOAD_URL" -H "Authorization: Bearer $TOKEN" --data-binary @"$VIDEO" -H "Content-Type: video/mp4"
SOURCE=$(curl -s -X POST "$API/v1/uploads/$UPLOAD_ID/complete" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN")
ASSET_ID=$(echo "$SOURCE" | uv run python -c "import sys,json; print(json.load(sys.stdin)['asset_id'])")
echo "Source: $ASSET_ID"

curl -s -X POST "$API/v1/apps/$APP_ID/source" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"asset_id\":\"$ASSET_ID\"}" | uv run python -m json.tool || true

echo "=== Calibrating ==="
curl -s -X POST "$API/v1/apps/$APP_ID/calibrations" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"geometries":[{"id":"stop-line","kind":"line","label":"stop_line","points":[{"x":0.5,"y":0.0},{"x":0.5,"y":1.0}]},{"id":"signal","kind":"box","label":"signal-1","box":{"x1":0.85,"y1":0.05,"x2":0.95,"y2":0.18}}]}' \
  | uv run python -m json.tool || true

echo "=== Starting run ==="
RUN=$(curl -s -X POST "$API/v1/apps/$APP_ID/runs" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN")
RUN_ID=$(echo "$RUN" | uv run python -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Run: $RUN_ID"

for i in {1..10}; do
  sleep 1
  STATUS=$(curl -s "$API/v1/runs/$RUN_ID" -H "Authorization: Bearer $TOKEN")
  ST=$(echo "$STATUS" | uv run python -c "import sys,json; print(json.load(sys.stdin)['run']['status'])")
  echo "Run status: $ST"
  if [ "$ST" = "succeeded" ] || [ "$ST" = "failed" ]; then
    echo "$STATUS" | uv run python -m json.tool || true
    break
  fi
done

echo "=== Done ==="
