# Vision App Creator: Technical Design

**Status:** Implementation-ready proposal; no application code has been implemented.  
**Product authority:** [PRD.md](PRD.md), particularly requirements F01–F14.  
**Execution authority:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), including the task dependency table and ownership rules.

This design makes the PRD concrete enough for independent agents to implement compatible components. It does not expand P0 to live CCTV, arbitrary code generation, Jev, or self-hosted VLMs. Provider names and model choices inherit the research and limitations in the PRD; availability must still pass a real smoke test.

## Contents

1. [Decisions and invariants](#1-decisions-and-invariants)
2. [Boundaries and repository structure](#2-boundaries-and-repository-structure)
3. [Contracts and coordinates](#3-contracts-and-coordinates)
4. [Persistence and consistency](#4-persistence-and-consistency)
5. [APIs and workflows](#5-apis-and-workflows)
6. [Compiler and application language](#6-compiler-and-application-language)
7. [Video and perception](#7-video-and-perception)
8. [Rules and semantic reasoning](#8-rules-and-semantic-reasoning)
9. [Jobs, evidence, and actions](#9-jobs-evidence-and-actions)
10. [Frontend design](#10-frontend-design)
11. [Privacy, operations, and deployment](#11-privacy-operations-and-deployment)
12. [TDD and verification architecture](#12-tdd-and-verification-architecture)
13. [Component test specifications](#13-component-test-specifications)
14. [Integration test specifications](#14-integration-test-specifications)
15. [E2E and live acceptance specifications](#15-e2e-and-live-acceptance-specifications)
16. [Requirement traceability](#16-requirement-traceability)

---

## 1. Decisions and invariants

### 1.1 Key decisions

| ID | Decision | Consequence |
|---|---|---|
| D01 | A modular Python backend with explicit ports, not separately deployed microservices for every module | Components can be tested independently without infrastructure sprawl. |
| D02 | Pydantic models are the wire-contract source of truth | Generate JSON Schema, reference OpenAPI, and TypeScript types; never maintain handwritten competing domain types. |
| D03 | AppSpec is an allowlisted declarative language | The agent selects supported capabilities; it cannot emit runnable Python, arbitrary expressions, or action URLs. |
| D04 | Policy, calibration, source, and execution are separate immutable/bound resources | Another clip can reuse policy, but another camera cannot silently reuse geometry. |
| D05 | Real CV handles geometry; Gemini handles compilation and bounded semantics | No LLM is trusted to maintain object identity or establish authoritative timestamps. |
| D06 | A task can implement against a frozen port and a conforming fake | Real adapter dependencies are deferred to explicit composition/integration gates. |
| D07 | Polling is the mandatory progress transport; fetch-based SSE is an optional enhancement | Avoid blocking correctness on a long-lived connection. Reload/reconnect works through persisted resources. |
| D08 | One tracking stream per worker invocation; one active attempt owns state | Frames are ordered. Concurrency occurs across runs and bounded review calls. |
| D09 | Event finalization and external delivery are separated | Preview never sends externally. Traffic delivery requires a selected, finalized event and user review. |
| D10 | Deterministic local tests and live-provider acceptance are different gates | Mocked success cannot certify perception quality or cloud permissions. |
| D11 | Dependencies are added centrally and locked | Parallel agents do not compete over package manifests or lockfiles. |

### 1.2 Non-negotiable invariants

- Every executable AppSpec is structurally and semantically validated; a valid JSON object alone is insufficient.
- A saved version is immutable. A run captures the exact version, calibration revision, media hash, and model/capability revisions.
- Every time used for vision rules is a source-video timestamp, never wall-clock arrival time.
- Unknown observations never become an implicit negative or a supported alert.
- Missing signal/lane/line evidence cannot be repaired by an LLM's confidence claim.
- An observed position and a tracker-predicted position are distinguishable.
- An event belongs to one run attempt; attempt replacement cannot merge unrelated track identities.
- Only the current fenced attempt can write active results or finalize a run.
- External delivery is an explicitly permitted, idempotent outbox operation—not an LLM tool side effect.
- Authorization, quota reservation, cancellation, and deletion are enforced server-side.
- Test adapters cannot be selected in production through an HTTP request, query parameter, or untrusted environment value.
- No acceptance report omits failed, skipped, partial, or abstained cases to make results look better.

---

## 2. Boundaries and repository structure

### 2.1 Proposed stack

There are currently no dependency manifests. These are selections for the bootstrap task, not claims that the packages are already installed.

- **Python 3.12**, `uv`, FastAPI, Pydantic 2, Pydantic AI, Google GenAI SDK.
- **Vision:** PyAV/FFmpeg, NumPy/OpenCV, RF-DETR Small, Roboflow Trackers/ByteTrack, Supervision.
- **Backend tests:** pytest, pytest-asyncio, Hypothesis; HTTP transport doubles where appropriate; Ruff and mypy.
- **Frontend:** React, TypeScript, Vite; pnpm with a locked supported Node toolchain.
- **Frontend tests:** Vitest, React Testing Library, user-event, MSW; Playwright for real-browser tests.
- **Cloud:** Modal CPU/GPU workers; Firestore, GCS, Firebase Auth/Hosting; Logfire/OpenTelemetry.
- **Local integration:** Firebase Auth and Firestore emulators, a filesystem-backed media adapter, a test upload server, a local subprocess job executor, and an in-process webhook sink.

Pin actual compatible versions during F00. Prefer vetted releases at least seven days old. Core/unit tests must not import heavyweight GPU modules or initialize cloud clients at import time. Optional dependency groups isolate `vision`, `cloud`, `eval`, and test tooling.

### 2.2 Module dependency rule

```text
contracts
   ↑
geometry / rules / validation
   ↑
application services and runtime
   ↑
HTTP routes and composition root

Infrastructure adapters implement contracts/ports.
Domain modules never import FastAPI, Firestore, Modal, Firebase, React, or cloud credentials.
Frontend imports generated wire types, never Python implementation details.
```

Service modules may depend on other service **ports**, but the composition root supplies concrete implementations. This allows the compiler and job service to be implemented independently of an actual Modal executor.

### 2.3 Proposed directory structure

```text
PRD.md
DESIGN.md
IMPLEMENTATION_PLAN.md
pyproject.toml
uv.lock
package.json
pnpm-lock.yaml
pnpm-workspace.yaml
backend/
  src/vision_app/
    contracts/             models, ports, HTTP manifest, error and capability vocabulary
    geometry/
    rules/
    validation/
    media/
    perception/detection/
    perception/tracking/
    perception/signal/
    providers/gemini/
    reasoning/
    evidence/
    persistence/
    security/identity/
    security/authorization/
    storage/
    operations/
    applications/
    builder/
    runtime/
    jobs/
    actions/
    privacy/
    api/media/
    api/builder/
    api/runs/
    api/actions/
    adapters/modal/
    bootstrap.py
  tests/
    contracts/
    component/<area>/
    integration/<suite>/
    support/
apps/web/
  src/
    client/
    session/
    ui/
    features/upload/
    features/chat/
    features/video/
    features/results/
    pages/
    App.tsx
packages/contracts/        generated schemas, OpenAPI, TypeScript, contract examples
fixtures/
  contracts/
  synthetic/
  real/                    manifests and authorized references; not automatically public footage
  heldout/                 evaluator-controlled manifests
  releases/                approved model/evaluation freeze manifests
  staging/                 non-secret deployment readiness manifests
  checkpoints/             exact upstream model revision and file hashes
  provider-compatibility/  SDK/model smoke-test metadata, no payloads or credentials
  licenses/
e2e/functional/
e2e/security/
evals/
tests/live/smoke/          real cloud/provider smoke, owned by R01
tests/live/acceptance/     held-out quality and deployed journeys, owned by R02
tools/                     bootstrap, verification, contract export, fixture generation
infra/modal/
infra/firebase/
infra/gcp/
.github/workflows/
```

The plan assigns exclusive write scopes. Shared parent `__init__.py` files are pre-created or avoided through module-local imports; agents must not all edit a global export barrel. Agent-specific configuration, if later requested, belongs in `.devin/`, not compatibility directories for other tools.

---

## 3. Contracts and coordinates

### 3.1 Contract release C0

F01 publishes **C0**, a versioned contract bundle containing:

- Pydantic request/response and domain models.
- Python protocols for component boundaries.
- JSON Schema and TypeScript types.
- Reference OpenAPI derived from the HTTP contract manifest.
- Valid and invalid JSON examples for each discriminated union.
- Capability IDs and supported combinations.
- Error codes, enum states, timestamp rules, and event/progress envelopes.
- A stable content hash and a contract compatibility test suite.

C0 is a development integration contract, distinct from the product's AppSpec `schema_version`. The later assembled FastAPI application must match the reference OpenAPI on paths, methods, request bodies, success/error schemas, authentication, and nullability. Cosmetic descriptions need not byte-match.

Only the contract owner changes C0. A consumer needing a new field files a contract change request with compatibility impact and failing example; it does not invent its own field.

### 3.2 Fundamental types

| Type | Required semantics |
|---|---|
| `ResourceId` | Opaque server-generated string; never a filesystem path or cloud object key supplied by the model. |
| `SourceTimeMs` | Integer milliseconds from normalized source PTS origin; nonnegative, bounded by asset duration. |
| `UtcTimestamp` | ISO-8601 UTC for administration and audit only. |
| `TimeRange` | Half-open `[start_ms, end_ms)` for coverage/evidence; start < end. |
| `CrossingBracket` | Inclusive uncertainty bracket `[last_pre_ms, first_post_ms]`; last_pre < first_post. Not interchangeable with a coverage range. |
| `PointN` | Finite normalized `(x,y)` in `[0,1]`, origin top-left in rotation-normalized original video. |
| `BoxN` | `(x1,y1,x2,y2)` with strict positive width/height. |
| `FrameRef` | source ID, source hash, PTS, frame sequence, dimensions, transform ID; no image bytes in persistence. |
| `ObservationQuality` | Flags/reasons such as `occluded`, `tiny_roi`, `timestamp_gap`, `predicted_only`; no fabricated calibrated probability. |
| `MoneyMicrousd` | Integer accounting estimate; rates are versioned and actual usage remains separate. |
| `ModelInvocationMetadata` | provider/model/revision, prompt hash, actual usage, duration, retry count, adapter mode; no sensitive payload logging. |

Retain native rational PTS/time-base internally. Derive source milliseconds using a documented rounding rule. If rounding collapses distinct frames to the same millisecond, preserve sequence/native PTS for ordering and do not claim finer timestamp certainty than the representation supports.

### 3.3 Application contracts

- `VisionApp`: workspace, title, draft/published version pointers, revision for optimistic concurrency.
- `AppVersion`: ID, parent ID, validated AppSpec, immutable capability/model manifest, validation report, created-by/at.
- `AppSpec`: union of `TrackedRulesSpec` and `SemanticWindowsSpec`; common title/objective, evidence policy, approved action references, limits.
- `Calibration`: camera/source binding, revision, reference frame, lanes, finite lines, ROIs, governing-signal association, confirmation metadata, scene fingerprint.
- `SourceAsset`: byte/codec metadata, storage object reference, hash, state, generation, retention/deletion metadata.
- `BuildTurn`: user instruction, base version/revision, status, tool progress, clarification/proposed version, linked preview run, usage.
- `CompilerOutcome`: `NeedsInput`, `ProposedVersion`, or `UnsupportedRequest`; no free-form success that bypasses the validator.

The model proposes geometry in its native response format. The Gemini adapter converts it to `PointN` with explicit validation; no consumer assumes a provider uses `[0,1]` rather than `[0,1000]` or pixels.

### 3.4 Runtime contracts

- `DecodedFrame`: RGB image buffer plus `FrameRef`; transient, not JSON serialized into Firestore.
- `DetectionBatch`: frame reference, detections with class/box/score/model ref; empty detections are different from a failed invocation.
- `TrackObservation`: attempt-scoped track ID, observed/predicted flag, box/anchor, last observation time, continuity quality.
- `SignalObservation`: ROI, time, enum `red|amber|green|unknown`, raw quality facts.
- `SignalInterval`: state, conservative confirmed start/end, boundary uncertainty, observation gaps.
- `RuleCandidate`: rule, crossing or persistence episode, supporting fact refs, hard-gate disposition.
- `SemanticObservation`: `present|absent|uncertain`, requested window, bounded observation intervals, evidence refs, model metadata.
- `EvidenceManifest`: requested and actual source ranges, thumbnail/clip refs, clipping-at-boundary flags, availability state.
- `Event`: run/attempt/spec/calibration refs, source interval, rule, track refs, facts, evidence, machine decision, human review, revision.
- `RunProgress`: media preparation, processed intervals, requested sampling, actual coverage, review backlog, attempt, cancellation, usage.

### 3.5 Port contracts

F01 fixes signatures and DTOs for these operations; concrete implementations belong to later tasks.

| Port | Operations / obligations |
|---|---|
| `Clock`, `IdFactory` | Inject controllable time and identifiers; domain tests never sleep. |
| `IdentityVerifier` | Verify token and return `Principal`; no workspace membership inference from untrusted claims. |
| `Repository` | Owned reads; atomic commands/CAS for versions, reservations, jobs, events, deletion, and outbox. |
| `MediaStore` | Begin/finalize upload, authorized read, artifact put, delete, metadata; opaque resource refs only. |
| `VideoDecoder` | Probe, sample frames, ordered decode, extract bounded clip; errors explicit. |
| `Detector` | Detect RGB frame; validate class/box/shape; return invocation metadata. |
| `TrackerFactory` / `TrackerSession` | New independent state per attempt; update in source order; reset/close. |
| `SignalObserver` | Observe confirmed ROI without inventing absent pixels. |
| `VisualReasoner` | Scene proposal, clip classification, candidate review; typed outputs and bounded calls. |
| `CompilerModel` | Pydantic AI model boundary; scripted model implementation available for tests. |
| `SceneInspector` | Authorized metadata/frame sampling for the builder. |
| `PreviewService` | Start/read a bounded dry-run preview; no publish or delivery permission. |
| `JobExecutor` | Submit/cancel/query invocation; duplicate submission is possible and must be fenced by job state. |
| `EventSink` | Fenced event upsert, artifact association, progress and coverage commit. |
| `BudgetLedger` | Atomic reservation, settlement, release, deadline/count limits. |
| `WebhookTransport` | Approved endpoint delivery with DNS/redirect safeguards; sink double for tests. |
| `TraceSink` | Redacted spans and metrics; in-memory sink for assertions. |
| `ProviderAssetCleaner` | Delete recorded provider-side media refs; failures are retried and reported. |

All fakes must pass the same port contract tests as real adapters where meaningful. Cloud IAM, GPU correctness, and provider retention cannot be certified by fake conformance.

---

## 4. Persistence and consistency

### 4.1 Firestore layout

Use workspace-scoped collections:

```text
workspaces/{workspace}/apps/{app}
workspaces/{workspace}/versions/{version}
workspaces/{workspace}/assets/{asset}
workspaces/{workspace}/calibrations/{calibration}
workspaces/{workspace}/build_turns/{turn}
workspaces/{workspace}/runs/{run}
workspaces/{workspace}/runs/{run}/attempts/{attempt}
workspaces/{workspace}/runs/{run}/events/{event}
workspaces/{workspace}/runs/{run}/updates/{sequence}
workspaces/{workspace}/deliveries/{delivery}
workspaces/{workspace}/reservations/{reservation}
workspaces/{workspace}/deletion_jobs/{deletion}
```

Large per-frame observations and overlay chunks go into GCS with manifests, not one Firestore document per frame. Persist bounded progress updates and event revisions. Paginate events by a stable `(source_time,event_id)` key and progress by monotonically increasing sequence.

The Admin SDK bypasses client security rules; every service still checks workspace membership/ownership. Browser direct Firestore access is unnecessary for P0 and should be denied unless deliberately introduced and tested.

### 4.2 Atomic operations

Repository contract tests cover:

- Create version only if app revision/base version still matches.
- Publish only a validated version with required confirmed calibration and explicit user approval.
- Reserve quota and create queued run/dispatch intent atomically.
- Claim attempt lease and increment fencing token atomically.
- Commit event/progress only for current attempt and source generation.
- Select a successful attempt and finalize run atomically.
- Review only the current finalized event revision.
- Create one delivery record per approved event revision/destination permission.
- Mark deletion requested, revoke application access, and invalidate future job writes atomically.

Do not perform external model/GPU/network calls inside a retryable database transaction. Transactions record intent; separate executors perform side effects.

### 4.3 Attempt fencing and replay correctness

**Important refinement of the PRD:** GPU reruns can produce different detections and tracker IDs. Never deduplicate different full reruns using a bare track ID.

- Each attempt has a unique ID, monotonic fence token, heartbeat/lease, and manifest.
- Event IDs are stable within an attempt: hash of run, attempt, rule, local track, and episode.
- A worker crash that requires rerunning perception creates a new attempt and supersedes earlier provisional results. The UI replaces the active attempt's timeline rather than adding both timelines together.
- Only the selected successful attempt contributes finalized counts or externally deliverable events.
- Within an attempt, replayed writes are idempotent. Replaying sealed observation artifacts can preserve IDs; fresh inference cannot assume that property.
- Lease expiry fences old workers even if they resume after a replacement starts.
- Do not automatically replace a successfully finalized, delivered run. A user-requested rerun is a new run with separate review/delivery permissions.
- Restarted attempts reset provisional human-review eligibility; external traffic delivery is unavailable until finalization.

This avoids promising exactly-once inference while still guaranteeing no duplicate selected results or retry-driven deliveries.

---

## 5. APIs and workflows

### 5.1 HTTP conventions

- `/v1` API; Firebase ID token in `Authorization: Bearer ...`.
- Server resolves workspace membership; resource IDs never authorize access by themselves.
- `Idempotency-Key` on upload initiation, message submission, run creation, and action enable/delivery requests.
- `expected_revision` on edits/reviews; return `409` on stale writes rather than silently overwriting.
- Standard errors: `{code, message, field_errors, request_id, retryable}`; redact internals and secrets.
- `401` invalid identity; `404` for inaccessible resources to avoid enumeration; `409` stale/state conflict; `413` excessive bytes; `422` invalid/unsupported media/spec; `429` quota/rate limit.
- Async work returns `202` with a durable resource ID; lack of a browser connection never erases it.

### 5.2 Endpoint groups

| Owner group | Endpoints / behavior |
|---|---|
| Media | `POST /uploads`, `POST /uploads/{id}/complete`, `GET /assets/{id}`, `POST /assets/{id}/read-grant` |
| Builder | `POST/GET /apps`, `GET /apps/{id}`, `GET /apps/{id}/versions`, `GET /versions/{id}`, `POST /apps/{id}/messages`, `GET /build-turns/{id}`, `POST /calibrations/{id}/confirm`, `POST /apps/{id}/versions/{version}/publish` |
| Runs | `POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/events`, `GET /runs/{id}/updates`, `GET /runs/{id}/overlays`, `POST /runs/{id}/cancel`; optional `/runs/{id}/stream` |
| Actions/privacy | `POST /events/{id}/review`, `POST /events/{id}/actions/preview`, approved destination/permission create-enable-revoke routes, `POST /events/{id}/actions/dispatch`, `DELETE /assets/{id}`, `GET /deletions/{id}` |

The F01 HTTP manifest specifies full bodies, response codes, and pagination. This expands the PRD's illustrative endpoint list to cover reload, saved-app retrieval, explicit action permission, and deletion status.

### 5.3 Upload workflow

1. Authenticate; validate declared metadata; reserve upload bytes/count.
2. Issue an operation-scoped upload grant for a server-selected object key. Use an enforced content-length policy where supported; never assume a generic signed PUT automatically enforces application limits.
3. Upload directly to private storage. The local test upload adapter enforces the same contract.
4. Finalize: check actual object identity, generation, size, hash, and metadata; probe in a bounded CPU process.
5. Atomically mark `ready` only after media validation. On failure, quarantine/delete the temporary object and release reservation according to policy.

Initial exact limits: 250,000,000 bytes, 300,000 ms, MP4/H.264, up to 2,073,600 displayed pixels/frame and 60 source FPS. Reject larger/unsupported input explicitly rather than silently transforming it during P0. Rotation is supported; decoder resource limits still apply. These are implementation guardrails, not model capability limits.

### 5.4 Builder workflow

1. Persist idempotent BuildTurn capturing app revision, source, prompt, and build budget.
2. Use authorized inspector/registry tools.
3. Return a `NeedsInput` proposal when the source, intent, or geometry is unresolved.
4. Compile typed spec; structural and semantic validators run outside the model.
5. At most two repair attempts; on failure expose field errors and preserve the last valid version.
6. A preview tool can launch only a bounded, no-delivery run with its own reserved budget linked to the build budget.
7. Persist proposed immutable version; surface actual tool progress and preview evidence.
8. Publication and calibration confirmation require explicit user actions tied to a revision. A chat “yes” can authorize the pending confirmation through normal authenticated application logic, not because the model declares itself authorized.

Concurrent edits against the same base version produce an explicit conflict. The compiler cannot overwrite another user's change or change a currently running version.

### 5.5 Run workflow

1. Validate source readiness, version, capability availability, required calibration, limits, permissions, and deletion generation.
2. Atomically reserve quota and store queued run/dispatch intent.
3. Dispatcher submits a job. Submission ambiguity is harmless to results because only one fenced attempt can claim active execution.
4. Worker processes ordered source observations and emits provisional events/coverage.
5. Evidence/review jobs finish; event dispositions are updated under revision checks.
6. Select the current successful attempt; mark `completed`, `partial`, `failed`, or `cancelled` with accurate coverage.
7. User review can enable a permitted event's delivery; outbox processing is separate.

---

## 6. Compiler and application language

### 6.1 Initial language

`TrackedRulesSpec` supports:

- common-class detection + per-source tracking;
- person-in-zone with configured persistence;
- directional line crossing/counting;
- red-phase crossing tied to a confirmed governing signal;
- unique event aggregation and evidence capture.

`SemanticWindowsSpec` supports:

- bounded visible condition, optional ROI;
- labels `present|absent|uncertain`;
- window duration/stride/sample rate;
- explicit persistence and episode-merging policy;
- sampled-analysis coverage disclosure.

Only installed observer/rule/action IDs are accepted. A semantic app cannot claim exact counting or tracking. Custom objects not covered by the detector must use clearly limited semantics or be rejected.

### 6.2 Validation layers

1. **Syntax/schema:** types, discriminated unions, unknown fields, numeric bounds.
2. **References:** unique IDs, valid observer/rule/geometry bindings.
3. **Capabilities:** supported classes, models, combinations, version compatibility.
4. **Geometry/time:** valid polygons, finite lines, directions, interval policies.
5. **Safety:** required unknown behavior, no unsupported actions, no invented URLs/code.
6. **Execution budget:** duration/FPS/call limits and quota feasibility.
7. **Publication readiness:** calibration confirmation and user approval where needed.

A proposal can be structurally valid but `needs_calibration`; that is not a runnable published app. Report states explicitly so frontend/backend tests agree.

### 6.3 Tools and model boundary

Pydantic AI orchestrates one bounded builder agent. Avoid unnecessary multi-agent reasoning chains inside the product itself. Tools operate on owned IDs and return typed observations. Tool descriptions contain only capabilities actually installed.

The Gemini adapter owns SDK differences, video submission, provider-file cleanup refs, timeout/retry normalization, model IDs, coordinate conversion, and usage extraction. A direct Google SDK path for video is permitted behind the same port if Pydantic AI lacks a required API feature.

No unit test contacts Google. A scripted Pydantic AI model must exercise real tool dispatch/output validation, including malformed output and attempted forbidden tools. Live evaluations subsequently test model behavior on held-out prompts.

---

## 7. Video and perception

### 7.1 Decoder and sampling

- Probe container/codec/duration/rotation/time base before decoding.
- Normalize display orientation and preserve the original PTS origin in metadata.
- Schedule samples in source time, not every N decoded frames; VFR cannot use assumed constant FPS.
- Full-frame detector target starts at 10 FPS. Signal crop observation can use more of the decoded source cadence.
- Account for actual processed samples, unavailable frames, and gaps.
- Bound decode CPU, memory, runtime, pixels, and buffered frames; avoid loading the entire asset.
- No URL/network-capable decoder inputs from untrusted users. Decode a staged local object under a restricted execution profile.
- Clip extraction reports actual time range and keyframe/re-encode behavior; evidence must not pretend approximate seeking is exact.

### 7.2 Coordinate transformations

Maintain explicit transforms:

`rotation-normalized source → model resize/letterbox → model coordinates → source normalized → displayed video rectangle`

For a source of `(W,H)` and displayed rectangle `(left,top,width,height)`, an overlay point is `(left+xN×width, top+yN×height)`. The rectangle excludes letterbox bars. Test portrait video, CSS resizing, high-DPI canvas, crop offsets, and model letterbox removal.

Pure Python geometry and frontend geometry tests consume shared golden coordinate examples; they do not independently invent slightly different rounding rules.

### 7.3 Detection adapter

- Lazy-load pinned RF-DETR Small once per warm worker; no download at module import.
- Input is RGB with explicit dimensions; test BGR/RGB mistakes using a spy backend.
- Convert class mapping and boxes to shared types; enforce finite valid boxes and clipped coordinate behavior.
- Record threshold, checkpoint hash, preprocessing, and model manifest.
- Keep low-confidence detections needed by the chosen ByteTrack policy instead of silently pre-filtering them away.
- An empty valid detection batch is distinct from detector failure; a failure creates a coverage gap.

Adapter tests with a fake inference backend verify plumbing, not detection quality. Real checkpoint inference belongs in live/vision acceptance.

### 7.4 Tracking

- Fresh ByteTrack session per run attempt; no shared global tracker.
- Use actual elapsed source time. If the library assumes fixed cadence, the adapter must validate/resample cadence or reset across gaps; do not claim arbitrary VFR support while passing a fixed nominal FPS.
- Predicted positions carry `observed=false` and cannot independently establish crossings.
- Keep class history/eligibility stable enough to avoid one vehicle toggling categories every frame; document and test the chosen rule.
- Reset on detected scene discontinuity or unacceptable gap. Reset/new track cannot fabricate a pre-line observation.

### 7.5 Signal observer

For the supported fixed-camera signal style, use confirmed lamp ROIs and conservative color/brightness features at source resolution. Store thresholds/calibration parameters explicitly. Red/green ambiguity, excessive saturation, low resolution, flicker, or occlusion produces `unknown`.

Temporal confirmation waits for the configured stability duration. A confirmed red interval begins conservatively at confirmation time unless earlier supporting timestamps are explicitly modeled and tested; do not backdate to an unsupported guess. Unknown observations break continuous confirmed coverage.

The model can help propose lamp geometry and review crops, but cannot override a missing-visibility gate. Synthetic crop tests demonstrate classifier mechanics; real signal-crop validation is required before release.

---

## 8. Rules and semantic reasoning

### 8.1 Pure rule interpreter

Input: ordered observations, immutable rule/calibration, prior state. Output: next state plus typed candidates/events. No database, network, wall clock, or file writes.

Geometry uses:

- point/polygon membership with an explicitly chosen boundary policy;
- signed distance to an oriented line;
- intersection with the **finite** line segment;
- hysteresis bands to avoid jitter;
- minimum observed continuity and maximum gap;
- explicit approach-to-junction direction.

For P0 choose polygon boundary as inside and line dead-band as neither side. Tests fix these semantics. Bottom-center is a documented proxy, not legal bumper localization.

### 8.2 Red-phase rule

Let crossing bracket be `[a,b]`. Let a conservative continuous confirmed-red range be `[r0,r1)`, and ambiguity margin be `m`.

Support requires, at minimum:

- observed, eligible, directionally valid finite-line crossing;
- correct lane/signal calibration;
- sufficient track continuity;
- `a >= r0 + m` and `b < r1 - m`;
- no unknown/gap inside the bracket or excluded condition.

At an ongoing red phase, `r1` represents confirmed observation coverage up to the latest signal observation—not infinity. Wait for sufficient signal coverage before finalizing; bounded timeout/missing future coverage yields inconclusive. Equality and source-end behavior must have tests.

Distinguish:

- definitely crossed outside red → rejected;
- may overlap red transition or has insufficient evidence → inconclusive;
- stopped before line → no crossing event;
- first appeared beyond line → cannot prove a crossing;
- previously crossed during green but remains in the junction → not a red crossing.

### 8.3 Zone and line-count rules

Person-in-zone and directional counts reuse the same observations and geometry. Persistence is calculated in source time. A missing sample cannot count as continuous confirmed presence. One continuous episode produces one event; exit/re-entry can create another according to the explicit episode policy.

### 8.4 Semantic windows

Initial defaults: 5-second window, 2.5-second stride, 1 FPS sampling, adjustable within validated limits. These are sampling defaults, not accuracy guarantees.

The visual reasoner returns intervals bounded by the requested window and supported evidence. Merge overlapping/adjacent positive intervals under a fixed gap/persistence policy; unknown spans do not silently bridge two positive episodes. Report window-level coverage separately from frame coverage and decision coverage.

The merger must preserve short negatives/unknowns where they affect the configured policy. A semantic classifier is not allowed to emit “exact vehicle count” under a label intended only for presence.

### 8.5 Evidence review and decision state

Machine decisions: `candidate → supported|rejected|inconclusive`. A required review may keep a candidate pending, agree, or downgrade to inconclusive; it cannot turn failed hard gates into supported evidence.

Every reviewed revision is auditable. Human review is a separate enum. If evidence or the machine revision changes before finalization, stale human approval cannot authorize the changed event.

---

## 9. Jobs, evidence, and actions

### 9.1 Runtime composition

`RunEngine` accepts port instances and an immutable execution context. It:

1. Checks cancellation/deletion/fence and reserves bounded work.
2. Decodes in source order.
3. Produces detections/tracks/signal observations or semantic windows.
4. Applies pure rules.
5. Queues bounded evidence/review work, persisting provisional facts.
6. Flushes end-of-source candidates honestly.
7. Commits actual coverage and settles known usage.

The GPU loop must not block on every VLM review. A bounded queue applies backpressure; hitting review caps produces explicit partial/inconclusive output rather than unbounded spend.

### 9.2 Job lifecycle

`queued → preparing → running → completed|partial|failed|cancelled`

Separate fields track `cancel_requested`, dispatch intent, active attempt, lease, heartbeat, review backlog, and cleanup. A run with all requested semantic windows processed can be completed while still reporting sampled coverage and inconclusive events. Provider failures or omitted required windows make processing partial; do not confuse this with ordinary negative classifications.

A reconciler handles submission ambiguity, expired leases, stalled jobs, and pending cleanup. It operates only on owned nonterminal records and respects retry/count budgets.

### 9.3 Evidence

- Default evidence request: three seconds before and after event, clipped to source boundaries.
- Manifest records requested/actual ranges, truncation, source hash, event revision, and artifact state.
- Store thumbnail and extracted clip privately. A source interval link is a valid degraded fallback if extraction fails and raw source still exists.
- Artifact writes are attempt/source-generation scoped. Recheck tombstones/fence before registering an artifact; orphan artifacts are later cleaned.
- Do not allow a stale extraction job to recreate visible media after deletion.

### 9.4 Outbox

Eligibility is a pure decision over: finalized selected event revision, human-review policy, approved permission, destination status, run mode, workspace, budget, and deletion state.

Delivery records use a deterministic key over event revision, destination, and permission version. A transaction creates/claims one delivery record. Network retry may deliver more than once; the signed payload contains an event/delivery ID for receiver deduplication.

Destination validation must check resolved addresses on actual connection, not only URL syntax. Reject private/loopback/link-local/metadata destinations, mixed DNS results, redirects, unexpected schemes, credentials in URLs, and excessive payload/response sizes. Use a production allowlist for the single demo sink. Local sink exceptions exist only in the test transport and cannot be enabled through production request data.

### 9.5 Cancellation and budget

Reservations account for concurrent jobs/builds and in-flight calls. Reserve before work, settle measured usage, release unused reservation only when safe. Process cost estimates cannot guarantee a strict invoice cap, so also enforce finite frame/call/output/time/concurrency limits.

Cancellation stops new scheduling promptly, lets unavoidable in-flight work settle, suppresses delivery, persists partial coverage, and triggers cleanup. A client disconnect is not cancellation.

---

## 10. Frontend design

### 10.1 Component boundaries

| Feature | Responsibilities | Inputs/output boundaries |
|---|---|---|
| Session/client | Firebase login, refreshed token, generated API client, polling/cursors, common UI primitives | No feature-specific domain inference. |
| Upload panel | File selection, limits, progress, probe failure/retry, source readiness | Emits ready source ID; does not compile apps. |
| Chat panel | Conversation, clarification, actual tool progress, version proposal/diff, confirmation controls | Typed build turns; never fabricates backend progress. |
| Video canvas | Playback, seek, calibration overlays, tracks, signal state, geometry confirmation UI | Source geometry + display transform + source time. |
| Results panel | Counts, decision/review filters, evidence cards, review/action preview, partial coverage | Server-selected attempt/version; no double-count across retries. |
| Workspace page | Compose features and coordinate selected app/source/version/run | Owns navigation/deep-link state; does not duplicate feature internals. |

Co-locate Vitest tests with each feature. Shared generated examples and MSW handlers provide consistent API semantics before a real backend exists.

### 10.2 State management

Use small feature-local state and explicit state machines/reducers; avoid introducing a global store before it is necessary. Server resources are authoritative.

Persisted/deep-link identity: selected app, source, version, run. Transient state: draft chat text, video playback position, selection focus, upload progress. On reload, reconstruct from APIs, not an in-memory transcript.

Run and build requests use an abortable client for navigation, but aborting a browser request must not cancel a persisted server job. Explicit Stop calls the cancellation endpoint.

### 10.3 Accessibility and error behavior

- All essential actions are keyboard operable with labels and focus restoration.
- Status/decision is not communicated by color alone.
- Clarification and validation errors attach to the relevant control.
- Loading, empty, unknown, failed, partial, cancelled, and complete have distinct UI states.
- “No events” displays processing coverage; it must not imply no events occurred in skipped/unobservable footage.
- Expired media grants can be refreshed without losing timeline state.
- A source deletion tombstone revokes UI playback and removes artifact links.

---

## 11. Privacy, operations, and deployment

### 11.1 Environment profiles

| Profile | Identity/data | Model/executor | Network/side effects |
|---|---|---|---|
| `component` | In-memory doubles | Scripted/fake ports, real pure logic | No network; no cloud SDK initialization. |
| `integration-local` | Auth/Firestore emulators, local media adapter | Real composed services, local worker, scripted providers where needed | Loopback-only allowlist; no paid providers. |
| `e2e-local-contract` | Real browser + emulator-backed app | Real decoder/tracker/rules; recorded detector/model boundary outputs explicitly declared | Test sink only; validates workflow, not model accuracy. |
| `staging-live` | Dedicated real cloud test workspace/storage | Actual Gemini, RF-DETR, Modal | Explicit approved budget and fixture rights; external sends disabled unless separately approved. |
| `production` | Real identity/storage with strict ownership | Pinned real adapters | No test switches, no emulator trust, approved destinations only. |

Use the same service/runtime code in local and live profiles. Only infrastructure/provider composition differs. The application emits adapter provenance so test reports cannot relabel scripted inference as live.

### 11.2 Deletion and retention

Deletion creates a durable tombstone and increments source generation before asynchronous cleanup. It prevents new runs/grants, requests cancellation, invalidates late worker writes, and queues deletion of local/cloud/provider artifacts. Retries are idempotent.

Existing signed URLs can remain usable until expiry unless the backing object is deleted; UI/API revocation is not cryptographic URL revocation. Tests distinguish these behaviors. Report pending provider/backups/soft-delete cleanup rather than falsely claiming immediate irreversible erasure.

Retention defaults inherit the PRD. Deleting an app does not accidentally bulk-delete other workspace assets; the cleanup graph uses explicit references.

### 11.3 Observability

Trace identifiers: request, workspace pseudonymous ID, build turn, app version, run, attempt, rule, event, and delivery. Measure queue, model initialization, decode, inference, rule, review, extraction, and delivery separately.

Log only approved fields and aggregate usage. Redaction tests cover prompts, source URLs, Authorization headers, provider keys, signed query parameters, and media bytes. A tracing outage must not block the app; metering/accounting required for budget enforcement must still function independently.

### 11.4 Deployment

- Modal CPU ASGI service and background CPU orchestration; separate GPU class for detection/runtime.
- Model weights cached and pinned; no arbitrary network fetch during every frame.
- Firebase Hosting serves the built SPA; restricted CORS to the API.
- Private GCS buckets and least-privilege service identities; explicit signing/IAM verification.
- Firestore indexes/rules are versioned and tested. Do not weaken policies to get a demo green.
- Cloud smoke tests include missing-secret failures, auth issuer/audience, real signed upload/read, GPU cold/warm invocation, frontend origin, and actual provider output validation.

Deployment and paid calls are operator-approved steps, not automatic consequences of opening a subagent task.

---

## 12. TDD and verification architecture

### 12.1 TDD protocol

Every behavior-changing task follows:

1. Identify its contract and acceptance cases.
2. Write the smallest observable failing test in its owned test area.
3. Run it against unimplemented/old behavior and record the expected assertion failure.
4. Implement only enough to pass.
5. Add edge/failure/property tests and refactor while green.
6. Run component tests plus all relevant integration/contract checks.
7. Submit a handoff with test command, red/green evidence, artifact paths, limitations, and dependency revisions.

An environment/import/credential failure is not a valid RED for a product behavior. If behavior already exists and the first test passes, record it as added verification; do not manufacture a bug or claim a false RED. Never commit a broken main branch merely to demonstrate TDD. The red phase occurs inside the task's isolated branch/worktree.

### 12.2 Test layers

| Layer | Real | Substituted | Certifies |
|---|---|---|---|
| Contract | Models, generated clients/schema, port conformance | Data fixtures | Interface compatibility and invariant vocabulary. |
| Component | One module or React feature | Adjacent ports, clock/IDs, network | Local behavior and failure handling. |
| Integration-local | Multiple real services, FastAPI, emulator transactions, decoder, tracker, rules | Paid model/GPU/provider boundaries; local media emulation | Composition, persistence, auth, retries, state consistency. |
| Browser E2E-local | Built UI, HTTP server, emulator-backed app, local worker, media playback | Scripted compiler/VLM and recorded detector output when declared | Complete user journeys and UX correctness. |
| Staging-live | Actual Google/Firebase/GCS/Modal/model paths | Test sink only unless separately approved | Real integration feasibility, quality, latency, cost, permissions. |

A test must declare `profile`, adapter provenance, fixture type, and required external resources. Required suites fail on unexpected skips, empty test collection, missing assets, or fallback to a fake.

### 12.3 Fixtures

F03 creates small deterministic, rights-safe assets and matching manifests:

- Generated RGB crops, simple crossing frames, CFR and VFR MP4, rotated video, corrupt/truncated files, no-signal frames.
- Ordered detection/track/signal traces with timestamps and known event truth.
- Valid/invalid specs, clarifications, provider responses, auth principals, progress sequences.
- Browser-ready fixtures for upload, chat, overlays, events, errors, and retry-attempt replacement.

F04 separately prepares real, licensed development/held-out footage and labels. Each manifest includes hash, source/camera group, provenance, rights/redistribution, fixture type, expected intervals/uncertainty, and split. Rights are a human approval gate; agents do not fabricate them.

Freeze held-out data before evaluation. Split by source recording/camera, not adjacent frames. Do not optimize prompts against held-out labels. Synthetic mechanics tests are not counted as real-video quality evidence.

### 12.4 Reproducibility and test isolation

- Inject clocks/IDs; seed property tests and generators; assert source times.
- Default-deny outbound network; allow only explicit test services per profile.
- Each task/test worker gets unique ports, emulator project ID, workspace ID, storage prefix, and artifact directory.
- Do not use Firestore emulator global flush or delete a shared bucket while other tests run.
- No sleeps to wait for jobs; poll bounded conditions with useful diagnostics or use deterministic executor controls.
- No visual screenshot assertion is the sole correctness test; assert semantic state, geometry, events, and evidence links.
- Reruns diagnose flakes, not conceal them. A pass after an unexplained retry is not an unconditional green gate.

### 12.5 Future verification commands

F00/F02 establish a single runner. These commands **do not exist yet**; they are required deliverables of the implementation plan.

```text
uv run python tools/verify.py static --area <area>
uv run python tools/verify.py contracts
uv run python tools/verify.py component --area <area>
uv run python tools/verify.py integration --suite <suite>
uv run python tools/verify.py e2e --suite <suite> --profile e2e-local-contract
uv run python tools/verify.py live --suite <suite> --profile staging-live --allow-paid --budget-usd <approved-cap>
uv run python tools/verify.py gate --id <gate>
```

The wrapper runs pytest/Ruff/mypy or pnpm/Vitest/TypeScript/Playwright as appropriate, starts isolated local services, emits JUnit/JSON/HTML artifacts, and exits nonzero on failure. It must never silently install packages, download model weights, deploy infrastructure, or make paid calls to satisfy a test.

Paid verification additionally requires explicit operator approval, configured staging resources, and authorized fixture manifests. `--allow-paid` records intent but is not a substitute for permission. Delivery has a separate opt-in; the live default does not send webhooks.

### 12.6 Coverage expectations

- All acceptance cases in sections 13–15 must be collected and exercised at their gates.
- Target at least 90% branch coverage in pure geometry/rules and critical authorization/action/deletion state machines; report exceptions explicitly.
- Use property tests for geometry, intervals, state transitions, and event deduplication.
- Coverage percentage alone is not acceptance. Required negative tests and real-provider gates cannot be replaced by a high coverage number.
- Use deliberate fault injection at test boundaries to prove that wrong signal order, stale fences, unauthorized action, and provider fallback cause the expected test failures.

---

## 13. Component test specifications

IDs identify test families, not single superficial tests. Each family includes the listed edge cases. The implementation plan assigns one owner and a concrete `component --area` command.

| Family | Area | Required first/edge tests |
|---|---|---|
| CT-CONTRACT | contracts | Invalid discriminators/unknown fields; timestamp/coordinate bounds; JSON→Python→JSON roundtrip; generated TypeScript compile; fake-port conformance. |
| CT-HARNESS | harness | Outbound network blocked; missing fixture/zero collection fails; unique namespaces; deterministic clock/ID; live mode requires explicit permission/budget. |
| CT-FIXTURE | fixtures | Regeneration hashes stable under pinned encoder; manifest validates; actual VFR PTS differs from nominal FPS; rights/split metadata required. |
| CT-DATASET | dataset | Missing rights/hash/labels rejected; recording/camera leakage rejected; required positive/negative/unknown inventory checked; held-out manifest freeze verified. |
| CT-GEOMETRY | geometry | Known finite-line crossing succeeds; outside-segment crossing fails; reversed direction; boundary membership; degenerate polygon/line; transform roundtrip and scale invariance. |
| CT-RULES | rules | Red/green/pre-red/unknown truth table; predicted-only crossing refused; gap invalidates continuity; boundary equality; repeated observations do not duplicate episodes; zone enter/exit and two-object count. |
| CT-VALIDATION | validation | Structurally valid but unsupported spec rejected; missing calibration; unknown class; semantic exact-count request rejected; forbidden action; bounded budgets. |
| CT-MEDIA | media | CFR/VFR timestamps and rotation; corrupt codec/container; oversized media; EOF/gap; bounded sampling; decoder timeout; clip range clipping/actual seek metadata. |
| CT-DETECT | detection | RGB/channel and shape contract; class mapping; invalid boxes; low-confidence policy; empty batch vs failure; load-once; model revision mismatch. |
| CT-TRACK | tracking | Real tracker with canned boxes maintains IDs; two streams isolated; occlusion/gap resets; observed vs predicted; variable cadence policy; no crossing from new post-line track. |
| CT-SIGNAL | signal | Synthetic red/amber/green/unknown crops; tiny/occluded/glare; stability duration boundaries; no unsupported backdating; unknown breaks confirmed interval. |
| CT-GEMINI | gemini | Typed success; malformed output; bounded repair/retry; timeout/429; usage including thinking; coordinate conversion; provider assets cleanup registration; no fake fallback in production. |
| CT-REASONING | reasoning | Out-of-window evidence rejected; unknown not bridged; overlap episode merge; candidate hard gate cannot be upgraded by VLM; budget-limited review queue. |
| CT-EVIDENCE | evidence | Three-second pre/post clipping; source-start/end truncation; exact source linkage; extraction failure fallback; expired grant handling; stale generation artifact rejected. |
| CT-REPOSITORY | persistence | Immutable versions; expected-revision conflict; atomic quota/run creation; attempt CAS/fence; stable pagination; idempotent event/outbox commands. |
| CT-IDENTITY | identity | Bad/expired/wrong-audience token; cross-tenant access; inaccessible resource returns safe error; no caller-supplied workspace privilege; test verifier denied in production. |
| CT-STORAGE | storage | Byte policy and object generation; grant expiry/scope; size mismatch on finalize; path traversal; missing/deleted artifact; opaque IDs; no public access. |
| CT-OPS | operations | Concurrent reservation cannot oversubscribe; settle/retry accounting; cancellation releases only unused work; redaction; telemetry outage; finite task/model deadlines. |
| CT-APPLICATIONS | applications | Create/revise/publish; stale base conflict; source binding; changed calibration requires re-confirmation; policy-only cache reuse vs changed perception. |
| CT-BUILDER | builder | Scripted model calls actual typed tools; clarification branch; invalid-spec repair; unsupported prompt; prompt injection cannot add tools/permissions; preview bounded and no-send. |
| CT-RUNTIME | runtime | Ordered pipeline emits expected event; correct per-frame alignment; failure yields partial coverage; end-of-source flush; bounded review queue; cancellation/deletion/fence checked. |
| CT-JOBS | jobs | Persist before submit; duplicate/ambiguous submit; lease expiry/new attempt; stale worker rejected; reload independent of client connection; terminal-state rules. |
| CT-ACTIONS | actions | Dry-run has zero network; review/version/permission gate; deterministic delivery key; retry/duplicate receiver behavior; SSRF/DNS/redirect protections; revoked permission suppresses pending delivery. |
| CT-PRIVACY | privacy | Tombstone first; cancel work; graph-scoped deletion; late result suppressed; provider deletion retry; signed URL caveat; no unrelated data deletion. |
| CT-API-MEDIA | api-media | Auth and schema errors; initiation/finalize replay; malformed/oversized upload; read grant ownership; status/error mapping. |
| CT-API-BUILDER | api-builder | Async message accepted; clarification/publish prerequisites; stale revision 409; owned list/version reload; idempotent message. |
| CT-API-RUNS | api-runs | Unauthorized/source-not-ready run rejected; reservation failure; status/events/cursor; cancel idempotency; selected-attempt results only. |
| CT-API-ACTIONS | api-actions | Review stale revision; unapproved dispatch; explicit test-destination enable; deletion request/status; all routes enforce owner. |
| CT-UI-CLIENT | ui-client | Token refresh; safe error parsing; polling resume/cursor; abort vs server cancellation; request idempotency; no token-in-URL. |
| CT-UI-UPLOAD | ui-upload | File validation; progress; finalize/probe wait; actionable retry; ready source callback; cancelled/failed input. |
| CT-UI-CHAT | ui-chat | Clarification; actual tool progress; no fake completion; proposed-version diff; confirmation; conflict; keyboard/focus; unsupported request. |
| CT-UI-VIDEO | ui-video | Letterbox/rotation/resize golden geometry; timestamp seek; selected calibration revision; text-only confirm; no overlay on unknown transform. |
| CT-UI-RESULTS | ui-results | Candidate vs supported vs inconclusive; selected attempt replacement; filtering/count; seek evidence; partial/no-events text; review/action/deletion states. |
| CT-UI-WORKSPACE | ui-workspace | Upload→chat→confirm→run feature wiring; refresh reconstructs app/run; version change doesn't mutate active run; navigation cancel distinction. |
| CT-MODAL | modal | Deployment adapter config/dependency injection; model initialization once; function payload contains IDs not media secrets; cancellation mapping; no shared tracker instance. |
| CT-EVAL | evaluation | One-to-one event matching; duplicate/unmatched predictions; positives abstained count toward misses; grouped split checks; denominator/sample reporting; threshold regression detection. |

---

## 14. Integration test specifications

Integration tests exercise real adjacent modules and storage/emulators. They must identify precisely which provider boundary, if any, remains scripted.

| ID / suite | Real path and fixture | Assertions / failure injection | Owner / gate |
|---|---|---|---|
| IT01 `persistence` | Real Firestore adapter against isolated emulator | Concurrent revisions/reservations; transaction retry; pagination; attempt fence; atomic outbox | B01 / G1 |
| IT02 `storage` | Local media adapter + bounded media probe | Actual upload bytes; finalize hash/size; invalid video; expired grant; no path escape | B03, then A01 composed case / G2 |
| IT03 `identity` | Auth emulator token + real authorization + repository | Two users/workspaces; ID substitution across every resource family; emulator tokens rejected outside local profile | B02, I01 / G2 |
| IT04 `builder` | Real Pydantic AI tools + validator + catalog + repository; scripted model | Clarify→confirm→version→preview; malformed tool args; repair exhaustion; stale base | I01 / G2 |
| IT05 `tracked-run` | Real decoder, tracker, signal observer, rule interpreter, evidence, repository; recorded detector boundary | Positive, green, pre-red, unknown; source timestamp/overlay/evidence agreement | I01 / G2 |
| IT06 `semantic-run` | Real windows/merger/repository; scripted VLM | Overlap dedup; unknown gap; invalid interval; provider timeout partial; caps enforced | I01 / G2 |
| IT07 `job-recovery` | Real job service/runtime/repository, controllable local executor | Duplicate dispatch; crash before/after submit; lease stolen; old writes fenced; attempt timeline replaced | I01 / G2 |
| IT08 `cancellation` | Active runtime + delayed provider double + budget ledger | Stop new work, settle in-flight usage, suppress delivery, preserve partial coverage | I01 / G2 |
| IT09 `actions` | Real eligibility/outbox/transport safeguards + test sink | Preview zero sends; confirm/enable then one delivery record; retry signed payload; revoke between enqueue/send | I01 / G2 |
| IT10 `deletion` | Real runtime/evidence/tombstone/ledger with controllable pause barriers; provider-cleanup transport double | Delete during upload/run/review; no resurrection; stale grant refusal; cleanup retry; other user intact | I04 / G3 |
| IT11 `security` | Real HTTP composition + malicious input corpus | SSRF/DNS/redirect, video/prompt injection, HTML rendering data, invalid specs, wrong issuer, private IDs | I04 / G3 |
| IT12 `operations` | Concurrent builds/runs + real ledger/redaction | Reservation race; retry metering; trace payload redaction; queue backpressure; telemetry failure | I01, I04 / G3 |
| IT13 `api-parity` | Actual FastAPI OpenAPI + C0 generated clients | No missing route/schema/security changes; exported contract/examples compile | I01 / G2 |
| IT14 `cloud-smoke` | Real deployed Firebase/GCS/Modal/Gemini | Real IAM/signing/upload/CORS/provider output; secrets missing → safe readiness failure | R01 / G4 |

Owning adapter tasks add their integration tests alongside component TDD; I01 owns cross-module system suites, and I04 owns adversarial/race suites. They do not concurrently edit the same test directory.

---

## 15. E2E and live acceptance specifications

### 15.1 Deterministic browser E2E: mandatory G3

Use Playwright against the built UI and a real local composed backend. No frontend route mocks in this layer. Backend model/detector substitutions are declared and fixture-driven; real HTTP, persistence, decoder/tracker/rules, and browser playback remain exercised.

| ID | Journey | Required assertions |
|---|---|---|
| E01 | Sign in, upload valid MP4, inspect source | Actual upload/finalize, metadata, ready preview; no premature run. |
| E02 | Upload invalid/oversized/corrupt video | Actionable failure, no ready asset/run, reservation released, retry works. |
| E03 | Prompt→clarification→geometry confirmation→preview | Visible typed policy, actual tool progress, confirmed revision, evidence result. |
| E04 | Red-light positives/negatives/unknown | Exactly expected selected events; pre-red entrant not flagged; unknown displayed, no unsupported legal claim. |
| E05 | “Ignore motorcycles” refinement | New immutable version; event change on appropriate fixture; prior run unchanged; perception cache invalidation correct. |
| E06 | Save, reload, rerun another clip | App/version/run restored from API; new run uses saved policy; changed view requires confirmation. |
| E07 | Person-in-zone / directional count | Same builder/runtime interfaces; expected two-object count or zone episode; not a hard-coded traffic-only page. |
| E08 | Semantic obstruction app | Sampled-analysis label; merged episode; uncertainty/coverage; source-evidence seek. |
| E09 | Refresh/disconnect/reconnect while running | Server job continues; progress cursor resumes; events not duplicated; selected attempt replacement visible. |
| E10 | Stop, timeout, exhausted budget | Correct cancelled/partial states; no fake successful empty timeline; no new action scheduling. |
| E11 | Review and webhook preview/dispatch | Preview produces no sink request; current finalized event reviewed; explicit permission; signed delivery visible; retry dedup semantics. |
| E12 | Cross-user resource substitution | UI and direct API reject app/source/run/evidence/action access without leaking resource details. |
| E13 | Delete during active work | Playback revoked, status pending/completed accurately, no late event/artifact reappears, unrelated media preserved. |
| E14 | Prompt/video injection and rendered hostile content | No unauthorized tool/action, no script execution, literal evidence text rendered safely. |
| E15 | Responsive/keyboard geometry workflow | Confirm/seek/review usable by keyboard; overlays align at supported sizes; errors restore focus. |
| E16 | Stale revision/two tabs | Conflict visible; no lost update or review applied to an obsolete event version. |

I03 owns E01–E11, E15–E16. I04 owns E12–E14 and adversarial expansions. Both use isolated workspaces/artifacts and pre-established Playwright configuration.

### 15.2 Live and human acceptance: mandatory G4–G6

| ID | Test | Release evidence |
|---|---|---|
| L01 | Real provider and cloud smoke | Actual Gemini and RF-DETR model/revision, Modal invocation, Firebase identity, GCS upload/read, no scripted adapter. |
| L02 | Held-out prompt→spec evaluation | At least 20 cases overall with a held-out split; valid executable specs 100%, target ≥90% supported-intent fidelity; unsupported requests handled honestly. |
| L03 | Held-out traffic/video evaluation | At least 30 labeled cases overall across positive/negative/unknown and declared splits; precision target ≥90%, recall target ≥85%; report real/synthetic separately, sample counts and abstention. |
| L04 | Latency/throughput/cost | Cold and warm reported separately; source/queue/decode/review timings; actual usage; PRD target ≤$0.50 for a warm supported five-minute run. |
| L05 | Real multi-run isolation/cancellation | Concurrent camera-local state isolated, cancelled work bounded, selected events not duplicated, quotas respected. |
| L06 | Deployed browser journeys | E01/E03/E04/E05/E06/E08 against staging with real providers on approved fixtures; no route mocking or hidden cached inference. |
| L07 | Human usability and honest demo | Four of five test users complete a supported flow without code; positive/negative/unknown evidence demonstrated; cached/synthetic material labeled. |

The reported quality targets apply to the declared supported operating envelope and small evaluation set, not production safety certification. Missing authorized footage, provider access, or a required live test keeps G5 blocked; missing human usability evidence keeps G6 blocked. Deterministic green does not waive either requirement.

### 15.3 Evaluation details

- Freeze models, thresholds, preprocessing, prompts, and fixture split before final evaluation.
- Match events one-to-one using rule/class and a documented temporal-overlap/tolerance criterion. Store matching configuration with reports.
- Duplicate predictions are false positives; unmatched labeled positives are false negatives. Positive cases ending inconclusive remain visible in recall/coverage reporting.
- Measure source-group metrics as well as pooled results; disclose cases outside the supported envelope.
- Record attempt count, failed requests, and total cost including retries.
- Never use an LLM judge as the sole traffic ground truth.
- A failing target triggers a specific corrective task and rerun on a new frozen revision; do not rewrite labels or silently reduce the set.

---

## 16. Requirement traceability

| PRD requirement | Design ownership | Required verification |
|---|---|---|
| F01 chat creation | Compiler, contracts, builder API/UI | CT-BUILDER, IT04, E03, L02 |
| F02 upload | Storage, media, media API/upload UI | CT-MEDIA/STORAGE, IT02, E01–E02, L01 |
| F03 scene confirmation | Geometry, calibration/catalog, chat/video UI | CT-GEOMETRY/APPLICATIONS/UI-VIDEO, E03/E06/E15 |
| F04 reusable compilation | Contracts, validation, rules | CT-CONTRACT/VALIDATION/RULES, IT13, E03/E07 |
| F05 run monitoring | Runtime/jobs/run API/results | CT-RUNTIME/JOBS, IT07–IT08, E09–E10 |
| F06 evidence | Evidence/event persistence/video/results | CT-EVIDENCE, IT05–IT06, E04/E08, L03 |
| F07 chat revision | Catalog/compiler/chat | CT-APPLICATIONS/BUILDER, E05/E16, L06 |
| F08 save/rerun | Repository/catalog/workspace | IT01/IT04, E06, L06 |
| F09 red-light | Detection/tracking/signal/geometry/rules | CT-DETECT/TRACK/SIGNAL/RULES, IT05, E04, L03 |
| F10 second app | Rules/compiler/shared UI | CT-RULES/BUILDER, E07 |
| F11 semantics | Gemini/reasoning/window runtime | CT-GEMINI/REASONING, IT06, E08, L06 |
| F12 actions | Authorization/outbox/review UI | CT-ACTIONS, IT09, E11/E14 |
| F13 access/privacy | Identity/storage/privacy/all routes | CT-IDENTITY/STORAGE/PRIVACY, IT03/IT10/IT11, E12–E14 |
| F14 evaluation/traces | Operations/harness/evaluation | CT-OPS/EVAL, IT12, L01–L07 |

The design is complete only as a specification. Implementation completion is determined by the task DAG and staged evidence in IMPLEMENTATION_PLAN.md, not by the existence of these documents.
