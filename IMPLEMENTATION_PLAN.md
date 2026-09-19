# Vision App Creator: Dependency-Driven Implementation Plan

**Status:** Proposed plan. All implementation tasks below are **pending**.  
**Scope:** The complete P0 in [PRD.md](PRD.md), implemented according to [DESIGN.md](DESIGN.md).  
**Purpose:** Let a coordinator assign independent, test-first work to subagents while preserving compatible interfaces, exclusive file ownership, and staged verification.

No application scaffolding, infrastructure deployment, model invocation, or product implementation is performed by creating this plan. Commands and paths below describe deliverables to establish during implementation; they are not currently runnable application commands.

## Contents

1. [Execution rules](#1-execution-rules)
2. [Verification gates](#2-verification-gates)
3. [Canonical dependency DAG](#3-canonical-dependency-dag)
4. [Parallel scheduling](#4-parallel-scheduling)
5. [Task cards](#5-task-cards)
6. [Agent assignment and handoff](#6-agent-assignment-and-handoff)
7. [Verification matrix and commands](#7-verification-matrix-and-commands)
8. [Integration, repair, and release](#8-integration-repair-and-release)
9. [Scope control and optional work](#9-scope-control-and-optional-work)
10. [Plan validation](#10-plan-validation)

---

## 1. Execution rules

### 1.1 Definition of a dependency

The table in section 3 is the **single authoritative list of direct finish-to-start dependencies**. Transitive dependencies need not be repeated.

**ID namespaces:** task IDs and PRD requirement IDs are separate. For example, task `F01` establishes contracts, while requirement `PRD:F01` is chat-based app creation. Use `task_id` and `requirement_ids` as separate handoff fields, prefix feature references with `PRD:`, and never feed the PRD feature table into the dependency scheduler.

A task is ready only when:

- Every listed dependency is complete, reviewed, and available on the integration baseline.
- Its required contract revision and fixtures are available.
- Its exclusive file scopes and required resource leases are free.
- Required external authorization is present for paid/cloud tasks.

A dependency on a **port contract** does not imply a dependency on its concrete implementation. For example, the job service can be implemented against a fake JobExecutor before the Modal adapter exists. Its component tests must be green, but the real system is not certified until integration/live gates pass.

### 1.2 Definition of done for every task

1. Implements all acceptance cases in its card and referenced design test families.
2. Follows RED → GREEN → REFACTOR for newly implemented behavior.
3. Passes targeted static, contract, component, and any task-specific integration checks.
4. Provides red/green evidence and a reproducible command/artifact manifest.
5. Has no unexpected skipped tests, empty collection, hidden fake fallback, or unreported blocker.
6. Does not edit outside its declared scope without coordinator approval.
7. Has its interface-compatible change integrated and checked on the current baseline.

“Code written,” “works with my mock,” or “tests could not run” is not done. A blocked external task remains blocked; it does not disappear from the release requirements.

### 1.3 Central ownership of shared assets

- F00 establishes package/toolchain manifests and lockfiles; later dependency changes go through the coordinator.
- F01 owns the shared contracts and generated types. Consumers do not hand-edit generated output.
- F02 owns shared test infrastructure, service lifecycle, global fixtures/plugins, and verification scripts.
- Feature agents own their module and its local tests only.
- I01 owns backend composition; U06 owns frontend composition; I02 owns Modal bindings.
- I03 and I04 own disjoint functional/security test directories.
- R01 owns actual staging deployment configuration/provisioning. Cloud changes require operator approval.

Pre-create empty parent packages and avoid shared export barrels. Two agents must not concurrently update the same global router, package manifest, `conftest.py`, generated schema file, UI theme, or deployment configuration.

### 1.4 Recommended isolation

Use one task per isolated branch/worktree when implementation begins. Each task starts from a baseline containing the exact completed dependency revisions. The coordinator serializes integration; it does not reset or overwrite active task worktrees.

If there is no Git repository, establish the agreed repository/worktree strategy during F00 when implementation is authorized. Do not assume the planning session has initialized Git. Commits/pushes and cloud side effects follow explicit user/team permissions; no force-push, destructive reset, or hook bypass is part of this plan.

---

## 2. Verification gates

| Gate | When | Required evidence | What it does not certify |
|---|---|---|---|
| **G0: foundation** | F00–F02 complete | Locked toolchain; C0 schemas/ports/generated client; test runner and network isolation work | No product workflow exists yet. |
| **G1: component** | Per implementation task, independently | Test-first local behavior, edge cases, static/contract checks, adapter integration where assigned | Other implementations or real model quality. |
| **G2: composed backend** | I01 complete | IT01–IT09 and IT13 applicable composed suites; real local persistence/media/runtime path; API parity | Cloud IAM or real Gemini/RF-DETR quality. |
| **G3: deterministic product** | I03 and I04 complete | E01–E16, adversarial/race suites IT10–IT12, no frontend route mocks | Live-provider quality, cost, or deployment feasibility. |
| **G4: deployed smoke** | R01 complete | I02 bindings deployed to approved staging; IT14 and L01; real auth/storage/model/GPU invocation | Held-out accuracy or full reliability target. |
| **G5: measured acceptance** | R02 complete | L02–L06, actual evaluation/cost/latency artifacts, frozen model/data revisions | Production safety certification. |
| **G6: release/demo** | R03 complete | G0–G5 evidence plus L07 usability and PRD go/no-go checklist | Out-of-scope live CCTV or universal detection. |

G1 is not a global barrier: a consumer may start as soon as its own dependencies pass G1. I03 can start after I01/U06 even if the independent Modal binding task is still finishing. R01 joins those tracks only when cloud deployment actually needs both.

External blockers—rights to footage, cloud credentials, available GPU, credits, human usability participants—must be reported immediately. They do not prevent unrelated local work, but they block their genuine downstream gate.

---

## 3. Canonical dependency DAG

### 3.1 Task table

`—` means no dependency. IDs, not row order, define scheduling. All listed dependencies are direct and mandatory.

| Task | Deliverable | Direct dependencies | Primary write scope / owner lane |
|---|---|---|---|
| F00 | Bootstrap and locked toolchains | — | Root manifests, minimal CI, package skeleton / foundation |
| F01 | C0 contracts, ports, schemas, generated client | F00 | `backend/src/vision_app/contracts`, `packages/contracts` / contracts |
| F02 | Test harness, profiles, verification runner | F01 | `tools/verify.py`, shared test support/config / test infrastructure |
| F03 | Deterministic fixture corpus | F02 | `fixtures/contracts`, `fixtures/synthetic`, fixture generator / fixtures |
| F04 | Authorized real dataset and held-out split | F02 | `fixtures/real`, `fixtures/heldout`, `fixtures/licenses` / data owner |
| C01 | Geometry, intervals, coordinate transforms | F02 | `backend/src/vision_app/geometry` / domain |
| C02 | Pure tracked/temporal rule interpreter | C01, F03 | `backend/src/vision_app/rules` / domain |
| C03 | Capability registry and semantic validation | C01 | `backend/src/vision_app/validation` / domain |
| P01 | Media probe, PTS decoder, window extraction | F03 | `backend/src/vision_app/media` / media |
| P02 | RF-DETR detection adapter | F03 | `backend/src/vision_app/perception/detection` / detection |
| P03 | ByteTrack tracking adapter | F03 | `backend/src/vision_app/perception/tracking` / tracking |
| P04 | Signal ROI observer and interval confirmation | F03, C01 | `backend/src/vision_app/perception/signal` / signal |
| P05 | Gemini/Pydantic AI provider adapters | F02 | `backend/src/vision_app/providers/gemini` / models |
| P06 | Semantic window reasoning and candidate review | P05, C02 | `backend/src/vision_app/reasoning` / reasoning |
| P07 | Evidence manifest, thumbnails, clips | P01, C01 | `backend/src/vision_app/evidence` / evidence |
| B01 | Firestore repository and atomic commands | F02 | `backend/src/vision_app/persistence` / persistence |
| B02 | Identity and resource authorization | F02 | `backend/src/vision_app/security/identity`, `security/authorization` / security |
| B03 | GCS/local media storage adapters | F02 | `backend/src/vision_app/storage` / storage |
| B04 | Budget ledger and redacted observability | F02 | `backend/src/vision_app/operations` / operations |
| B05 | Application/version/calibration services | C03 | `backend/src/vision_app/applications` / app lifecycle |
| B06 | Typed builder agent and revision workflow | C03, P05 | `backend/src/vision_app/builder` / builder |
| B07 | Ordered execution engine and event pipeline | C02, P01, P02, P03, P04, P06, P07, B04 | `backend/src/vision_app/runtime` / runtime integration |
| B08 | Job dispatch, attempts, leases, cancellation | B04 | `backend/src/vision_app/jobs` / jobs |
| B09 | Action eligibility, approvals, delivery outbox | B04, C03 | `backend/src/vision_app/actions` / actions |
| B10 | Deletion/tombstone/retention orchestration | F02 | `backend/src/vision_app/privacy` / privacy |
| A01 | Upload/media HTTP routes | B02, B03, P01, B10 | `backend/src/vision_app/api/media` / media API |
| A02 | Builder/app/calibration HTTP routes | B02, B05, B06 | `backend/src/vision_app/api/builder` / builder API |
| A03 | Runs/events/progress HTTP routes | B02, B08 | `backend/src/vision_app/api/runs` / run API |
| A04 | Review/action/deletion HTTP routes | B02, B09, B10 | `backend/src/vision_app/api/actions` / action API |
| U01 | Typed browser client, session, UI primitives | F02 | `apps/web/src/client`, `session`, `ui` / frontend foundation |
| U02 | Upload and source inspection UI | U01, F03 | `apps/web/src/features/upload` / upload UI |
| U03 | Chat, clarification, revision UI | U01 | `apps/web/src/features/chat` / chat UI |
| U04 | Video, geometry, calibration overlays | U01, F03 | `apps/web/src/features/video` / video UI |
| U05 | Events, evidence, review, action UI | U01 | `apps/web/src/features/results` / results UI |
| U06 | Workspace/page composition and reload | U02, U03, U04, U05 | `apps/web/src/pages`, `App.tsx` / frontend integration |
| I01 | Backend composition and local system integration | B01, B03, B05, B06, B07, B08, B09, B10, A01, A02, A03, A04 | `backend/src/vision_app/bootstrap.py`, system integration tests / backend integrator |
| I02 | Modal execution/deployment bindings | B01, B03, B07, B08, P05 | `backend/src/vision_app/adapters/modal`, `infra/modal` / cloud adapter |
| I03 | Functional browser E2E suite | I01, U06 | `e2e/functional` / product verification |
| I04 | Adversarial, privacy, concurrency verification | I01, U06 | `e2e/security`, adversarial integration tests / independent verification |
| R01 | Approved staging deployment and real smoke | I02, I03, I04 | `infra/firebase`, `infra/gcp`, `tests/live/smoke`, staging manifests / deployment owner |
| R02 | Live quality, latency, cost, regression evaluation | R01, F04 | `evals`, `tests/live/acceptance`, release freeze manifests / evaluation owner |
| R03 | Release readiness and demonstration | R02 | Release artifact manifest and checklist / coordinator + human reviewer |

### 3.2 Dependency interpretation examples

- **P02 and P03 are parallel:** both consume C0 DetectionBatch/FrameRef; P03 uses deterministic detections to test the real tracker, not P02's implementation.
- **B01 and B04 are parallel:** the budget service uses the repository port and conforming atomic fake; I01 verifies the real Firestore transaction behavior.
- **B06 and B05 are parallel:** compiler and catalog communicate through C0 ports; neither imports the other's implementation.
- **U02–U05 are parallel:** generated types and common UI/client utilities exist before feature work; each feature uses its own MSW handlers/examples.
- **A03 does not depend on B07:** route-level tests exercise JobService through a fake executor. I01 is the explicit join with the real runtime.
- **F04 does not block local development:** real footage is essential for R02, not for deterministic geometry, decoder, API, or UI TDD.
- **B07 deliberately waits for its real perception/rule components:** the engine is a true implementation join, not a second incompatible pipeline behind mocks.

---

## 4. Parallel scheduling

### 4.1 Topological levels

These are dependency layers, **not mandatory whole-wave barriers** and not elapsed-time estimates. Start a ready task immediately when its own dependencies finish.

| Level | Tasks eligible if previous dependencies are complete |
|---|---|
| 0 | F00 |
| 1 | F01 |
| 2 | F02 |
| 3 | F03, F04, C01, P05, B01, B02, B03, B04, B10, U01 |
| 4 | C02, C03, P01, P02, P03, P04, B08, U02, U03, U04, U05 |
| 5 | P06, P07, B05, B06, B09, A01, A03, U06 |
| 6 | B07, A02, A04 |
| 7 | I01, I02 |
| 8 | I03, I04 |
| 9 | R01 |
| 10 | R02 |
| 11 | R03 |

The largest displayed level contains **11 independent tasks**. This is available structural parallelism, not a recommendation to run 11 GPU jobs or a proof of the graph's maximum antichain. Actual concurrency is bounded by agents, RAM, test-service slots, credentials, and review capacity.

One longest dependency chain is:

`F00 → F01 → F02 → C01 → C02 → P06 → B07 → I01 → I03 → R01 → R02 → R03`

This is a graph-depth chain, not a measured time-critical path. Prioritize tasks with many blocked downstream consumers and genuine external-risk tasks, especially F03, C01/C03, P05, B01/B04, U01, and F04.

### 4.2 Practical worker allocation

With a limited pool, use rotating lanes rather than tying one agent to an entire subsystem forever:

- Domain/rules lane: C01 → C02; C03 can use another worker once C01 finishes.
- Media/perception lanes: P01/P02/P03/P04 concurrently when feasible, then P07/B07.
- Backend lanes: B01/B02/B03/B04/B10 independently, then their service/API consumers.
- Model/builder lane: P05, then split P06 and B06.
- Frontend lane: U01, then split U02/U03/U04/U05, then U06.
- Verification lane: fixture work and independent review early; I03/I04 later.

Do not reserve a worker waiting for a dependency. Park blocked work with its reason and assign the worker another ready task.

### 4.3 Scheduler policy

```text
ready(task) =
  task.status == pending
  AND all(dependency.status == completed for dependency in task.dependencies)
  AND task.contract_revision == approved_contract_revision
  AND required_write_scopes_are_unleased
  AND required_runtime_resources_are_available
  AND external_authorizations_are_satisfied

dispatch as many ready tasks as allowed by agent/resource limits
when a task finishes:
  review its patch, contract compatibility, and test artifacts
  integrate serially into the baseline
  rerun impacted checks on that baseline
  mark complete and unlock its dependents
```

Write-scope leases apply even with worktrees, because merging incompatible shared changes is still a conflict. Runtime leases are separate:

| Lease | Policy |
|---|---|
| Root manifests / lockfiles / C0 | One owner; coordinator-mediated changes. |
| Emulator/process slot | Unique project ID and port set per invocation; no shared destructive reset. |
| Browser slot | Unique artifacts/download/session directories; limit total browser RAM use. |
| GPU smoke | Explicit device/workspace slot and spend reservation; component tasks normally need no GPU. |
| Cloud deployment | One deployment owner per staging environment. |
| Live provider quota | Central budget/concurrency reservation, not one independent unlimited allowance per subagent. |
| Integration baseline | One integrator at a time; downstream tasks record exact dependency revisions. |

---

## 5. Task cards

### Reading the cards

- **Dependencies:** always use the canonical table, not an inferred import chain.
- **Path shorthand:** unqualified backend module scopes such as `rules/**` resolve under `backend/src/vision_app/`. Paths beginning with `backend/`, `apps/`, `packages/`, `fixtures/`, `tools/`, `infra/`, `evals/`, `tests/`, or `e2e/` are repository-root relative. All verification commands run from the repository root.
- **Owned tests:** backend task `<area>` owns `backend/tests/component/<area>/**` unless specified; frontend tests are colocated in its feature scope. Adapter integration suites are explicitly assigned.
- **Common verification:** `static --area <area>`, `component --area <area>`, and `contracts` when consuming/changing wire behavior, all through `tools/verify.py` once F02 exists.
- **Test IDs:** detailed expected behaviors are in DESIGN.md sections 13–15.
- **RED:** the first observable missing-behavior assertion to demonstrate before implementation. An import/environment error is not sufficient.

### F00 — Bootstrap and locked toolchains

**Own:** root Python/pnpm manifests and locks, workspace/package skeletons, initial CI, minimal health/test entrypoints, `tools/bootstrap.py`. Do not implement a product feature.

**Build:** establish Python 3.12 through an approved managed toolchain, a supported pinned Node/pnpm pair, Vite/React/TypeScript, backend import/test layout, lint/typecheck tools, optional vision/cloud/eval dependency groups, and an environment-only secret contract. Verify actual compatibility; do not copy unverified versions from a blog. Pre-create parent package boundaries so subsequent agents need not edit shared barrels.

**RED:** a bootstrap smoke test expects a minimal health response and frontend render. Install/configure runners first so failures are meaningful behavior failures.

**GREEN/exit:** minimal Python tests, Vitest render, typecheck, and web build succeed from locked installs. CPU test import does not load Torch or contact a cloud provider. Publish the exact bootstrap commands and toolchain versions in the handoff. F02 may then replace the minimal runner with the complete verification interface.

**External blocker:** the earlier environment exposed an Xcode-license failure through system Python. Use an available approved managed Python route or ask the operator to resolve the license; never accept licenses or change system policy on their behalf.

### F01 — C0 contracts, ports, generated types

**Own:** `backend/src/vision_app/contracts/**`, `backend/tests/contracts/**`, `packages/contracts/**`, `tools/export_contracts.py`.

**Build:** all DESIGN.md section 3 contracts, port protocols, HTTP manifest, explicit unions/statuses/error codes, capability IDs, sample payloads, structural validators, and contract hashing. Export schemas/reference OpenAPI/TypeScript from one authority. Include source generation, attempt fences, revision-based approvals, and provider provenance before splitting implementation.

**RED:** invalid mode/rule combinations, malformed coordinates/timestamps, unknown fields, and incompatible client payloads must fail. Add roundtrip/client-compile tests before filling schemas.

**GREEN/exit:** CT-CONTRACT; reference examples validate in Python/generated types; tests prove no ambiguity between CrossingBracket and TimeRange. Minimal conforming port doubles compile. Freeze C0 and give every downstream agent its version/hash. No cloud services or model execution required.

### F02 — Test harness and verification runner

**Own:** `tools/verify.py`, `tools/validate_plan.py`, `backend/tests/support/**`, shared `conftest.py`, test-profile configuration, shared `e2e/fixtures/**`, Playwright service setup, CI gate expansion. Shared manifest changes are coordinated.

**Build:** unified commands in section 7; pytest/Vitest/Playwright wrappers; local emulator/media/worker/sink profiles; seeded clock/ID doubles; scripted Pydantic AI model and detector boundary; JSON/JUnit/HTML artifacts; test namespace/port allocator; network deny-by-default; profile provenance; no-empty/no-unexpected-skip checks. Establish test configuration for future functional/security directories now so both owners can work without editing it later.

**RED:** forbidden network use, missing fixtures, missing required credentials in live mode, empty suite, and reused namespace must fail explicitly.

**GREEN/exit:** CT-HARNESS; all commands have deterministic exit behavior, document collection/profile rules, and isolate parallel workers. `validate_plan.py` recognizes only the section 3.1 task table and detects missing IDs/cycles; similarly named rows elsewhere are not tasks. G0 passes. F02 builds service launchers and conforming test doubles, not the production/local storage, executor, or outbox implementations owned by B03/B08/B09. An integration profile remains explicitly unavailable until I01 supplies those implementations; an unavailable suite cannot report green. No actual deployment or paid call is needed to complete this task.

### F03 — Deterministic fixture corpus

**Own:** `fixtures/contracts/**`, `fixtures/synthetic/**`, `tools/generate_fixtures.py`, component area `fixtures`.

**Build:** the synthetic media, crop, track, signal, provider-response, and UI fixtures in DESIGN.md section 12.3. Include all red-light truth-table cases, VFR/rotation, two simultaneous objects, gaps, signal uncertainty, semantic overlap, retries/attempt replacement, and hostile text. Manifest hashes and source timestamps are canonical; generated encoder/version details are recorded.

**RED:** a requested fixture/manifest consistency test fails before the asset exists; a VFR test must reject a fake fixture whose PTS is actually constant cadence.

**GREEN/exit:** CT-FIXTURE; regeneration and validation commands succeed; valid/invalid examples conform to C0. Assets are small, redistributable, and require no external model or footage. Publish fixture IDs so consumers do not create contradictory competing goldens.

### F04 — Authorized real dataset and held-out split

**Own:** `fixtures/real/**`, `fixtures/heldout/**`, `fixtures/licenses/**`, `tools/validate_dataset.py`; CT-DATASET tests under `backend/tests/component/dataset/**`.

**Build:** acquire operator-approved source references and rights records, label development/held-out sets by recording/camera, and freeze manifests. Include at least the PRD's 30 labeled video cases overall and 20 prompt cases overall, with an explicit held-out portion and positive/negative/unknown coverage. Traffic input must visibly include the governing signal and stop line. Mark synthetic/staged cases separately.

**RED:** validator rejects missing rights, incorrect hash, train/held-out source overlap, absent signal/lane evidence, malformed truth intervals, or insufficient required case inventory.

**GREEN/exit:** validated manifests, label-review evidence, rights approval, and split freeze available to R02. Do not expose restricted footage in the repository or manufacture permission. Missing footage is **blocked**, not a passing synthetic substitute; all other eligible local tasks continue. No model result is used as the sole ground-truth label.

### C01 — Geometry, intervals, coordinate transforms

**Own:** `geometry/**`, component area `geometry`.

**Build:** normalized points/boxes, valid polygons, finite-line crossing, oriented direction, hysteresis band, point-in-zone boundary policy, interval arithmetic, and explicit source/model/display transforms. Keep functions pure.

**RED:** a trajectory crosses the infinite extension but not the finite segment; expected result is no crossing. Add portrait/letterbox roundtrip and boundary cases before implementing utilities.

**GREEN/exit:** CT-GEOMETRY, Hypothesis invariants for scale/translation/roundtrip where applicable, all degeneracy/NaN/gap cases handled. Verify the frozen C0 coordinate examples also consumed by U04; request additional shared goldens through F03 rather than editing its scope. U04 does not wait for C01 implementation. No OpenCV model, database, or network dependency in pure geometry tests.

### C02 — Pure tracked/temporal rules

**Own:** `rules/**`, component area `rules`.

**Build:** ordered state reducer for red-phase crossing, directional counts, person-in-zone persistence, episode IDs, and shared interval/episode-merging primitives. Input/output are C0 observations/state, not SDK objects. Implement inclusive crossing brackets versus half-open confirmed coverage and DESIGN.md section 8 equality/ambiguity rules.

**RED:** a car crossing on green but still in the junction after red must not produce a supported event. Then missing signal, predicted-only track, outside-segment crossing, and jitter duplicates.

**GREEN/exit:** CT-RULES and the full synthetic truth table; property tests for no duplicate episode and no support without every hard fact. Two vehicles produce two events. Unknown gaps never bridge persistence. Branch coverage target ≥90%, with required cases mandatory regardless of percentage.

### C03 — Registry and semantic spec validation

**Own:** `validation/**`, component area `validation`.

**Build:** installed-capability registry, cross-reference validation, class/model allowlists, geometric/time compatibility, limits, unknown policies, and publication readiness. Return actionable typed validation errors/needs-calibration outcomes. Treat action permissions as references to externally approved authorization, never as proof of permission embedded in an LLM spec.

**RED:** a schema-valid semantic app requesting exact tracked counts is rejected; a red-light app missing its governing-signal binding cannot publish.

**GREEN/exit:** CT-VALIDATION; all initial capability combinations and rejection cases covered. Registry metadata supports builder explanation and model selection without executing code. Supports both the PRD example policy and independently generated valid specs, not just one golden JSON string.

### P01 — Media probe, source timestamps, decoding/windows

**Own:** `media/**`, component area `media`.

**Build:** safe metadata probe, bounded local decode, native PTS normalization, rotation, source-time sampling, small scene samples, clip/window extraction, and explicit errors. Implement exact P0 byte/duration/codec/pixel limits. No arbitrary URL input to FFmpeg.

**RED:** a VFR fixture produces incorrect times under `frame_index/fps`; test expects its actual normalized PTS. Add invalid codec/oversize/timeout and EOF tests first.

**GREEN/exit:** CT-MEDIA on real generated MP4 bytes, not solely mocked decoder calls. Correct samples/rotation/seek metadata, bounded memory and decoder lifetime, valid source hashes. Output FrameRef/transform contract usable independently by perception/evidence/UI. FFmpeg absence is an environment blocker, not a skipped required media suite.

### P02 — RF-DETR adapter

**Own:** `perception/detection/**`, component area `detection`, `fixtures/checkpoints/**` metadata only.

**Build:** lazy pinned-checkpoint load, RGB preprocessing, class/box conversion, selected threshold/low-score behavior, invocation metadata, and warm reuse. Optional GPU dependencies remain isolated from normal CPU imports.

**RED:** spy inference backend receives BGR/wrong shape or emits invalid coordinates; the adapter must detect/correct according to the contract, not silently return bad boxes. Empty detections and inference failure produce different results.

**GREEN/exit:** CT-DETECT, load-once tests, stable checkpoint/license manifest and an executable real-inference smoke path. Component tests substitute only the underlying inference backend. Actual GPU/model performance is **not** certified here and remains required at R01/R02. Never mark the real detector installed/available because a fake test passed.

### P03 — ByteTrack adapter

**Own:** `perception/tracking/**`, component area `tracking`.

**Build:** real ByteTrack integration against C0 detections, independent sessions, observed/predicted flags, class history policy, cadence handling, gap/scene reset, and explicit continuity quality.

**RED:** two independent sources must not share track IDs/state; predicted-only position cannot appear as an observation. Use canned boxes to reproduce ID continuity and a long gap.

**GREEN/exit:** CT-TRACK with the actual tracking library and deterministic detections; no dependency on RF-DETR implementation or GPU. Document/test whether cadence is resampled, validated, or causes reset. A new post-line track never gets a fabricated before-line history.

### P04 — Signal observer

**Own:** `perception/signal/**`, component area `signal`.

**Build:** conservative calibrated lamp-ROI classification, quality flags, stability timer in source time, confirmed intervals, unknown interruptions, and transition uncertainty. Keep configured thresholds explicit and changeable per calibration; no hard-coded universal traffic scene.

**RED:** glare/occlusion/tiny ROI returns unknown, not red; stability confirmation does not backdate unsupported evidence. Test red→unknown→red discontinuity.

**GREEN/exit:** CT-SIGNAL synthetic crop/interval suite, exact boundary tests, and a real-crop evaluation entrypoint for R02. Clearly identify supported signal style. If that style fails real footage, the live gate is blocked even though synthetic classifier mechanics are green.

### P05 — Gemini/Pydantic AI adapters

**Own:** `providers/gemini/**`, component area `gemini`, non-secret `fixtures/provider-compatibility/**` records.

**Build:** CompilerModel/VisualReasoner implementations, SDK/model configuration, typed scene/clip/review outputs, provider-coordinate normalization, error/retry/timeout translation, token/thinking usage, provider-file lifecycle references, and production fake-adapter prohibition. Use direct Google video SDK calls behind the port if needed; keep them out of domain code.

**RED:** malformed or out-of-window provider response must fail validation; attempted unbounded retry or missing usage produces explicit handling. A production profile cannot fall back to scripted responses.

**GREEN/exit:** CT-GEMINI with stubbed transport/scripted model, secret-redaction checks, and a small explicit live smoke command. Record model availability as unverified until R01; do not guess SDK fields or treat network failures as successful empty analysis.

### P06 — Semantic reasoning and candidate review

**Own:** `reasoning/**`, component area `reasoning`.

**Build:** bounded semantic window requests, episode merging through shared interval primitives, factual evidence references, typed review dispositions, and hard-gate preservation. Respect visual reasoner port budgets/timeouts; use unknown/partial results honestly.

**RED:** a VLM agreeing with a crossing cannot upgrade a candidate with missing signal evidence; overlapping semantic windows cannot generate duplicate incidents or bridge an unknown span.

**GREEN/exit:** CT-REASONING with scripted reasoner outputs, source-bounded interval validation, deterministic merger outcomes, and explicit required/optional review state. Adjacent real components are C02/P05 contracts/implementations; no live network needed for G1.

### P07 — Evidence artifacts

**Own:** `evidence/**`, component area `evidence`.

**Build:** thumbnail/extracted clip generation, requested/actual range manifest, truncated source-edge behavior, source playback fallback, artifact naming by attempt/source generation, and MediaStore/EventSink interactions through ports.

**RED:** an event at the beginning/end of a clip cannot claim nonexistent pre/post footage; a stale source generation cannot register an artifact after deletion.

**GREEN/exit:** CT-EVIDENCE with real generated media and a conforming media-store fake. Seek/clip timestamps match P01; extraction failure retains an honest fallback. No public object URLs or cross-source evidence linkage. Does not block on the real GCS adapter.

### B01 — Repository and transactions

**Own:** `persistence/**`, component area `persistence`, integration suite `backend/tests/integration/persistence/**`.

**Build:** Firestore and in-memory repository conformance, immutable versions, expected-revision CAS, reservation/run transaction, attempt fencing, event/updater sequencing, outbox atomic commands, deletion generations, pagination, and bounded document schemas. Large overlays remain object-store manifests.

**RED:** concurrent quota reservations cannot both consume the final available slot; stale app revision and stale worker fence must fail without partial writes.

**GREEN/exit:** CT-REPOSITORY and IT01 against an isolated real Firestore emulator. In-memory tests alone are insufficient. Exercise transaction retries and stable pagination. Do not implement authorization by trusting caller-supplied workspace IDs; ownership checks receive an authenticated principal/context.

### B02 — Identity and authorization

**Own:** `security/identity/**`, `security/authorization/**`, component area `identity`, adapter integration suite `identity`.

**Build:** Firebase verifier, principal resolution, workspace/resource authorization helpers, safe error mapping, emulator/test identity separation, and authorization conformance for all resource families through repository doubles.

**RED:** user B cannot obtain user A's evidence grant by substituting its ID; expired/wrong-audience/emulator token must be rejected under the production profile.

**GREEN/exit:** CT-IDENTITY and adapter portion of IT03. Real Auth emulator token verification works locally; fake verifier never activates from request data. Publish one authorization boundary used by all APIs. Cloud issuer/IAM are separately verified at R01.

### B03 — Media storage

**Own:** `storage/**`, component area `storage`, adapter integration suite `storage`.

**Build:** private GCS adapter and local media/upload adapter with matching semantics, scoped grants, actual object-generation/size/hash verification, safe opaque IDs, artifact writes/reads/deletes, and expiry. Keep cloud signing credentials server-side.

**RED:** a file exceeding the declared/policy size cannot become ready; a grant for one operation/resource cannot read another. Reused upload/finalize requests cannot create duplicate assets.

**GREEN/exit:** CT-STORAGE and local IT02 adapter checks; mocked GCS client calls verify signing/metadata plumbing, not IAM. Actual GCS read/upload/signing is required at R01. No remote arbitrary-URL ingestion. Do not assume unsigned metadata proves uploaded content or a signed PUT enforces the maximum size.

### B04 — Budgets and observability

**Own:** `operations/**`, component area `operations`.

**Build:** atomic budget reservation/settlement service over repository ports, job/build/frame/call/output/concurrency limits, deadlines, usage aggregation, cancellation settlement, and redacted TraceSink/Logfire bindings. Store estimated versus measured usage separately.

**RED:** two concurrent model calls cannot both reserve the last budget; raw auth/signed URL/prompt bytes cannot appear in captured traces.

**GREEN/exit:** CT-OPS with conforming atomic fake and in-memory span sink; failed/retied calls are metered correctly; telemetry failure does not interrupt analysis. I01 later runs ledger races with real Firestore. No feature agent implements an independent incompatible budget counter.

### B05 — App/version/calibration services

**Own:** `applications/**`, component area `applications`.

**Build:** create/list/read app, immutable revisions, validated proposal persistence, calibration source binding and confirmation, explicit publish, revision conflicts, and cache eligibility metadata. Services consume repository/validator ports and do not depend on HTTP/UI/model SDKs.

**RED:** modifying a draft does not mutate an already published/running version; changed source view invalidates calibration confirmation; stale base update returns conflict.

**GREEN/exit:** CT-APPLICATIONS with repository fake; both tracked and semantic apps have correct readiness states. Rerunning another clip from a confirmed same view has explicit binding; a changed view requires re-confirmation. Pure policy edits reuse observations only when perception manifest compatibility permits.

### B06 — Builder agent

**Own:** `builder/**`, component area `builder`.

**Build:** real Pydantic AI tool orchestration, inspector/registry/validator/preview service ports, BuildTurn state, clarification, bounded repair, proposed revisions, and actual progress events. Persist explicit needs-input/unsupported/failed outcomes. No implicit publication or action authorization.

**RED:** an ambiguous lane/signal produces a clarification instead of a runnable app; a prompt/video string requesting exfiltration cannot add a tool or enabled destination. Two repair attempts are the maximum.

**GREEN/exit:** CT-BUILDER using a scripted model that exercises actual tool calls/output validation, not a fake final builder result. Happy path, unsupported capability, preview, revision, conflict, and timeout cases covered. Catalog/runtime implementations are supplied only at I01; builder component work does not wait on them.

### B07 — Ordered runtime engine

**Own:** `runtime/**`, component area `runtime`.

**Build:** actual composition of decoder/detector/tracker/signal/rules/reasoning/evidence/operations components behind ports; ordered source-time loop, candidate lifecycle, bounded review queue, progress/coverage, source-end flush, and explicit partial results. EventSink/repository/JobExecutor remain injectable infrastructure boundaries.

**RED:** the full synthetic pipeline must produce one red-crossing event with correct timestamps/evidence, and no event for a pre-red entrant. Then inject delayed reviews and cancellation to prove bounded scheduling.

**GREEN/exit:** CT-RUNTIME with real adjacent logic/media/tracker and only declared model/infrastructure doubles. No per-frame cloud hop, unbounded buffer, or shared tracker. Stale fence/deletion prevents commits. Large media uses streaming bounded state. This is a real implementation join; do not finish by replacing the entire pipeline with golden events.

### B08 — Jobs and attempts

**Own:** `jobs/**`, component area `jobs`.

**Build:** durable dispatch intent, local executor implementation, attempt claim/lease/fence, heartbeat/reconciliation, cancellation, terminal-state selection, and retry policy. JobExecutor/Repository/RunEngine ports make this independently testable before B07/I02 wiring.

**RED:** dispatch succeeds but the response is lost; retry must not produce two active accepted attempts. A worker that resumes after lease replacement cannot publish results.

**GREEN/exit:** CT-JOBS with deterministic executor controls and clock. Crash points before/after submission and event writes covered. Fresh inference retries use a new attempt and replace provisional results; external delivery stays unavailable until selected finalization. No claim of exactly-once inference.

### B09 — Actions and outbox

**Own:** `actions/**`, component area `actions`.

**Build:** permission records, approved test destination references, eligibility reducer, review/version checks, signed payloads, idempotent outbox, bounded delivery retries, rate limiting, and SSRF-safe production transport. Local sink lives behind the test transport, not a production request flag.

**RED:** a preview run or an unreviewed traffic event must produce zero outbound requests; a stale review or revoked permission cannot authorize a newer event. DNS/redirect to private addresses is refused.

**GREEN/exit:** CT-ACTIONS; pure gate tests plus controlled transport/resolver tests. Network delivery is at-least-once, one durable delivery record per eligibility key, receiver dedup supported. No paid/real endpoint sends needed at G1. Include the explicit operator-approved single test destination path required by F12, not only a disabled button.

### B10 — Privacy and deletion orchestration

**Own:** `privacy/**`, component area `privacy`.

**Build:** tombstone-first deletion, source-generation invalidation, cancellation intents, media/evidence/provider cleanup graph, retention eligibility, retry/status reporting, and scope-safe cleanup. Operate through repository/media/provider-cleaner ports, allowing parallel adapter work.

**RED:** deletion during evidence extraction must prevent late registration/resurrection; deleting one asset must not delete another user's artifact or all workspace media.

**GREEN/exit:** CT-PRIVACY with delayed port doubles and injected failures. Access revocation is immediate at API level; signed-grant expiry/object removal and backup/provider cleanup are reported accurately. Idempotent retries, pending cleanup, and audit metadata tested. No real asset deletion occurs during component tests.

### A01 — Media API

**Own:** `api/media/**`, component area `api-media`; composed local upload tests under `backend/tests/integration/media-api/**`.

**Build:** media/upload/read-grant routes from C0, principal enforcement, actual bounded probe/finalize path, idempotency, error mapping, source readiness/deletion checks. Export a router factory; do not edit global backend composition.

**RED:** unauthorized/oversized upload cannot produce a ready owned source; replaying finalize must return the existing result or a defined conflict rather than duplicate storage.

**GREEN/exit:** CT-API-MEDIA plus composed local-media IT02 behavior using B03/P01. Auth supplied through B02. Every status code/body matches C0, including in-progress probe and invalid media. Required storage cleanup failure is visible, not converted to a false upload success.

### A02 — Builder/application API

**Own:** `api/builder/**`, component area `api-builder`.

**Build:** app/version retrieval, async messages/BuildTurn status, calibration confirmation, publication, and optimistic concurrency endpoints. Bind B05/B06 via injected ports/router factory. Source ownership checked before tool access.

**RED:** publishing an unconfirmed spatial app fails; concurrent stale edit returns 409; a reloaded client can fetch the same immutable version and turn status.

**GREEN/exit:** CT-API-BUILDER; idempotent message creation, unauthorized resource access, validation/clarification/repair exhaustion, and publish prerequisites covered. No route holds a large video or long GPU run in request memory. No fabricated tool progress.

### A03 — Run/event/progress API

**Own:** `api/runs/**`, component area `api-runs`.

**Build:** run creation/cancel/status, selected-attempt event pagination, updates/progress cursor, and overlay manifest access. Mandatory polling first; SSE may be added only if it does not delay correctness. Inject job/repository services.

**RED:** duplicate `POST /runs` with one idempotency key returns one durable run; a stale attempt's events cannot inflate the active timeline; cancellation replay is safe.

**GREEN/exit:** CT-API-RUNS; ownership, source readiness, calibration, quotas, pagination/reconnect, partial states, and cancellation validated. B07 is not required for route component tests; I01 binds the real runtime and verifies behavior. API responses contain source timestamps and provenance, not raw media bytes.

### A04 — Review/actions/deletion API

**Own:** `api/actions/**`, component area `api-actions`.

**Build:** review, preview, explicit permission/destination approval, dispatch, revoke, deletion initiation/status routes. User identity/approval are separate from model-generated specs. Export router factory without modifying global wiring.

**RED:** changing event ID/revision or workspace cannot apply another user's review; preview has no delivery side effect; delete reports pending cleanup rather than unverified completion.

**GREEN/exit:** CT-API-ACTIONS; stale revision, disabled/revoked destination, missing review, idempotent dispatch/delete, and inaccessible-resource cases match C0. All required F12/F13 behavior is available through API, not only internal helper functions.

### U01 — Browser client/session/UI primitives

**Own:** `apps/web/src/client/**`, `session/**`, `ui/**`; colocated tests, area `ui-client`.

**Build:** generated typed API client wrapper, Firebase session, bearer refresh, safe errors, idempotency keys, bounded polling/cursors, authenticated fetch streaming only if needed, and minimal accessible buttons/dialog/status components. Establish styling primitives that feature agents can consume unchanged.

**RED:** refreshing an expired token resumes the request without putting credentials in a URL; aborting a UI fetch does not send a server cancellation request.

**GREEN/exit:** CT-UI-CLIENT with MSW/session doubles, no `any`-typed domain DTO replacements, no provider keys in the bundle. Production session cannot be swapped by an untrusted query flag. Shared styles/client remain owned here; downstream features submit requests rather than edit them concurrently.

### U02 — Upload UI

**Own:** `apps/web/src/features/upload/**`; area `ui-upload`.

**Build:** accessible file picker, exact limit validation, progress, initiation/direct upload/finalize states, source metadata/ready callback, retry/cancel, and deletion-aware errors. Use shared client and contract fixtures.

**RED:** a successful byte upload is not displayed as ready until backend media validation completes; corrupt media exposes the right error and retry action.

**GREEN/exit:** CT-UI-UPLOAD using MSW, keyboard interaction, loading/empty/error states, and no duplicate initiation on double click. Real browser upload is verified later in E01/E02. Do not fake a ready source from the filename alone.

### U03 — Chat and revision UI

**Own:** `apps/web/src/features/chat/**`; area `ui-chat`.

**Build:** transcript, BuildTurn polling, clarification, genuine tool progress, proposed-spec summary/diff, pending confirmation, publish/revision actions, and conflict recovery. Supported prompt completion can use text confirmation; direct JSON editing is not required.

**RED:** `NeedsInput` cannot render a successful built/runnable app; stale version conflict is visible and does not overwrite the current run.

**GREEN/exit:** CT-UI-CHAT across all compiler outcomes, focus/keyboard tests, actual versus pending progress, and malicious rendered text. Model strings are rendered as data; action permission is never inferred from prose. API tests are mocked only at the declared browser component boundary.

### U04 — Video/calibration canvas

**Own:** `apps/web/src/features/video/**`; area `ui-video`.

**Build:** HTML video playback, source-time seek, normalized overlay transforms, track/signal/line/zone rendering, calibration selection and confirmation controls, unknown-transform state, responsive letterboxing. Use golden examples shared with C01 through fixtures, not a Python implementation import.

**RED:** portrait/letterboxed video overlays must align at known points; a resized canvas must not move the stop line relative to the video. Confirming stale geometry must be refused.

**GREEN/exit:** CT-UI-VIDEO golden geometry and interaction tests; unsupported transforms hide unsafe overlays; labels do not depend on color alone. DOM tests validate calculations; E15 validates real browser video layout/seeking. Optional drag correction is not required to complete the prepared chat-first flow.

### U05 — Results/evidence/review UI

**Own:** `apps/web/src/features/results/**`; area `ui-results`.

**Build:** selected-attempt event list, counters/filters, decision and human-review states, evidence playback requests, coverage/uncertainty, action preview/enable/send statuses, and deletion/expiry behavior.

**RED:** superseding a worker attempt replaces provisional events rather than counting both; no-events on partial coverage cannot display “no violations detected” as an unqualified conclusion.

**GREEN/exit:** CT-UI-RESULTS, correct source seek callback, stale review handling, no external send during preview, proper retry/error states. Evidence source/version linkage is shown. A VLM confidence value is not rendered as a certified probability that an offense occurred.

### U06 — Workspace composition/reload

**Own:** `apps/web/src/pages/**`, `App.tsx`, page-only layout styles; area `ui-workspace`.

**Build:** three-panel workspace, route/deep-link selection, feature-to-feature events, saved-app list, source/version/run coordination, refresh reconstruction, and global page error boundaries. Reuse feature interfaces; do not rewrite each component's internal state.

**RED:** after page reload, the same saved app/run/evidence is fetched and shown without in-memory transcript state. Switching draft version does not mutate the run displayed in another tab.

**GREEN/exit:** CT-UI-WORKSPACE with real feature components and MSW API, full navigation/clarification/run/refine/reload journey. Frontend build/typecheck passes. I03 later removes frontend API mocks and exercises actual backend behavior.

### I01 — Backend composition and local system integration

**Own:** `backend/src/vision_app/bootstrap.py`, `backend/tests/integration/system/**`, API-parity assertions. Do not modify another task's implementation without an explicit ownership handoff.

**Build:** actual service/repository/media/identity/builder/job/runtime/action/privacy dependency injection; local-profile ASGI app and subprocess executor; shared resource factories; router registration; final OpenAPI parity; persisted read/reload behavior. Test doubles remain only at explicitly declared paid-provider/detector boundaries.

**RED:** start with IT04/IT05 full path against the unwired composition root; it must fail on missing wiring, not missing credentials. Add job/action failure scenarios before adding reconciliation/wiring paths.

**GREEN/exit:** G2: IT01–IT09/IT13 system cases, actual emulator transactions and media bytes, ordered runtime, immutable app revisions, dry-run action behavior, source timestamp/evidence agreement. Fixes to producer modules return to the owner; integration tests must not be weakened to match a bug. Publish local run instructions through the verification runner and artifact manifest.

### I02 — Modal bindings

**Own:** `backend/src/vision_app/adapters/modal/**`, `infra/modal/**`, component area `modal`.

**Build:** Modal JobExecutor and CPU/GPU entrypoints, secret references, cached checkpoint volume, model initialization hook, per-run tracker/session isolation, concurrency/time limits, cancellation/status mapping, and image build definition. Use the same B07 runtime and B08 lifecycle, not a cloud-only divergent pipeline.

**RED:** submitted jobs must carry owned IDs/fences/manifests, not raw secret-bearing URLs; concurrent invocations must not share mutable tracker state.

**GREEN/exit:** CT-MODAL, image/config validation without deploying, injectable SDK-call tests, and a documented operator-run staging smoke invocation. Confirm packaging includes required media/vision dependencies. Cloud deployment and actual GPU invocation happen in R01, not silently during this task's ordinary tests.

### I03 — Functional E2E

**Own:** `e2e/functional/**`; functional Playwright reports under its execution namespace.

**Build/test-first:** implement E01–E11/E15/E16 using a built frontend, real local HTTP app/emulators/media/local worker, no frontend route interception. Scripted compiler/VLM and recorded detector boundary outputs are declared in the test profile; decoder/tracker/rules/evidence remain real. Include two-tab conflicts and refresh/reconnect.

**RED:** write each journey before addressing its missing product wiring; log actual first-run result. Existing passing flows are additional verification, not fabricated RED evidence. New behavior gaps return to owning feature tasks for test-first fixes.

**GREEN/exit:** all assigned E2Es pass with zero unexpected skips/retries; attach Playwright trace/screenshot/video on failure and machine-readable profile provenance. Evidence, rule change, supported/negative/unknown outcomes, and save/rerun are asserted semantically, not just by screenshots. G3 still waits for I04.

### I04 — Independent security/privacy/resilience verification

**Own:** `e2e/security/**`, `backend/tests/integration/adversarial/**`; no concurrent edits to I03 fixtures/config.

**Build/test-first:** E12–E14 and IT10–IT12 adversarial/race expansions: cross-user ID substitution across all resource routes, wrong issuer, malicious video/prompt/HTML, DNS rebinding/redirect/private endpoints, delete during extraction/review, expired grants, stale worker completion, quota races, and trace redaction.

**RED:** encode each expected security invariant, reproduce the failure if present, and assign minimal fixes to component owners. Verify tests are sensitive using fault injection at supported test boundaries, not by weakening production protections.

**GREEN/exit:** independent negative-case suite and artifact review; no media resurrection, unauthorized delivery, secret leak, or unexplained duplicate selected event. Unique emulator/bucket namespaces avoid interfering with I03. G3 passes only with both I03/I04 and impacted component regressions green.

### R01 — Approved staging deployment and live smoke

**Own:** `infra/firebase/**`, `infra/gcp/**`, `tests/live/smoke/**`, non-secret `fixtures/staging/**` readiness manifests; deployment artifact namespace. I02 remains owner of Modal code changes. R02 owns the separate `tests/live/acceptance/**` scope.

**Build:** deploy approved real resources/service identities, private storage, database/index/rule configuration, frontend origin, Modal CPU/GPU, model checkpoint cache, and managed secrets. Fail closed on missing config; never relax IAM/security to work around errors.

**RED/GREEN:** infrastructure/readiness assertions first; then validate IT14/L01 using small authorized synthetic fixtures through actual GCS/Firebase/Gemini/RF-DETR/Modal. Check real upload signing, auth audience, origin, cloud invocation, provider schema, and cold/warm state separately. Provisioning failures are external failures, not TDD product RED.

**Exit:** G4 with actual invocation IDs, revision provenance, billed usage, and no fake fallback. Operator approval for cloud changes/paid calls is mandatory; no secret values in artifacts. External webhook delivery remains off unless separately approved. Rollback plan and cleanup scope are recorded without destructive automatic cleanup of unrelated resources.

### R02 — Live evaluations and performance/cost

**Own:** `evals/**`, `tests/live/acceptance/**`, `fixtures/releases/**`, component area `evaluation`; frozen evaluation artifacts. R01 retains `tests/live/smoke/**`; F04 data owner approves changes to protected data/labels.

**Build/test-first:** implement CT-EVAL matching/denominator/report tests against hand-computable synthetic cases before running any model; then Pydantic Evals tasks and actual staging journeys L02–L06. Freeze model/threshold/prompt/preprocessing versions and split manifests.

**RED:** evaluator must penalize duplicate events, missed positives including abstentions, wrong source intervals, and source-group leakage. A report with missing/failed/skipped required live cases must fail the gate.

**GREEN/exit:** G5 with prompt validity/fidelity, traffic precision/recall/confusion/abstention, real versus synthetic split, latency/cold-start/throughput, actual retries/token/GPU usage, warm five-minute cost, concurrency/cancellation, and deployed browser results. Compare Gemini-only and hybrid baselines where affordable under approval. Missed targets produce explicit corrective tasks and new frozen reruns; never silently narrow the evaluation set. Required live-test absence blocks completion.

### R03 — Release readiness and demo

**Own:** release artifact manifest/checklist and demonstration coordination; no unreviewed product code changes.

**Verify:** all PRD F01–F14 mapped to current passing artifacts, G0–G5 satisfied, L07 human usability measured, authorized data and external-action permissions recorded, no critical unresolved security/correctness issues. Walk through prompt→confirm→run→evidence→refine→save/rerun and the second/semantic app paths.

**Exit:** G6: final reproducible demo configuration, exact model/contract/source/spec revisions, usage/evaluation summary, known limitations, clearly labeled cached/synthetic fallback, and operator sign-off. The four-of-five usability target is a real human gate; agents must not invent participants/results. No automatic claim of legal-grade traffic enforcement, live CCTV, or universal vision support.

---

## 6. Agent assignment and handoff

### 6.1 Assignment template

Use one task card per writing agent; attach relevant design sections rather than asking it to infer the architecture from the entire repository.

```text
Task: <ID and title>
Goal: <observable deliverable from task card>
Baseline: <integration revision>
Contract: C0 <hash/revision>
Dependencies: <IDs and integrated revisions>
Allowed write paths: <exact module, tests, fixtures, artifacts>
Read-only dependencies: <ports and adjacent modules>
Required behavior/tests: <CT/IT/E/L IDs and first RED>
Verification: <exact runner commands and required gate>
Profile/resources: <namespace, ports, adapters, GPU/paid-call policy>
Out of scope: <explicit exclusions>

Use RED → GREEN → REFACTOR for new behavior.
Do not change contracts, manifests, global configuration, or another task's files.
Request contract/dependency changes through the coordinator.
Do not deploy, spend credits, send webhooks, or delete real data without specific approval.
Report blockers immediately; do not replace required tests with skips or golden final outputs.
Return: changed paths, implementation summary, red/green evidence, command results,
artifacts, dependency revisions, known limitations, and integration notes.
```

A read-only reviewer can inspect contracts, tests, security assumptions, and patch boundaries independently. A reviewer does not concurrently “help” by editing the writer's files.

### 6.2 Handoff manifest

Each completed task emits a machine-readable artifact, for example:

```json
{
  "task_id": "C02",
  "requirement_ids": ["PRD:F04", "PRD:F09", "PRD:F10"],
  "status": "ready_for_review",
  "baseline_revision": "<revision>",
  "contract_revision": "<C0-hash>",
  "dependency_revisions": {"C01": "<revision>", "F03": "<revision>"},
  "changed_paths": ["backend/src/vision_app/rules", "backend/tests/component/rules"],
  "red_evidence": "<artifact-path>",
  "green_commands": [
    "uv run python tools/verify.py static --area rules",
    "uv run python tools/verify.py component --area rules",
    "uv run python tools/verify.py contracts"
  ],
  "test_profile": "component",
  "external_calls": 0,
  "required_tests_skipped": 0,
  "artifacts": ["<junit-path>", "<coverage-path>"],
  "known_limitations": [],
  "blockers": []
}
```

Values above are a template, not existing test evidence. Store execution artifacts under an ignored `.artifacts/<execution-id>/<task-id>/` namespace. Never store credentials, signed media URLs, or sensitive raw prompts in handoffs.

### 6.3 Shared-file changes

If a task needs a change outside its scope:

1. Write a small change request with the failing contract/use case and downstream consumers.
2. Coordinator grants ownership to the existing owner or temporarily transfers it while the previous writer is paused.
3. Contract owner makes additive/backward-compatible change where possible and regenerates artifacts.
4. All affected consumers rebase and rerun contract/component tests.
5. Update the dependency baseline/handoff records before more work proceeds.

Do not solve a scheduling problem by duplicating DTOs, forking helper behavior, or teaching mocks a different protocol than the real adapter.

---

## 7. Verification matrix and commands

### 7.1 Runner contract

F02 must implement these commands and area/suite mappings. Normal invocations use locked environments; installing dependencies is a separate explicit bootstrap operation.

| Command | Backend/frontend tools underneath | Required behavior |
|---|---|---|
| `uv run python tools/verify.py static --area <area>` | Ruff/mypy or TypeScript/lint/build as relevant | Checks changed scope and imported contracts; nonzero failure. |
| `uv run python tools/verify.py contracts` | pytest schema/port tests + generated TS compile + drift check | Generated artifacts match authority; no silent regeneration hiding a diff. |
| `uv run python tools/verify.py component --area <area>` | pytest/Hypothesis or Vitest/Testing Library | No external network, scoped test collection, required cases present. |
| `uv run python tools/verify.py integration --suite <suite>` | pytest, Auth/Firestore emulators, local media/worker/sink | Starts isolated services, validates readiness, runs real composition, always cleans only its own test namespace. |
| `uv run python tools/verify.py e2e --suite functional --profile e2e-local-contract` | Built Vite app + Playwright + real local API | No frontend route mocks; declared provider substitutions only. |
| `uv run python tools/verify.py e2e --suite security --profile e2e-local-contract` | Playwright + adversarial corpus | Isolation/privacy/injection tests, independent artifacts. |
| `uv run python tools/verify.py live --suite <suite> --profile staging-live --allow-paid --budget-usd <approved-cap>` | Actual staged providers/GPU + Pydantic Evals/Playwright | Refuses missing authorization/assets/provenance; caps work, records real usage. |
| `uv run python tools/verify.py gate --id <G0-G6>` | Aggregates applicable suites/artifacts | Never counts missing/old-revision/skipped required evidence as passing. |
| `uv run python tools/validate_plan.py` | Markdown task-table parser + topological validator | IDs/dependencies unique/existing, no cycle, no orphan required task, all P0 tasks reach R03. |

For G1 the runner accepts `--task <ID>` to verify one task's area and assigned suites. Full G1 aggregation can be used before G2 but is not a scheduling barrier. G4–G6 commands require the corresponding external approvals/artifacts; they must not deploy or spend silently.

### 7.2 Area mapping

| Task(s) | Component area(s) | Additional checks |
|---|---|---|
| F01 | contracts | Generated client/schema parity |
| F02 | harness | Plan/profile/isolation validation |
| F03, F04 | fixtures, dataset | Hash/PTS/rights/split validation |
| C01, C02, C03 | geometry, rules, validation | Property tests, truth table |
| P01–P07 | media, detection, tracking, signal, gemini, reasoning, evidence | Actual generated media/tracker mechanics; live model separately gated |
| B01–B10 | persistence, identity, storage, operations, applications, builder, runtime, jobs, actions, privacy | Adapter emulator suites where assigned |
| A01–A04 | api-media, api-builder, api-runs, api-actions | HTTP contract/security/error parity |
| U01–U06 | ui-client, ui-upload, ui-chat, ui-video, ui-results, ui-workspace | Vitest, accessibility, frontend build |
| I01 | system integration | `integration --suite system`, `contracts` |
| I02 | modal | Image/config/lifecycle tests; real GPU at R01 |
| I03 | functional E2E | E01–E11, E15–E16 |
| I04 | adversarial integration/security E2E | IT10–IT12, E12–E14 |
| R01 | staged smoke | IT14, L01 |
| R02 | evaluation + live suites | CT-EVAL, L02–L06 |
| R03 | release artifact gate | L07, PRD go/no-go checklist |

### 7.3 Staged verification ownership

- **Producer component tests:** written by the producer before implementation; they prove behavior at a port boundary.
- **Consumer contract tests:** use C0 payloads/protocols; they cannot alter fake behavior to excuse producer incompatibility.
- **Adapter integration tests:** B01/B02/B03 and A01 prove local infrastructure mechanics early.
- **System integration:** I01 proves real modules compose; no blanket fake runtime or golden final event stream.
- **Independent adversarial tests:** I04 adds tests outside the implementation owner's assumptions.
- **Browser E2E:** I03/I04 validate complete user flows without frontend API mocks.
- **Live evaluation:** R01/R02 replace the remaining model/GPU/cloud substitutions and measure actual feasibility/quality.

### 7.4 Failure artifacts

Every failing run captures:

- command, exit status, baseline/dependency/contract revisions;
- test case IDs, fixture IDs/hashes, profile and actual adapter provenance;
- assertion/stack trace with secrets redacted;
- source timestamps, selected attempt, rule facts, and relevant small approved evidence refs;
- Playwright trace/screenshot for browser failures;
- emulator/worker lifecycle logs and usage reservations where relevant.

Do not upload private source footage or full model prompts automatically with a failure report. Store references under the test workspace's access policy.

---

## 8. Integration, repair, and release

### 8.1 Merge/integration protocol

1. Check task's write scopes and dependency revisions.
2. Review RED/GREEN evidence and required test collection; reject skipped blockers or untested claims.
3. Check schema/port compatibility and generated artifact drift.
4. Integrate serially on the current baseline.
5. Run task component tests, impacted consumer tests, and contract checks on that baseline.
6. Record integrated revision; only now mark completed and unlock dependents.

A component green on an obsolete baseline is not sufficient. Avoid merging multiple large unverified tasks together and then assigning one agent an undefined “fix everything” task.

### 8.2 Repair tasks

If integration or live tests find a bug:

- Keep the failed gate in progress/blocked and publish the failing test/artifact.
- Create an explicit `FIX-<owner-task>-<n>` child work item with affected scope, baseline, expected behavior, first RED, and regression commands.
- Depend on the relevant completed producer baseline and failure artifact; do not introduce a circular requirement that a fix waits for the failing gate to pass.
- Give the module owner the write lease, or explicitly transfer it.
- Revalidate the repaired component, affected consumers, and failed gate on a new revision.
- Invalidate stale acceptance artifacts when models/contracts/thresholds/perception/policy change.

No agent may “fix” a failing test by reducing required cases, removing an unknown-state guard, widening action privileges, accepting stale events, or replacing real inference with a hidden fixture.

### 8.3 CI policy

- Default CI: locked static/contract/component tests, deterministic fixture validation; no provider keys required.
- Main integration CI: emulator-backed system/security suites and built-browser E2E.
- Explicit staged workflow: live smoke/evaluation with approved scoped credentials, dataset, budget, and environment.
- Required suites fail on empty collection, unexpected skip, contract drift, or profile mismatch.
- Intentional exclusion of live tests from local CI is declared by profile; it is not counted as live acceptance.
- Preserve useful artifacts; a flaky retry never erases the first failure.

F00/F02 own CI setup. Later tasks request CI changes through the coordinator instead of editing global workflows concurrently.

### 8.4 Release evidence manifest

R03 requires:

- Contract and generated client hashes.
- Package lock/container/checkpoint revisions and model IDs returned by providers.
- Source-data rights and development/held-out split manifests.
- App/calibration/version/run/attempt provenance for demo results.
- Current G0–G5 reports and L07 usability observations.
- Precision/recall/abstention/coverage denominators, actual latency/cost including retries.
- Auth/privacy/action permission checks and pending deletion/retention limitations.
- Explicit known limitations and labeled fallback behavior.

No model/API/quality claim is considered verified merely because it appears in the original research PRD.

---

## 9. Scope control and optional work

All 42 tasks are part of the P0 delivery/verification graph. Their sizes differ; they are units of ownership, not equal-size tickets or duration estimates.

Keep these outside the graph until G3 and the core live feasibility are secure:

| Optional task | Earliest safe dependency | Additional gate |
|---|---|---|
| Jev semantic routing experiment | R02 | Access plus same-observation routing eval; cannot replace vision or deterministic temporal rules. |
| Gemma/Qwen on Modal | R02 | Memory, quality, cost, latency, license/checkpoint validation. |
| Live webcam/WebRTC | R02 | Ordered timestamp/coverage, reconnect, consent, browser real-time E2E. |
| RTSP gateway | R03 | Network/security/clock/reconnect/edge deployment design; separate scope. |
| Slack/Teams native connector | B09, G3 | Explicit destination approval, token/redaction, delivery idempotency integration. |
| Full annotated-video export | P07, U06, G3 | Codec/overlay timestamp, artifact access/retention, browser playback tests. |
| Agentic long-video mode | P05, P06, R02 | Coverage/recall/cost comparison; no exhaustive-detection claim. |

Cut optional features before weakening P0 evidence, uncertainty, red-light timing, access control, chat-driven revision, or real evaluation. If a required capability is infeasible, report it as blocked/incomplete and obtain an explicit scope decision; do not silently relabel a simpler demo as the requested complete app.

---

## 10. Plan validation

### 10.1 Checks performed when authoring this plan

The 42-task dependency map was topologically checked using an inline Node program:

- 42 unique task IDs.
- All direct dependency IDs exist.
- No dependency cycle.
- Every required task is an ancestor of final release task R03.
- The dependency levels and sample longest chain in section 4 were generated from that map.

The persisted table was reviewed against the task cards, write scopes, and PRD F01–F14 traceability. This is validation of the **plan**, not execution of application tests. F02 must implement the repository-readable validator so future edits cannot silently introduce invalid dependencies.

### 10.2 Coordinator pre-dispatch checklist

- [ ] C0 and shared test infrastructure exist and are green before opening broad parallel work.
- [ ] All task-table dependencies are integrated, not merely “in review.”
- [ ] Task owner has exact allowed paths and test IDs.
- [ ] Shared manifests/contracts/configuration are not concurrently leased.
- [ ] Ports/fakes used by the task have contract coverage.
- [ ] Test resources have isolated namespaces/ports.
- [ ] Cloud calls, deployments, webhook sends, and real-data cleanup are separately approved.
- [ ] Required RED and GREEN commands are understood.
- [ ] Downstream integration gate and artifact handoff are specified.
- [ ] Blocked work stays visible while unrelated ready work proceeds.

**Implementation strategy:** a short contracts-and-harness foundation, broad independent component TDD, explicit frontend/backend/cloud joins, deterministic E2E/security verification, then real-provider acceptance. This maximizes useful parallelism without hiding integration risk behind mocks.
