# R02 dataset evaluation and demo quality gate

## Status and scope

R02 is a **live/human gate**. This document defines the evaluation protocol and proposed hackathon-demo targets; it does not claim that a real-footage evaluation has run or that G5 has passed. G5 remains blocked until an authorized held-out manifest, human rights approval, required live cases, and frozen live results exist.

The component baseline is deterministic and model-free. Live execution, GPU/provider use, deployment, spend, and external delivery require their separate approvals. External sends remain disabled.

## Dataset policy (mandatory)

Evaluation may use only:

1. generated deterministic synthetic fixtures;
2. footage staged by an authorized project operator; or
3. real footage whose manifest documents provenance, license/authorization, permitted evaluation use, redistribution constraints, retention, and approving human.

Do **not** download or use unlicensed public video, scrape streams, infer that public availability grants a license, or fabricate/guess rights. Missing or ambiguous rights metadata is a hard failure, not a field to fill with plausible text. Protected footage and labels remain under the F04 data owner. Reports expose only approved aggregates and non-sensitive identifiers; footage, labels, source URLs, credentials, and signed links are not copied into reports.

Synthetic footage validates evaluator and pipeline mechanics only. It must be reported separately and never represented as real-world model-quality evidence.

## Frozen evaluation unit

Before a run, freeze a manifest containing:

- manifest hash and revision; fixture type (`synthetic` or `authorized_real`);
- media hash, annotation hash, recording ID, camera/source-group ID, split, duration, and positive/negative/unknown inventory;
- documented rights record and human approval for every real item;
- exact app spec, calibration, model/checkpoint, threshold, prompt, preprocessing, provider/adapter mode, and code revisions;
- required cases and expected resource profile.

Split real data by recording and camera/source group, never by adjacent frames. No group may occur in both development and held-out sets. Freeze held-out labels before evaluation; do not tune prompts, thresholds, geometry, or preprocessing against them. Any change creates a new identified run over the complete frozen set.

## Ground truth and event matching

Each annotation has a stable ID, source-time half-open interval `[start_ms, end_ms)`, and class/rule label. Optional geometry is represented in normalized source coordinates. Unknown/unobservable intervals remain explicit and are excluded only according to a pre-frozen denominator policy; they cannot silently become negatives.

For a selected successful runtime attempt, the harness reads contract `Event` objects and compares `Event.source_range` and `Event.rule_id` with annotations:

1. compute temporal IoU for every prediction/annotation pair;
2. greedily select one-to-one pairs by descending IoU with stable input-index tie-breaking at the frozen threshold (demo: `0.50`);
3. record a same-class pair as a true positive;
4. record a different-class temporal pair in the off-diagonal confusion cell and as both one false positive and one false negative;
5. record unmatched predictions, including duplicate events, as false positives;
6. record unmatched truths, including cases where the runtime abstained/was inconclusive or coverage omitted a positive, as false negatives.

Predictions from superseded attempts are excluded. Coverage, failed/partial attempts, skipped required cases, and abstention counts are reported rather than hidden. Wrong source intervals naturally fail the IoU threshold. A required live case that is missing, failed, skipped, run with fallback/scripted provenance, or has source-group leakage fails the gate.

## Metric definitions

- **Precision@IoU** = same-class matched predictions / all predictions.
- **Recall@IoU** = same-class matched truths / all ground-truth positives. Abstentions on positives are misses.
- **False positives/hour** = unmatched or wrong-class predictions × `3,600,000 / evaluated observable duration_ms`. Report total duration and per-source denominators.
- **Confusion matrix** uses ground-truth classes as rows and predicted classes as columns, plus `__none__` for misses and unmatched predictions.
- **Per-class precision/recall** use each class's prediction/truth denominators. **Per-class accuracy** is one-vs-rest `(TP + TN) / all matrix observations`; include support so imbalance is visible.
- **Calibration quality (geometry IoU)** is intersection area / union area in normalized, rotation-corrected source coordinates. Report per geometry, median, p5, and minimum. Do not substitute display/CSS coordinates.
- **Latency** reports nearest-rank p50/p95/p99 and maximum for queue, cold start, decode, inference/model, rules/review/evidence, and end-to-end run latency. Keep cold and warm runs separate.
- **Cost/video-minute** = actual total billed micro-USD × `60,000 / processed source duration_ms`. Also report retries, token use, GPU duration, provider calls, and total billed cost. Estimates are labeled and cannot pass an actual-cost gate.

