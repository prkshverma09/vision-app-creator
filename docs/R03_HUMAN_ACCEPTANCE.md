# R03 Human Acceptance Checklist: Hackathon Demo Gate

This document captures the go/no-go checklist for the **Vision App Creator** hackathon demonstration.  
It is owned by task **R03** in [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) and corresponds to the **G6: release/demo** verification gate.

## Scope and status

- **What this checklist covers:** The complete demo journey a first-time human reviewer walks through before signing off that the product is safe to demonstrate.
- **What it does not cover:** Out-of-scope live CCTV, production traffic enforcement certification, enterprise governance, or real-time universal detection. See [Known limitations](#known-limitations).
- **How to use it:** Check each item during a live rehearsal. The companion React component [`DemoChecklist.tsx`](../apps/web/src/evaluation/DemoChecklist.tsx) lets the team persist progress in-browser for the event.

## Demo environment prerequisites

Before running the demo, confirm the following are available and recorded:

- [ ] Approved, rights-cleared short clip (ideally under 30 seconds) showing a visible stop line, governing signal, and at least one vehicle movement.
- [ ] A second clip from the same calibrated viewpoint for the rerun step.
- [ ] Staging environment is warmed, budget cap is set, and the approved test webhook destination is configured.
- [ ] Fallback plan is documented if a live provider call fails (clearly labeled cached/replay result with exact model/spec/source revisions).
- [ ] At least one independent human reviewer who has not written the code is present for the 4-of-5 usability observation.

## Core demo acceptance checklist

### 1. Create a red-light violation app via chat (< 5 minutes)

- [ ] A new user lands on the workspace without writing code.
- [ ] The user types an objective such as "Flag vehicles that cross the stop line while the traffic light is red."
- [ ] The builder agent responds with a typed, plain-language interpretation and either a proposed app version or a focused clarification request.
- [ ] Unsupported or ambiguous prompts are refused or clarified, not silently accepted.
- [ ] Within 5 minutes a validated `AppSpec` is visible in the app panel with title, objective, capability, and evidence policy.

### 2. Upload media and inspect source metadata

- [ ] The user uploads a supported short MP4 (H.264/AAC, under 5 minutes and 250 MB).
- [ ] Source metadata is displayed: duration, dimensions, codec/container hints, hash/state, and any probe warnings.
- [ ] Invalid media (wrong container, corrupt file, unsupported codec, or oversized) is rejected with an actionable message before analysis starts.
- [ ] A thumbnail/preview frame loads and is clearly labeled as the reference frame for calibration.

### 3. Calibrate stop line and signal

- [ ] The agent proposes a stop line and governing signal region on the video canvas.
- [ ] The user can see the proposal overlaid on the reference frame and edit or confirm it.
- [ ] Calibration warnings are shown for ambiguous geometry (e.g., line near edge, tiny signal ROI, missing lane association) before confirmation.
- [ ] Confirmed calibration is saved with a revision; changing the camera/source requires a new confirmation.

### 4. Run analysis and view events

- [ ] The user starts a run and sees an explicit run/job status with progress updates (preparation, processed interval, coverage).
- [ ] Event cards appear with source timestamp, rule ID, thumbnail, machine decision, and review status.
- [ ] Selecting a card shows a playable evidence interval and before/at/after frames/crops where available.
- [ ] Positive, negative, and unknown/abstention cases are all visible or explainable in the results.
- [ ] Analysis can be cancelled and does not disappear on reload.

### 5. Review, approve, and reject events

- [ ] Each event card exposes controls to confirm, dismiss, or leave unreviewed.
- [ ] Approved or rejected events update visibly and are reflected in counters/filters.
- [ ] Bulk review or filtering by decision/review status is available.
- [ ] A dry-run action preview shows what would be delivered without actually sending unless opt-in is confirmed.

### 6. Refine the app via chat and rerun

- [ ] The user sends a follow-up such as "ignore motorcycles" or "also require the rear axle to cross the line."
- [ ] A new app version is created; a version diff or changelog is visible.
- [ ] Re-running the same clip shows a changed result consistent with the refinement.
- [ ] The saved app can process a second clip from the calibrated view without rebuilding from scratch.

## Error and edge-case handling

- [ ] **Unsupported requests:** Off-scope prompts (e.g., facial recognition, license-plate reading, automatic fines) are refused with a clear reason.
- [ ] **Invalid media:** Corrupt, unsupported, or oversized uploads show a human-readable validation message, not a generic error.
- [ ] **Calibration warnings:** Low-confidence or ambiguous stop-line/signal geometry surfaces a warning before confirmation; no alert is generated from unconfirmed geometry.
- [ ] **Budget and limit messages:** Run creation is blocked or gracefully degraded when per-run caps, per-workspace concurrency, or spend limits would be exceeded. The UI shows remaining allowance when relevant.
- [ ] **Provider/retry errors:** A failed provider call or GPU cold start is reported with adapter provenance and an explicit retry/cancel path.

## Accessibility basics

- [ ] All interactive controls in the demo flow are reachable via keyboard (Tab order, Enter/Space activation, visible focus).
- [ ] Checkboxes, buttons, and form fields have descriptive labels or `aria-label` text that a screen reader can announce.
- [ ] Decision badges and status indicators do not rely on color alone (text, icons, or patterns differentiate supported/rejected/inconclusive/unreviewed).
- [ ] The video canvas exposes equivalent metadata in text for proposed geometry and calibration state.

## Performance basics

- [ ] Initial app load in the browser is under 3 seconds on a typical conference Wi-Fi connection (measure from navigation to first interactive workspace render).
- [ ] Analysis progress updates are visible at least every few seconds; the user is not left with a static spinner for the entire run.
- [ ] Event cards and thumbnails render without blocking the main thread; a sensible loading state is shown while evidence artifacts load.

## Exit criteria (all must be true to pass R03)

1. All items in **Core demo acceptance** are demonstrated on a real built app.
2. All items in **Error and edge-case handling** are either demonstrated or explicitly marked as simulated/mocked with a truthful label.
3. Accessibility and performance basics are validated by direct observation or by a recorded run-through.
4. A second app (person-in-zone, directional counting, or bounded semantic obstruction check) is created through the same chat flow and executed.
5. No unapproved external action or webhook is sent during the demo.
6. Cached, replayed, or synthetic results are clearly labeled with exact source/spec/model revisions.
7. The independent human reviewer confirms the 4-of-5 usability target or documents the specific blockers.
8. No critical unresolved security, correctness, or privacy issue remains open.

## Known limitations statement

Use this wording, or a materially equivalent statement, in the demo introduction and closing:

> This is a **review-oriented hackathon prototype**, not a legal enforcement system.  
> It works best on a short, fixed-camera clip with a visible stop line and signal.  
> Detection, tracking, and signal classification can miss or misidentify objects, especially in occlusion, low resolution, unusual lighting, or at signal transitions.  
> Results are timestamped evidence for human review; they are not a determination of guilt, a traffic citation, or a safety certification.  
> Live CCTV, arbitrary camera angles, long-form universal monitoring, and guaranteed real-time operation are explicitly out of scope for this demo.

## Sign-off

| Role | Name | Date | Result |
| --- | --- | --- | --- |
| Demo runner | | | |
| Human reviewer | | | |
| Security/ops reviewer | | | |

Passing R03 requires all **Exit criteria** to be satisfied and this sign-off to be complete.
