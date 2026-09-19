# Modal deployment binding

The binding uses the shared `vision_app.runtime` composition through the callable named by
`VISION_APP_MODAL_RUNNER`; it does not implement a second cloud-only pipeline.

## Environment contract

| Variable/secret | Required | Purpose |
|---|---:|---|
| `MODAL_TOKEN_ID` | deploy/smoke only | Modal CLI identity; never sent in run input |
| `MODAL_TOKEN_SECRET` | deploy/smoke only | Modal CLI credential; never sent in run input |
| `VISION_APP_MODAL_RUNNER` | worker | `module:callable` shared-runtime composition |
| `GOOGLE_CLOUD_PROJECT` | worker | Firestore/GCS project |
| `GOOGLE_APPLICATION_CREDENTIALS` | worker when not using workload identity | service credential path |
| `GOOGLE_API_KEY` | worker when Gemini is enabled | provider secret in `vision-app-runtime` |

Run inputs contain owned IDs, attempt fence, opaque storage reference, generation/hash, and
validated spec/calibration manifests. They never contain signed URLs, local paths, or credentials.
The `vision-app-runtime` Modal secret and `vision-app-checkpoints` volume must be provisioned by an
operator. The volume is mounted read-only by convention at `/models`; checkpoint revisions must be
pinned by runtime composition.

## Commands

```bash
# Definition/import validation, no deployment or account required
uv run python -c 'from vision_app.adapters.modal.app import health; assert health()["status"] == "ok"'

# Operator-approved deploy (requires Modal installed and credentials)
uv run modal deploy backend/src/vision_app/adapters/modal/app.py

# Explicit live smoke (never run by component/integration verification)
MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... \
  uv run python -m vision_app.adapters.modal.live_smoke
```

`health_check` is a CPU function. `run_gpu` uses an L4, a one-hour hard timeout, and a five-minute
scale-down window. Cancellation is propagated by `ModalExecutor.cancel` to the invocation client;
the worker runtime must also poll its cancellation token between frames and model calls.
