# R01 live acceptance: approved staging deployment and smoke

**Gate status:** human/operator gated. This checklist records G4 / L01 evidence; it does not
certify held-out quality (R02), production safety, or legal suitability. Mocked, scripted,
emulator, or recorded-boundary tests **cannot pass this gate**. Run it only with approved
credentials, budget, and documented rights to the test footage.

Authority: [PRD](../PRD.md), [design section 11](../DESIGN.md#11-privacy-operations-and-deployment),
[design L01](../DESIGN.md#152-live-and-human-acceptance-mandatory-g4g6), and
[R01 task card](../IMPLEMENTATION_PLAN.md#r01--approved-staging-deployment-and-live-smoke).
Modal deployment details are in [infra/modal/README.md](../infra/modal/README.md).

## 1. Human approval and prerequisites

Do not start paid calls or deployment until an authorized operator checks every item.

- [ ] Dedicated staging GCP project exists; billing, quota ceiling, and operator are identified.
- [ ] Private staging GCS bucket exists with least-privilege service identity and lifecycle policy.
- [ ] Native Firestore database and required indexes/rules exist in the staging project.
- [ ] Firebase Authentication project, expected issuer/audience, test user, and authorized frontend
      origin are configured. Emulator tokens are not accepted by staging.
- [ ] Gemini API key is stored outside the repository; the selected model is available and quota
      plus a hard spend limit are approved.
- [ ] Modal token belongs to the approved workspace and is stored outside the repository.
- [ ] `vision-app-runtime` Modal secret and read-only-by-convention
      `vision-app-checkpoints` volume are provisioned.
- [ ] A pinned RF-DETR checkpoint/model revision is cached on Modal; its license and provenance
      are recorded. The deployed detection function is verified to use that checkpoint.
- [ ] One or two short synthetic test videos and a representative sample frame are approved for
      this test. Their owner, permitted use, retention deadline, and deletion owner are documented
      in the restricted test record. Setting `R01_DATA_RIGHTS_CONFIRMED=yes` is an operator
      attestation, not a substitute for that record.
- [ ] External webhook delivery is disabled. Only action **preview** will be tested unless a
      separate destination and dispatch approval exists.

## 2. Environment contract

Export values in the invoking shell or approved secret manager. Never commit `.env` files,
service-account JSON, tokens, signed URLs, footage, or command output containing secrets.
Application Default Credentials or workload identity must resolve to the staging service identity.

| Variable | Required for | Contract |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCS, Firestore, deployed runtime | Dedicated staging project ID. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Cloud calls only when workload identity/ADC is unavailable | Path to an operator-managed credential file outside this repository. |
| `GCS_BUCKET` | GCS smoke/runtime | Private staging bucket name, without `gs://`. |
| `FIRESTORE_DATABASE` | Firestore smoke | Explicit database ID; use `(default)` only if that is the approved staging database. |
| `FIREBASE_PROJECT_ID` | Deployed E2E | Firebase project expected by identity verification. |
| `FIREBASE_AUTH_EMULATOR_HOST` | Never in this gate | Must be unset; an emulator cannot certify L01. |
| `GEMINI_API_KEY` | Gemini smoke/runtime | Real key with approved quota. `GOOGLE_API_KEY` may additionally be mapped into the Modal `vision-app-runtime` secret as required by the existing binding. |
| `GEMINI_MODEL` | Gemini smoke | Optional explicit model; defaults to `gemini-2.0-flash`. Record the resolved model/revision. |
| `GEMINI_MODEL_REVISION` | Evidence | Optional provider/model revision label; do not claim a revision that was not verified. |
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Modal deploy/smoke | Approved Modal CLI identity. Never include these in run payloads. |
| `VISION_APP_MODAL_RUNNER` | Modal worker | Shared runtime `module:callable`; no cloud-only alternate pipeline. |
| `R01_MODAL_APP` | RF-DETR smoke | Optional; defaults to `vision-app-creator`. |
| `R01_MODAL_RFDETR_FUNCTION` | RF-DETR smoke | Optional; defaults to `detect_frame`; deployment must expose the real frame-detection contract. |
| `R01_SAMPLE_FRAME` | RF-DETR smoke | Local path to an authorized, non-PII sample image. |
| `R01_SAMPLE_FRAME_CONTENT_TYPE` | RF-DETR smoke | Optional; defaults to `image/jpeg`. |
| `R01_DATA_RIGHTS_CONFIRMED` | Any footage/frame call | Must explicitly be `yes`; absence or any other value skips the footage test. |
| `R01_STAGING_BASE_URL` | Manual deployed journey | HTTPS origin of the approved staging frontend/API. |

## 3. Deploy Modal (operator-approved)

First validate imports without deployment, then deploy from the repository root:

```bash
uv run python -c 'from vision_app.adapters.modal.app import health; assert health()["status"] == "ok"'
uv run modal deploy backend/src/vision_app/adapters/modal/app.py
```

Record deployment/app ID, image digest, Git revision, runner path, RF-DETR checkpoint hash,
GPU class, secret names (not values), and UTC timestamp. Confirm the deployment exposes the
RF-DETR frame smoke contract named by `R01_MODAL_RFDETR_FUNCTION`; the current generic Modal
binding otherwise exposes only `health_check` and `run_gpu`, so absence of that callable is a
blocking I02/deployment issue—not grounds to fake a result.

## 4. Automated real-adapter smoke

Run:

```bash
scripts/run_r01_local.sh
```

Expected assertions:

- [ ] **Gemini compile:** the production Gemini compiler returns a typed outcome, reports Gemini
      provider/model provenance, and never selects scripted adapter mode.
- [ ] **RF-DETR on Modal:** the authorized sample frame reaches the deployed GPU detector; output
      names a non-empty model revision and every returned score/normalized box is valid. Zero
      detections is valid for a negative frame; fabricated detections are not.
- [ ] **GCS:** `GCSMediaStore` writes unique bytes, reads exactly the same bytes, and deletes the
      ephemeral object in `finally` cleanup.
- [ ] **Firestore:** an isolated document is written and read exactly, then deleted in `finally`
      cleanup.
- [ ] Capture invocation/request IDs, adapter and model revisions, cold/warm state, durations,
      retries, token/GPU usage, and billed/estimated cost. Do not capture keys, media, signed URLs,
      Authorization headers, or full prompts.

A skip is an honest **blocked gate**, not a pass. A provider permission, schema, IAM, quota, or
missing-function failure is also a gate failure and must not trigger a fake fallback.

## 5. Manual deployed end-to-end acceptance

Use only the one or two approved short videos. Perform once cold and once warm where budget allows.

1. [ ] Sign in through real Firebase Authentication; verify issuer/audience and staging origin.
2. [ ] In chat, request a supported app (for example, person crossing/counting). Confirm that
       clarification is requested when geometry is absent and that a typed app version is shown.
3. [ ] Upload through the real signed GCS flow; confirm private access, metadata, preview, and that
       another test user cannot access the source.
4. [ ] Inspect the scene, place/adjust geometry, and explicitly confirm calibration. Do not reuse
       calibration across a changed camera/view.
5. [ ] Run using real Modal/RF-DETR and Gemini where applicable. Verify persisted progress,
       coverage, source timestamps, adapter provenance, and no scripted/recorded fallback.
6. [ ] Inspect events and evidence. Check positive, negative, and unknown/insufficient-evidence
       behavior without making enforcement or certainty claims.
7. [ ] Review one finalized event and verify revision/state persistence after reload.
8. [ ] Open action preview and verify its payload. Confirm that preview sends **no** external
       request and that dispatch remains unavailable without separate opt-in.
9. [ ] Rerun/refine if needed and confirm a new immutable app version rather than mutation of the
       prior result.
10. [ ] Record actual timings, usage, cost, invocation IDs, deployment/model revisions, failures,
        skips, and cleanup status in the restricted acceptance record.

## 6. Guardrails and abort criteria

These are R01 operational ceilings, not claimed benchmarks. Before running, the operator must set
a concrete budget no looser than these defaults.

| Measure | Guardrail / action |
|---|---|
| Gemini compile | Target ≤30 s per attempt; abort after configured timeout/retry budget or any repeated schema failure. |
| Modal detector frame smoke | Warm target ≤10 s; cold target ≤120 s. Abort if cold start exceeds 5 min or an unpinned checkpoint/network download occurs. |
| GCS/Firestore smoke | Target ≤10 s each. Abort on wrong project/bucket/database, permission broadening, or cleanup failure. |
| Short-video run | Record queue/decode/inference/review separately. Abort at 15 min wall time, worker hard timeout, or stalled progress for 5 min. |
| Cost | Pre-authorize a per-session cap (recommended `$5` maximum for R01). Abort at 80% of cap. Preserve the PRD warm five-minute target of ≤`$0.50` as a measured target, not an R01 pass claim. |
| Retries/errors | Abort after configured retries, quota exhaustion, unexpected region/model revision, secret exposure, fake adapter provenance, or duplicate selected events. |

Immediately abort on suspected PII, footage outside documented rights, public object access,
cross-user access, insecure CORS/auth, unexpected external action delivery, inability to account for
spend, or inability to identify/delete created resources. Do not weaken IAM, Firestore rules,
authentication, or origin restrictions to make the smoke pass.

## 7. Data/privacy and cleanup

- Use synthetic authorized footage with **no PII**: no faces intended for identification, license
  plates, names, audio, account details, or unrelated bystanders. Facial recognition, plate
  recognition, and identity tracking are out of scope.
- Minimize clips and sampled frames. Do not paste media or provider payloads into tickets/logs.
- Set a retention deadline before upload, no later than 24 hours after this gate unless the approved
  staging policy is shorter. Provider-side retention must also be checked and recorded.
- Delete source objects, generated evidence/thumbnails, Firestore smoke documents, app/run/event
  records, provider file references, and local frame/video copies after evidence collection.
- Revoke temporary grants/test sessions and verify deletion/tombstone status. Record pending
  provider backup/soft-delete cleanup honestly; do not claim immediate irreversible erasure.
- Do not automatically delete shared deployments, buckets, databases, checkpoints, or unrelated
  resources. Cleanup is scoped to the recorded R01 resource IDs and remains operator-reviewed.

## 8. Gate decision

- **PASS:** every prerequisite and L01 assertion ran against identified real resources; no required
  test skipped; evidence includes invocation IDs, revisions, actual usage/cost, privacy cleanup, and
  no fake fallback.
- **BLOCKED:** credentials, quota, authorized footage/rights, deployed RF-DETR callable, dependency,
  or operator approval is absent. This is the expected state on an uncredentialed workstation.
- **FAIL:** a live assertion, security/privacy control, cleanup, budget, or abort criterion failed.

Local deterministic/E2E success does not change BLOCKED or FAIL to PASS. R01 remains a live human
gate until credentials and authorized footage are available and an operator signs the evidence.