## Deterministic component baseline

`backend/tests/evaluation/test_evaluation.py` uses contract types and hand-computable cases, plus `fixtures/synthetic/annotations/red_light_violation.json`. It verifies temporal IoU, duplicate/miss/wrong-interval/abstention penalties, class confusion, geometry IoU, deterministic nearest-rank latency, and cost normalization. It invokes no model, GPU, cloud SDK, or network service. Existing generated fixtures are pinned by `fixtures/synthetic/manifest.json` hashes and seed.

Run:

```text
uv run pytest backend/tests/evaluation/test_evaluation.py
uv run python tools/verify.py component --area evaluation
uv run python tools/verify.py static
```

## Authorized held-out procedure

1. **Human authorization:** F04 data owner checks each rights record and signs the frozen manifest. Stop if any record is absent or ambiguous.
2. **Leakage check:** compare recording and camera/source-group IDs against development and calibration sets. Stop on overlap.
3. **Inventory check:** require the frozen positive, negative, unknown, class, camera, and condition inventory; preserve every denominator.
4. **Readiness:** record approved budget/operator, staging revision, disabled external sends, fixture hashes, and all frozen runtime revisions.
5. **Execute:** run every required L02–L06 case in `staging-live`; capture actual invocation IDs, adapter provenance, selected attempt, coverage, retries, usage, latency, and billing. Never replace a live failure with a fake result.
6. **Evaluate:** run the same event matcher over selected events and protected labels. Produce separate real and synthetic sections and per-source/per-class breakdowns.
7. **Gate:** fail on missing/failed/skipped cases, leakage, fake fallback, incomplete provenance/rights, target miss, or absent actual cost. Create corrective tasks and rerun a newly frozen complete evaluation; never narrow the set silently.
8. **Human review:** the dataset owner and demo/release operator review the report and explicitly sign or reject G5. Agents do not invent approval or results.

## Hackathon demo quality targets

These are predeclared minimums for the authorized-real held-out aggregate unless stated otherwise. The report must include confidence/support context; passing synthetic data alone does not satisfy them.

| Measure | Pass target |
|---|---:|
| Event precision@0.50 IoU | >= 0.80 |
| Event recall@0.50 IoU | >= 0.75 |
| False positives/hour | <= 2.0 |
| Each required class precision and recall (with nonzero held-out support) | >= 0.60 |
| Each required class one-vs-rest accuracy | >= 0.80 |
| Calibration box IoU, median / minimum | >= 0.80 / >= 0.50 |
| Warm end-to-end latency for a five-minute video, p50 / p95 | <= 5 min / <= 10 min |
| Warm cost per processed video-minute | <= USD 1.00 |
| Required live cases | 100% executed and passed; zero skips/fake fallbacks |
| Critical security/correctness failures or duplicate selected events | 0 |

Cold-start latency, throughput, concurrency/cancellation, prompt validity/fidelity, browser journey results, and Gemini-only versus hybrid comparison are mandatory report sections but are informational until an operator freezes an additional numeric target. Baseline comparison occurs only when affordable and explicitly approved.

**Pass:** every numeric target passes on the complete authorized-real held-out set, every required live case passes, provenance/rights/usage are complete, and both humans sign G5. **Fail/gated:** any target or required section fails, any required result is absent, or approval is absent. Current status remains **GATED / NOT EVALUATED ON AUTHORIZED REAL FOOTAGE**.
