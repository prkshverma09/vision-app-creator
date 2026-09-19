# PRD: Vision App Creator

## A chat-first builder for reusable video intelligence applications

**Research date:** 18 September 2026  
**Status:** Proposed product and technical specification; not an implemented or benchmarked system  
**Target:** {Tech: Europe} Agentic AI Hack, London  
**Working product name:** Vision App Creator  
**Product reference:** Viso Now, not the entire Viso enterprise platform

### Reading guide

- [Executive recommendation](#1-executive-recommendation)
- [Viso research and its minimum product slice](#3-visoai-research)
- [MVP scope](#5-mvp-scope-and-priority) and [user experience](#6-user-experience)
- [Model selection](#8-model-research-and-selection) and [the Jev decision](#9-jev-direct-answer-and-integration-decision)
- [System architecture](#10-system-architecture) and [typed application contract](#11-app-specification-and-compiler-design)
- [Red-light implementation](#12-red-light-application-detailed-behavior) and [general semantic apps](#13-general-purpose-semantic-applications)
- [Evaluation](#17-evaluation-and-acceptance-plan) and [cost model](#18-cost-model)
- [Build milestones](#19-implementation-plan-and-ownership), [demo](#20-demo-narrative), and [risks](#21-risks-mitigations-and-unresolved-decisions)
- [Sources](#24-sources-and-research-notes)

---

## 1. Executive recommendation

Build a web application in which a user uploads a video, describes an outcome in chat, approves the interpretation of the scene and rules, and receives a **saved, executable vision app** with timestamped events, evidence, and configurable actions. Follow-up chat changes the app, not just the description of a video.

The key product loop is:

> **Describe → inspect the scene → compile a typed app → preview on video → refine in chat → save and run again.**

### Recommended starting stack

| Component | Recommendation | Reason |
|---|---|---|
| Chat-to-app compiler and scene understanding | **Gemini 3.8 Flash**, with **Gemini 3.7 Flash** as an explicitly tested fallback | Current documented multimodal models; image/video inputs, structured output, and tool use. Good fit for both building an app and interpreting evidence. [S09–S13] |
| Broad semantic video analysis | **Gemini Flash on short video windows** | Fastest route to a general-purpose promptable analysis capability without training a model. Do not confuse it with exhaustive, frame-accurate monitoring. [S10] |
| Repeated object detection | **RF-DETR Small**, with Nano as the speed fallback | Predictable object boxes for common classes; Apache-2.0 core model; avoids making a generative-model call for every frame. [S14] |
| Object identity and movement | **ByteTrack via Roboflow `trackers`**, plus `supervision` for overlays and geometry | Persistent IDs, trajectories, crossings, and dwell time. A detector alone cannot do these jobs. [S15, S16] |
| Temporal rules | **A small deterministic Python interpreter over a typed rule catalog** | Temporal ordering, counting, deduplication, and event state should be inspectable and testable, not improvised by an LLM. |
| GPU and video jobs | **Modal** | Python-native GPU workers, asynchronous execution, model caching, and a documented path to streaming/WebRTC later. [S21–S25] |
| Agent framework and contracts | **Pydantic AI + Pydantic** | Compile chat into validated application definitions and expose narrow, typed tools. [S26, S27] |
| Evaluation and observability | **Pydantic Evals + Logfire** | Measure prompt compilation, event correctness, latency, token usage, and errors across the full pipeline. [S28, S29] |
| Web UI | **React + TypeScript + Vite**, HTML video with a Canvas/SVG overlay | A small SPA is sufficient; no server-rendering requirement for the MVP. |
| Persistence, media, and identity | **Firestore + Google Cloud Storage + Firebase Authentication/Hosting** | Managed app state, private video objects, authenticated access, and a simple deployment path. [S32, S33] |

**Do not put Jev in the critical path.** Jev currently accepts **text only**, not image frames, audio, or video. It can optionally classify structured observations produced by the vision layer. For exact rules such as “crossed this line after this signal turned red,” ordinary code is faster, cheaper, and more auditable than Jev. [S06–S08]

**The red-light example is feasible as a bounded, review-oriented prototype**, provided the relevant signal and stop line are visible and associated with the correct lane. It is not feasible to promise reliable red-light enforcement from an arbitrary video and one vague sentence, without scene validation or temporal tracking.

**Best architecture:** hybrid perception plus temporal rules, with a VLM for semantics and ambiguity. **Best hackathon strategy:** implement one complete, reusable product loop, a strong red-light demonstration, and a second app using shared primitives—not an enterprise platform or a generic code-generation sandbox.

### Evidence standard

- **Documented:** a current primary source describes the capability or API.
- **Vendor claim:** a provider reports performance or broad capability; not independently verified here.
- **Recommendation:** a design choice based on fit, cost, and implementation risk.
- **Target:** a measurable goal for this project, not an achieved result.

No authenticated Viso session, paid inference benchmark, sponsor-credit redemption, or live camera test was performed in this research. The workspace was empty. Sources were checked on the research date; model availability, prices, quotas, and SDK compatibility must be smoke-tested before implementation is committed to them.

---

## 2. Hackathon context and constraints

The event page describes a one-day agentic AI hackathon: teams form in the morning, build during the day, and demo in the evening. Its published Saturday schedule includes opening/matchmaking at 10:00, competition opt-in at 19:00, demos at 20:00, and awards at 20:45. It lists Google DeepMind and Conduct as co-hosts, and Modal and Pydantic as technology partners. Participants are promised provider credits. [S01]

Important qualifications:

- The extracted page did not expose a reliable calendar date; confirm the date in the registration/calendar invite.
- Credit amounts, redemption mechanics, eligible products, and precise judging criteria were not published in the retrieved text. Do not invent sponsor-specific prize rules or assume generic Google Cloud credits also pay for every Gemini API route.
- The page says capacity is limited to 70 and entry is first-come, first-served even with a ticket. Confirm entry and team arrangements separately.
- The app should demonstrate genuine agency: inspecting input, asking for missing information, selecting capabilities, compiling and validating a policy, running a test, and applying a revision. A chatbot that merely returns a summary is not the intended product.

### Sponsor integration that is technically justified

1. **Google:** Gemini is central to app creation and semantic understanding; Firebase/GCS support the product. Optional Gemma on Modal is a later privacy/cost experiment, not a requirement to collect another logo.
2. **Modal:** runs the actual perception and media-processing workload on GPUs. This is more meaningful than hosting an otherwise unrelated helper function.
3. **Pydantic:** supplies the executable app contract, compiler agent, validation, evaluation, and traces. Show a real validation rejection and an evaluation result in the demo.

Prefer non-sponsor technology when it is better suited to a component. In particular, RF-DETR and ByteTrack are better suited to the MVP tracking loop than repeatedly asking a general-purpose Google model for object identities.

---

## 3. Viso.ai research

### 3.1 What Viso Now actually presents

Viso Now positions itself as an agentic computer-vision builder: “Build any real-world vision app in minutes.” Its three-step public workflow is: [S02]

1. **Start with an idea:** type a description or provide a clip; no dataset, labeling, or model selection presented to the user.
2. **Watch it build:** the system claims to connect the feed, recognize the scene, write detection logic, and wire alerts.
3. **Refine and ship:** adjust rules, thresholds, or outputs, then publish and run.

The product page advertises:

- Natural-language creation of vision applications.
- Ready-made templates.
- Dashboards showing compliance, counts, events, trends, and deviations.
- Files, webcams, IP/CCTV cameras, video systems, and cloud-folder sources.
- Email, Slack, Teams, direct API, and webhook-style integrations.
- A “Visual General Intelligence” engine, described as a pretrained model with broad visual reasoning.

**Interpretation:** the product is an app lifecycle around vision intelligence, not just a vision API or a one-off video question-answering interface.

### 3.2 Viso Now versus Viso Suite versus Viso Gateway

| Product | Public positioning | Relevance to this project |
|---|---|---|
| **Viso Now** | Chat-first creation and operation of vision agents | Clone the essential interaction and execution loop. |
| **Viso Suite** | Enterprise build/deploy/operate platform; visual workflow studio, edge/on-prem/cloud deployment, governance, integrations, and managed services | Do not attempt full parity in a hackathon. [S04] |
| **Viso Gateway** | Preconfigured device for secure camera connectivity; outbound HTTPS on port 443 | Demonstrates that connecting private CCTV is a separate engineering problem. [S05] |

Viso explicitly says the standard Gateway is primarily for camera connectivity and media ingestion. Dedicated local inference belongs to its enterprise edge products. Do not assume every Viso deployment is edge inference, or that a web app can directly reach an arbitrary private RTSP camera. [S05]

### 3.3 Templates reveal the product's practical market

The public gallery displayed 44 templates when checked. Examples include: [S03]

- Wrong-way vehicle detection and level-crossing violation monitoring.
- Loading-dock exclusion zones and forklift/pedestrian separation.
- Emergency-exit clearance and machinery exclusion zones.
- Queue pressure and front-desk waiting.
- Packaging defects, PPE checks, and warehouse audits.

These templates mix three different technical problems:

1. **Geometric/temporal:** crossing, direction, occupancy, dwell time.
2. **Semantic/contextual:** whether an exit is obstructed or work practices appear unsafe.
3. **Domain-specific perception:** a subtle defect, particular protective equipment, or a specialized industrial object.

A single MVP should not claim equal reliability across all three. Their evaluation and sensing requirements differ.

### 3.4 Pricing and packaging

The retrieved pricing page lists: [S30]

| Plan | Public starting price/allowance | Implication |
|---|---|---|
| Free | $0; 5 daily credits, capped at 30/month | Very low-friction experimentation. |
| Pro | Starts at $25/month on the displayed annual option, including VAT; shared across unlimited users | Monetization is based on capacity/usage rather than seats alone. |
| Business | Starts at $50/month on the displayed annual option, including VAT | Adds organizational controls and priority processing. |
| Enterprise | Custom platform fee and credit pricing | Governance, deployment, and service requirements drive enterprise value. |

Illustrative credit examples on the same page: build an agent 0.4 credits; refine it 0.1; analyze images/short clips 0.2–1; longer video 2–3. These are Viso's examples, not a stable conversion to video minutes or a public inference-cost model. Do not use them to infer Viso's GPU cost or latency.

### 3.5 What is Viso's MVP feature?

There is no verified public account here of Viso's original historical MVP. The **minimum product slice to reproduce now**, inferred from its current workflow, is:

> **Turn a natural-language visual monitoring objective into a reusable application, test it against a video, expose useful events/evidence, and refine the behavior through chat.**

That slice needs six capabilities:

1. Chat-based intent capture and clarification.
2. A video input and scene preview.
3. An executable representation of what to look for.
4. Running that representation on video.
5. Timestamped results with visual evidence.
6. Saving and editing the app for another run.

Templates, a basic event counter, and an action destination make the experience feel complete. Enterprise SSO, fleet management, billing, model training, and dozens of connectors do not establish the core value proposition.

### 3.6 What cannot be established from public material

- The exact model behind Viso's VGI branding, its architecture, weights, or training data.
- Independently measured accuracy, false-alert rates, cost per camera-hour, or end-to-end latency for the example tasks.
- Whether every advertised connector or use case behaves identically on every plan.
- The actual authenticated builder UX: the public documentation endpoint exposed only a minimal shell to this research tool. [S31]

Treat “human-level,” “any scene,” and “no retraining” as marketing claims, not engineering guarantees. The public VGI whitepaper is useful context but does not establish a reproducible model specification for a clone. [S35]

Build an independently designed functional alternative. Do not copy Viso branding, proprietary assets, implementation, or imply affiliation.

---

## 4. Product definition

### 4.1 Problem

An operations user can describe a useful visual rule but cannot easily translate it into models, tracking, video pipelines, temporal logic, a UI, and an alert integration. Conventional CV development exposes too much implementation complexity before the user can validate an idea.

### 4.2 Product promise

> “Describe what matters in your video. Get a reusable app that finds events, shows the evidence, and follows your approved rules.”

Do not promise “any action” literally. The MVP supports classification, counts, evidence creation, in-app alerts, and an explicitly configured webhook. Physical control, penalties, payments, and other consequential actions are excluded.

### 4.3 Initial users

- **Hackathon/demo user:** wants a compelling app from a clip and a prompt.
- **Operations or safety analyst:** wants to test a visual monitoring idea without building an ML stack.
- **Technical integrator:** wants a reusable, inspectable app definition and event output.

The first production customer hypothesis is a small operations team validating a fixed-camera workflow. Public-road enforcement is not the initial commercial positioning.

### 4.4 Jobs to be done

- “Tell me which events match this rule, and show why.”
- “Let me change the rule without changing code.”
- “Run the same policy on another clip from this camera.”
- “Tell me when the video is insufficient instead of pretending nothing happened.”
- “Send approved events into my workflow.”

### 4.5 Distinguishing features

- **Persistent apps, not disposable answers.**
- **Typed, inspectable rules**, with version history and a human-readable explanation.
- **Evidence-first results**: scene, track, signal state, timestamps, and limitations.
- **Hybrid execution**: fast CV for measurable events; VLMs for semantic questions.
- **Explicit uncertainty and coverage**, rather than a misleading single confidence percentage.

---

## 5. MVP scope and priority

### 5.1 P0: required to call the hackathon MVP complete

| ID | Requirement | Acceptance condition |
|---|---|---|
| F01 | Create an app from chat | Supported prompts produce a validated app definition or a specific clarification; unsupported behavior is not silently accepted. |
| F02 | Upload and inspect video | Accept MP4 with a supported codec, up to 5 minutes and 250 MB; display duration, dimensions, preview, and actionable errors. |
| F03 | Understand and confirm the scene | Propose relevant region/line/signal geometry; show it on video; require confirmation for spatial rules. |
| F04 | Compile into reusable capabilities | Execute a versioned app specification rather than arbitrary generated Python. |
| F05 | Run and monitor | Show job state, processed-video position, coverage, and partial results. Reloading the page does not lose the job. |
| F06 | Evidence timeline | Each event includes source timestamp, reason, app version, decision status, thumbnail, and a playable evidence interval. |
| F07 | Chat refinement | A follow-up such as “ignore motorcycles” creates a new version and changes runtime behavior on re-test. |
| F08 | Save and rerun | A saved app can process another clip; a changed camera requires a new calibration confirmation. |
| F09 | Red-light scenario | Detect **suspected red-phase stop-line crossings** in the supported fixed-camera setup, including negative and unknown cases. |
| F10 | A second reusable use case | Demonstrate person-in-zone or directional vehicle counting through the same compiler/runtime. |
| F11 | General semantic mode | Support a bounded clip-classification prompt, such as visible exit obstruction, with evidence and an explicit sampled-analysis label. |
| F12 | Actions | Create in-app events and support a dry-run webhook delivery preview; dispatch to one approved test destination only after opt-in. |
| F13 | Basic access and privacy | Authenticated ownership of apps/media; private storage; scoped upload/download authorization; deletion controls. |
| F14 | Evaluation and instrumentation | Run deterministic rule tests and a small labeled end-to-end suite; display actual latency/usage, not invented numbers. |

The red-light scenario remains a required deliverable. If its prerequisites or acceptance tests fail, label that capability experimental/incomplete; do not quietly substitute a line counter and claim the original example is solved.

### 5.2 P1: after the complete core loop works

- Live-like playback of a prerecorded source with incremental event arrival, clearly labeled **replay**.
- Real webcam input through WebRTC.
- Slack or Teams connector in addition to the approved webhook.
- Full annotated-video export; the P0 overlay and evidence player do not require re-encoding the entire video.
- Side-by-side comparison of app versions.
- A simple dwell-time template using the same tracker.
- Agentic search over longer uploaded videos.
- Optional Jev experiment on semantic routing after perception.

### 5.3 P2: post-hackathon product

- Outbound-only RTSP/ONVIF gateway and live stream recovery.
- Multiple cameras and camera-specific calibration management.
- Open-vocabulary localization/segmentation.
- Domain-specific classifiers and optional fine-tuning from reviewed examples.
- Edge/self-hosted inference; continuous-stream cost optimization.
- Team roles, audit exports, workflow integrations, and production incident handling.

### 5.4 Explicit non-goals

- Recreating Viso Suite, hardware, or managed services.
- Training a foundation model.
- Autonomous arbitrary-code execution from prompts.
- Universal zero-shot accuracy or guaranteed real-time operation on any input.
- Facial recognition, personal identity tracking, number-plate recognition, or cross-camera re-identification.
- Legal adjudication, automatic fines, emergency dispatch, or physical machinery control.
- Inferring facts that are not visible, such as a signal outside the image.

---

## 6. User experience

### 6.1 Main screen

A three-part workspace:

1. **Chat:** user objective, short clarification questions, actual tool progress, and revision history.
2. **Video canvas:** playback, proposed zones/lines, tracked objects, and timestamp-aligned overlays.
3. **App/results panel:** rule summary, Run/Stop/Save controls, event cards, counters, and limitations.

Show an app status separately from a run status. A valid saved app can have no runs; a failed run does not invalidate an earlier version.

### 6.2 Example conversation

**User:** “Find cars that run the red light in this video and save a clip of each one.”

**Assistant behavior:**

1. Inspect representative frames and video metadata.
2. State: “I can flag suspected stop-line crossings while the relevant signal is red. I need to confirm the lane, signal, and stop line.”
3. Propose labeled geometry on the preview.
4. Ask: “Use lane A, signal B, and the highlighted line? Should ‘cars’ mean cars only or all motor vehicles?”
5. Compile the approved policy and show its plain-language summary.
6. Run a short preview; show a positive, a negative, and any inconclusive evidence.
7. Save the app and offer a full run.

**User:** “Include buses and trucks, but ignore motorcycles.”

**Assistant behavior:** show the class-filter change, create version 2, reuse compatible cached observations, and re-evaluate. Never mutate the already-published version behind an existing run.

### 6.3 What “just a chat prompt” can honestly mean

- No code, dataset creation, training, or model selection is required from the user for supported tasks.
- The agent proposes the geometry and settings. On the prepared demo scene, the user should be able to complete setup with text confirmation alone.
- Clarifying chat is allowed and necessary when the objective is ambiguous.
- Optional direct manipulation of overlays is a recovery tool, not the primary builder UX.
- If the signal-to-lane mapping or boundary cannot be inferred confidently, stop and request clarification or another source. A genuinely unknown geometric fact cannot be made reliable by adding a more assertive prompt.

### 6.4 Event UX

An event card contains:

- Label: “Suspected red-phase crossing,” not “Driver committed an offense.”
- Source time and evidence start/end times.
- Local track ID and object class, where applicable.
- Rule facts: crossing interval, relevant signal interval, lane association, and exclusions.
- Status: `candidate`, `supported`, `rejected`, or `inconclusive`.
- Review state: `unreviewed`, `confirmed_by_user`, or `dismissed_by_user`.
- Evidence-quality flags and a short factual explanation.
- Action-delivery status.

`Supported` means the configured visual rule is supported by evidence; it is not a legal conclusion. Human review state is separate from machine decision state.

---

## 7. Why the architecture must be hybrid

A red light and a vehicle in the same frame do **not** establish a violation. The system must know:

- Which light governs which movement.
- Whether the vehicle crossed the relevant boundary in the prohibited direction.
- Whether the same vehicle was before and after the line.
- Whether the signal was already red when that crossing happened.
- Whether the car entered legally earlier, the signal is occluded, or timing is ambiguous.

### Architecture options

| Approach | Strength | Limitation | Decision |
|---|---|---|---|
| One VLM request for the whole video | Simplest prototype; broad semantics | Sampling omissions, approximate timestamps, weak persistent identity, variable latency | Useful semantic mode and baseline; not the sole traffic engine. |
| Independent frame images sent to a VLM | Simple API and easy parallelism | Loses motion/identity unless context is added; high request count; inconsistent events | Do not use as the core design. |
| Detector + tracker + rules | Fast, testable, strong for measurable geometry | Fixed object vocabulary; scene calibration needed | Primary traffic/counting/zone execution path. |
| VLM + detector + tracker + rules | Broad interaction plus precise measurable primitives | More integration work than a single API call | Recommended. |
| Vision observations → Jev → actions | Cheap structured semantic decisions | Jev cannot see missing pixels or repair inaccurate observations | Optional routing layer, never the only evidence gate. |
| Generate and run arbitrary CV code | Broad apparent flexibility | Hard to secure, debug, reproduce, and bound | Not an MVP requirement. |

The LLM should act like a **compiler and analyst**. It should not be the scheduler, the tracker, the source of authoritative timestamps, and the action authorization system all at once.

---

## 8. Model research and selection

### 8.1 Hosted multimodal models

#### Gemini 3.8 Flash: recommended initial model

Google's current catalog documents `gemini-3.8-flash` as a stable model accepting text, image, video, audio, and PDF, with a 1,048,576-token input limit and structured-output support. `gemini-3.7-flash` is also documented and is a useful fallback. [S09, S12, S13]

Use it for:

- Interpreting the user's objective.
- Inspecting scene frames and proposing a calibration.
- Compiling and revising an app specification.
- Short-window semantic classification.
- Reviewing evidence and explaining observations.

This is a recommendation based on documented integration fit, not a measured claim that Gemini beats every alternative on the target footage. Evaluate 3.8 versus 3.7 on the same prompts and clips; freeze the better working model before the demo.

#### Gemini 3.5 Flash-Lite: cost challenger

The current price is lower than Flash, and Google's video documentation includes it among models supporting agentic video processing. [S10, S11]

Use only after it passes the same domain tests, especially for small signals, negation, and temporal order. Suitable candidates are simple semantic checks, title generation, and non-critical routing. Do not choose it solely from a price table.

#### Static versus agentic video processing

Google documents two modes: [S10]

- **Static:** default sampling is 1 FPS; configurable FPS and media resolution.
- **Agentic:** the model navigates the video and selectively loads relevant material. Supported models include 3.8 Flash, 3.7 Flash, 3.6 Flash, and 3.5 Flash-Lite.

Google reports up to 88% fewer tokens on long-form video. That is a vendor result, not an expected saving for this app. Agentic navigation may increase first-response latency on short clips.

**MVP choice:** static, bounded video windows for reproducible short-clip analysis; deterministic high-frequency tracking for temporal geometry. Add agentic mode for long-video exploration later. Adaptive search is not a guarantee that every brief event was examined.

The current Google documentation recommends the generally available **Interactions API** for new integrations; `generateContent` remains supported. [S34] Pydantic AI's Google provider documents multimodal support, but this research did not establish that it exposes every new Interactions video-processing option. Keep a direct `google-genai` adapter for video tools, returning Pydantic-validated results to the agent. Do not block the project on framework feature parity.

#### Other hosted providers

Image-capable general LLMs can also compile policies or inspect sampled frames. There is no project-specific evidence here that switching providers improves traffic tracking. Compare alternative providers only through the same adapter and evaluation suite, rather than claiming Google is intrinsically superior because it sponsors the event.

**Twelve Labs:** Marengo and Pegasus offer specialized video retrieval/understanding APIs. They are credible candidates for a later long-video search/archive product. Their documented indexing and analysis workflows add a separate platform integration, and they do not remove the need for lane geometry and persistent tracking. Not the initial MVP dependency. [S20]

### 8.2 Fast detection and tracking

#### RF-DETR Small / Nano

RF-DETR's core Nano-to-Large detection models and code are Apache-2.0; XL/2XL Plus components have different licensing. Use the core package/checkpoint explicitly. [S14]

The vendor reports Small at 53.0 COCO AP50:95 and 3.5 ms inference latency, and Nano at 48.4 AP and 2.3 ms. Those measurements use **T4, TensorRT, FP16, batch size 1**. They are not Python pipeline, video decode, GPU cold-start, or end-to-end application latencies.

**Choice:** start with Small; evaluate Nano if throughput is inadequate. Use the pretrained common classes for people, cars, buses, trucks, and motorcycles. A generic traffic-light bounding box does not classify its illuminated state; use a separate calibrated signal-region observer.

A forklift, missing helmet, or custom manufacturing defect is not automatically supported just because RF-DETR is installed. The compiler must consult the capability registry.

#### ByteTrack and Supervision

Use `ByteTrackTracker` from Roboflow's Apache-2.0 `trackers` package. Use MIT-licensed `supervision` for detections, drawing, and geometry utilities. [S15, S16]

Current Supervision docs deprecate `sv.ByteTrack` in favor of the external package. Avoid building new code around an old tutorial import. ByteTrack is appropriate for a fixed-camera MVP; it still has ID switches under occlusion and does not provide true identity or reliable cross-camera tracking.

#### YOLO26 alternative

YOLO26 is a documented, available real-time family with integrated tracking workflows. YOLO27 is presented as an unreleased preview/waitlist, not a dependable build requirement. [S17]

YOLO26 is a strong alternative if the team already knows its APIs. Ultralytics uses AGPL-3.0 and enterprise licensing; evaluate the actual obligations before adopting it for a proprietary service. Do not assume “hackathon” or “behind an API” eliminates licensing obligations. [S18]

**Why prefer RF-DETR here:** permissive core licensing and sufficient documented detector/tracker integration—not a claim that it always has better latency or accuracy than YOLO26.

### 8.3 Open/self-hosted vision-language candidates

| Model | Verified capability | Best possible role | Why not on the P0 critical path |
|---|---|---|---|
| **Gemma 4 E4B / 12B** | Google's open multimodal family includes image/video understanding; current model card lists Apache-2.0. [S19] | Sponsor-aligned private crop/clip classification on Modal | Must validate actual checkpoint, memory, serving support, latency, and domain accuracy. |
| **Qwen3.5-9B** | Apache-2.0, native vision-language model with documented Transformers/vLLM integration. [S36] | Compact non-sponsor VLM challenger | Hosting and vision preprocessing add work; not proven faster end-to-end than hosted Gemini here. |
| **Qwen3.8-27B** | Current Apache-2.0 model card documents image/video understanding and controllable thinking. [S37] | Higher-capacity self-hosted challenger | Larger memory and cold-start cost; not the economical default for sparse demo requests. |
| **NVIDIA Cosmos-Reason2** | Physical/spatiotemporal reasoning and localization; open model under NVIDIA-specific terms. [S38] | Offline incident reviewer for safety/physical interactions | Reasoning overhead and serving complexity; no project-specific benchmark yet. |
| **SAM 3** | Text/visual-prompted detection, segmentation, and tracking in images/video. [S39] | Open-vocabulary objects and precise masks in P2 | Gated access, custom license, compute/state complexity; not a complete temporal rule engine. |

A 9B model in BF16 needs roughly 18 GB for weights alone, before KV cache, vision encoder workspace, and serving overhead. A 27B dense model is roughly 54 GB before overhead. Do not assume “small active parameter count” or a 24 GB GPU guarantees a particular model/context will fit. Start any optional self-hosting experiment with measured memory use, short contexts, and a prewarmed worker; use quantization only after checking accuracy.

### 8.4 Model routing policy

1. Exact arithmetic, comparisons, temporal state, and deduplication → Python.
2. Common-class object boxes → RF-DETR.
3. Persistent object IDs → ByteTrack.
4. Signal state in a known, visible ROI → conservative calibrated vision classifier, with unknown state.
5. Broad visual semantics → Gemini short-window analysis.
6. Ambiguous evidence → Gemini review or human review.
7. Text-only fuzzy routing after perception → optional Jev experiment.
8. Unsupported object vocabulary or unavailable visual evidence → clarification/unsupported, not fabricated capability.

---

## 9. Jev: direct answer and integration decision

### 9.1 Can Jev receive video frames and decide what happened?

**No, not with the currently documented API.** TypeSafe's State and Models documentation explicitly says text only; images, audio, and video are not supported. Sending base64 image strings does not add vision capability. [S06, S08]

The launch article's Doom demonstration uses structured game-state text, not images. [S07]

### 9.2 What Jev actually provides

The current documented model is `jev-1.13.0`; `jev-latest` and `jev-preview` currently resolve to it. Its primitives are: [S06, S08, S40]

- **Choice:** an option, probabilities, and a confidence statistic.
- **Score:** a rubric score/distribution and confidence.
- **Noul:** probability of a yes/no statement; no separate confidence field.

The docs list 64K total context, with a separate 32K constraint on state plus the longest question. They list $0.042 per million input tokens and free output tokens. Published rate limits are explicitly subject to change. [S08]

The launch article reports 70–500 ms end-to-end calls and very large speed/cost improvements on its System One workloads. Those are vendor measurements, often from the US West Coast, not a London-to-provider latency guarantee and not video-processing benchmarks. Early-access availability is a delivery risk. [S07]

### 9.3 Where it can help

A legitimate integration is:

> Video → detector/VLM observations with timestamps and missing-data flags → Jev semantic routing → deterministic policy gate → approved action.

Example state supplied to Jev could contain a reviewed event description, known rule facts, severity rubric, and explicitly missing facts. Ask independent questions such as “Which review queue should receive this?” or “Does this description require a supervisor's review under this policy?”

Do not ask Jev to infer a hidden signal or decide a crossing from a single caption. Errors and information loss in the perception layer propagate into its decision.

### 9.4 Why not use it for the red-light rule?

Once we have `crossing_interval`, `red_interval`, `direction`, and `lane_id`, an interval comparison in code is essentially free and fully inspectable. Jev adds a network call and probabilistic interpretation without improving the underlying evidence.

Nor can Jev replace the conversational builder: it does not generate arbitrary explanatory text or arbitrary new application code.

### 9.5 Claims to interpret carefully

- **Type-safe does not mean factually correct.** A wrong enum value can still perfectly satisfy a schema.
- “Cannot hallucinate” in the launch framing must not be interpreted as “cannot make a wrong real-world judgment.”
- Jev's reported `confidence` is derived from the probability distribution, not a separately verified probability that the whole CV pipeline is correct. [S40]
- Calibration on vendor tasks does not establish calibration on noisy traffic observations.

### 9.6 Optional go/no-go experiment

Only after the core app works and access is available:

- Compare deterministic routing, Gemini Flash-Lite, and Jev on the **same frozen textual observations**.
- Include missing facts, conflicting observations, negation, and ambiguous severity.
- Measure correct routing, abstention, Brier score where appropriate, p50/p95 round-trip latency, and actual billed tokens.
- Pin the Jev version and log the returned version.
- Adopt it only if it improves a real semantic decision without reducing safety or evidence quality.
- Failure or lack of access must not disable app building, traffic detection, or event display.

---

## 10. System architecture

### 10.1 Control plane and execution plane

```text
React browser application
  ├── Firebase Authentication
  ├── Chat + app summary + scene overlays
  ├── Direct authorized upload to private Cloud Storage
  └── Authenticated HTTP / streaming progress
             │
             ▼
Modal CPU service: FastAPI
  ├── Ownership, quotas, and budget checks
  ├── Pydantic AI compiler agent
  │     ├── Inspect source metadata / sample frames
  │     ├── Gemini: scene interpretation + AppSpec proposal
  │     └── Pydantic + semantic validation + dry run
  ├── Firestore: apps, immutable versions, runs, events, action records
  ├── Launch/cancel/status for background analysis jobs
  └── Action outbox: only approved destinations and permissions
             │
             ▼
Modal video worker
  ├── FFmpeg / PyAV decoding, source timestamps, clip extraction
  ├── RF-DETR model loaded once per warm GPU container
  ├── ByteTrack state owned by one source/run
  ├── Signal ROI observation and deterministic temporal rules
  ├── Bounded Gemini semantic/review calls via a CPU-side adapter
  └── Evidence artifacts → Cloud Storage; results → Firestore

Pydantic Logfire / OpenTelemetry across compiler, job, model, rule, and action spans
Pydantic Evals against fixed prompts, labeled clips, and expected events
```

### 10.2 Why this deployment shape

- Keep the Python CV stack, agent tools, and typed contracts in one language.
- Keep media bytes out of Firestore and out of the chat history.
- Do not route large uploads through a short-lived LLM or frontend request.
- Use Modal CPU functions for orchestration and API work; reserve GPU resources for perception.
- Do not keep a GPU unnecessarily blocked waiting for a long LLM response. Candidate evidence review can be asynchronous while detection continues.
- Do not send each frame through a separate network hop to a GPU endpoint. Send the job/source reference, decode near the model, and stream small metadata updates back.
- Use one persistent database. Modal Volumes cache weights/artifacts but are not the source of truth for multi-user application state.

### 10.3 Frontend implementation choices

Use a Vite SPA, React, TypeScript, and a small component library chosen at implementation time. Video overlays should be drawn against original-video coordinates transformed into the displayed letterboxed rectangle.

For the P0 preview, play the original source and fetch sparse timestamped overlay data. Full-video re-encoding is unnecessary. Evidence clips can be extracted separately; permit source playback at the evidence interval as a fallback when extraction fails.

Use authenticated `fetch` streaming for SSE-style progress, or authenticated polling. Browser `EventSource` cannot directly attach a normal bearer Authorization header; do not work around this by putting access tokens in query strings.

### 10.4 Persistence entities

| Entity | Important fields |
|---|---|
| `Workspace` | owner/member IDs, usage limit, retention settings |
| `VisionApp` | workspace, title, draft version, published version, lifecycle state |
| `AppVersion` | immutable spec, parent version, prompt revision, capability versions, validation report |
| `SourceAsset` | owner, storage object ID, hash, size, codec, dimensions, duration, retention deadline |
| `Calibration` | source/camera binding, reference frame, geometry, transforms, confirmed-by/at |
| `Run` | app version, calibration, source, status, worker call ID, progress, processed intervals, usage, errors |
| `Event` | run, rule, source interval, track refs, evidence IDs, decision and review states, reason facts |
| `ActionDelivery` | event, destination ref, idempotency key, attempts, status, failure reason |

Keep calibration separate from reusable policy. A policy can transfer to another camera, but its coordinates and signal association cannot automatically transfer with it.

### 10.5 Minimal API contract

| Endpoint | Purpose |
|---|---|
| `POST /v1/uploads` | Validate proposed metadata and issue a scoped upload grant. |
| `POST /v1/uploads/{id}/complete` | Verify stored object and probe media before accepting it. |
| `POST /v1/apps` | Create an owned draft app. |
| `POST /v1/apps/{id}/messages` | Chat, clarify, and produce a proposed version with streamed progress. |
| `POST /v1/calibrations/{id}/confirm` | Record explicit scene confirmation. |
| `POST /v1/apps/{id}/versions/{version}/publish` | Publish only after validation and user approval. |
| `POST /v1/runs` | Start a run against an immutable version; require confirmed calibration for spatial rules. |
| `GET /v1/runs/{id}` | Status, coverage, usage, and error summary. |
| `GET /v1/runs/{id}/events` | Cursor-based events and revisions. |
| `GET /v1/runs/{id}/stream` | Optional incremental status/event stream with reconnect cursor. |
| `POST /v1/runs/{id}/cancel` | Request cooperative cancellation. |
| `POST /v1/events/{id}/review` | Confirm or dismiss, with reviewer identity. |
| `POST /v1/events/{id}/actions/preview` | Show the proposed payload without sending it. |
| `DELETE /v1/assets/{id}` | Authorized deletion workflow and derived-artifact cleanup. |

All resource reads and writes enforce ownership server-side. Model tools call internal typed functions, not arbitrary HTTP endpoints supplied by the model.

---

## 11. App specification and compiler design

### 11.1 Use a small application language, not unrestricted code

An `AppSpec` contains:

- Name, objective, and supported operating conditions.
- Execution mode: `tracked_rules` or `semantic_windows`.
- Required source/calibration capabilities.
- Approved object classes and observer types.
- Rules built from a finite catalog.
- Sampling and processing limits.
- Evidence and uncertainty policy.
- Approved action references.
- Model/capability versions and schema version.

Pydantic provides structural validation. Additional semantic validation verifies references, supported combinations, geometry, units, and permissions. A schema-valid spec can still be an invalid or unsupported app.

### 11.2 Initial capability catalog

| Category | P0 capabilities |
|---|---|
| Perception | common-class detection; calibrated signal-state observation; semantic clip classification |
| Tracking | per-source object tracks |
| Geometry | polygon membership; oriented finite-line crossing |
| Temporal | persistence; interval overlap/order; per-track event state |
| Aggregation | unique event count; class filter; deduplication |
| Evidence | timestamped observations; thumbnail; source interval/clip |
| Actions | in-app event; webhook preview; explicitly enabled approved webhook |

Add dwell time as a small extension only after the initial rules work. Do not accept arbitrary mathematical expressions or executable strings disguised as a rule.

### 11.3 Compiler tools

- `inspect_video(source_id)`
- `sample_scene_frames(source_id, bounded_timestamps)`
- `list_capabilities()`
- `propose_calibration(source_id)`
- `validate_app_spec(spec)`
- `preview_app(version_id, bounded_interval)`
- `summarize_preview(run_id)`
- `propose_revision(version_id, instruction)`

The compiler can propose a publish operation but cannot grant itself approval or connector permissions. Limit tool calls, model requests, retries, output size, and per-build spend. Use at most two automatic repair attempts before presenting a clear error/clarification.

### 11.4 Example policy representation

Illustrative contract to implement and validate; not a vendor API payload. No coordinates are universal defaults.

```json
{
  "schema_version": "1.0",
  "name": "Red-phase crossing review",
  "mode": "tracked_rules",
  "objective": "Flag motor vehicles crossing the confirmed stop line during a confirmed red phase",
  "required_calibration_roles": ["approach_lane", "stop_line", "governing_signal"],
  "observers": [
    {
      "id": "vehicles",
      "kind": "object_detection",
      "model": "rfdetr-small",
      "classes": ["car", "bus", "truck"],
      "target_fps": 10
    },
    {
      "id": "signal",
      "kind": "calibrated_signal_state",
      "roi_role": "governing_signal",
      "states": ["red", "amber", "green", "unknown"],
      "minimum_stable_ms": 300
    }
  ],
  "tracker": {
    "kind": "bytetrack",
    "observer_id": "vehicles",
    "maximum_observation_gap_ms": 300
  },
  "rules": [
    {
      "id": "cross_on_red",
      "kind": "red_phase_crossing",
      "track_source": "vehicles",
      "lane_role": "approach_lane",
      "line_role": "stop_line",
      "direction": "approach_to_junction",
      "crossing_anchor": "bottom_center_proxy",
      "signal_observer_id": "signal",
      "require_red_for_entire_crossing_interval": true,
      "transition_ambiguity_ms": 200,
      "on_missing_evidence": "inconclusive",
      "deduplicate_by": "track_and_rule_and_crossing_episode"
    }
  ],
  "evidence": {
    "pre_event_seconds": 3,
    "post_event_seconds": 3,
    "include_track_and_signal_observations": true
  },
  "actions": [
    {"kind": "in_app_event"},
    {"kind": "webhook", "destination_ref": "approved_test_sink", "enabled": false}
  ],
  "limits": {
    "maximum_video_seconds": 300,
    "maximum_review_calls": 20,
    "maximum_estimated_run_cost_usd": 0.50
  }
}
```

### 11.5 Required validators

- Reject unknown fields, unsupported capabilities, duplicate IDs, and broken references.
- Bound duration, FPS, class counts, tool calls, event counts, and model output sizes.
- Check that line segments have nonzero length and polygons are valid.
- Validate normalized coordinates against `[0,1]`, with explicit coordinate-space metadata.
- Verify lane/signal/line bindings belong to the same confirmed calibration.
- Require timestamps in integer source milliseconds; do not mix them with wall-clock time.
- Require `unknown`/abstention handling for perception-dependent rules.
- Reject cross-frame rules in a frame-independent execution plan.
- Reject model names and action destinations outside the installed registry.
- Require permission and user confirmation separately from the LLM's proposed action.
- Keep model scores separate from claims about calibrated event probability.

---

## 12. Red-light application: detailed behavior

### 12.1 Supported operating envelope

P0 supports:

- A fixed camera with no scene cuts or PTZ movement.
- A visible stop line, approach lane, and the signal governing that lane.
- Sufficient image detail to distinguish the signal state and track vehicles around the line.
- A simple through movement without special turn-arrow or jurisdiction-specific exceptions.
- Source timestamps that can be recovered from the video.

A coarse bounding-box anchor is a **visual crossing proxy**, not the exact front bumper or wheel crossing a legal stop line. The UI and results must say so. A future enforcement-grade system would need better localization, calibrated geometry, legal interpretation, and validated sensing.

### 12.2 Scene calibration

1. Extract several representative frames, not only frame zero.
2. Ask Gemini to propose lane polygon, finite stop-line segment, direction, and signal ROI.
3. Map model coordinates into normalized original-video coordinates and show the overlay.
4. Ask the user to confirm the lane-to-signal relationship.
5. Reject or request another source if the required scene facts are absent.
6. Save calibration with source/camera identity, reference frame, and confirmation metadata.

The agent may suggest a stop line, but cannot assume that any visible white line is the relevant boundary. Moving the camera invalidates calibration.

### 12.3 Signal-state observation

A COCO detector's `traffic light` class locates an object; it does not establish red/amber/green state.

For the constrained MVP:

- Inspect the confirmed signal crop at original resolution.
- Use a conservative, calibrated color/brightness classifier with expected lamp locations for the supported signal style.
- Apply temporal stability checks; expose `unknown` for insufficient pixels, glare, ambiguous colors, occlusion, or unsupported signal shapes.
- Use the VLM to review ambiguous crops/short sequences, but do not make it a 30-FPS loop.
- Maintain source-timestamped state intervals with uncertainty bounds.

The example 300 ms stability setting is a configurable engineering noise filter, **not a legal grace period**. Do not backdate a red transition to a time not supported by observations. A later dedicated signal-state model can replace this observer without changing the rule interpreter.

### 12.4 Vehicle tracking and crossing

- Run detection at a configured starting rate of 10 FPS; benchmark and increase around fast crossings if needed.
- Maintain one ordered tracker state per source/run.
- Filter to the approved lane and object classes.
- Use a finite-line intersection and oriented crossing, not only a sign change against an infinite line.
- Require confirmed observations before and after the line with continuous enough tracking.
- Represent crossing time as the interval between the last pre-line observation and first post-line observation.
- Use hysteresis near the line to avoid jitter-triggered repeated crossings.
- Treat a track that first appears past the line as insufficient evidence, not a proven crossing.
- A predicted Kalman position without an observation cannot by itself establish a violation.

The signal ROI can be examined more frequently than full-frame detection because it is small. Trackers must use the actual sampling interval; changing FPS without adjusting temporal parameters changes their behavior.

### 12.5 Temporal decision rule

For track `T` and rule `R`:

```text
candidate(T, R) =
  eligible_object_class(T)
  AND associated_with_confirmed_approach_lane(T)
  AND observed_oriented_crossing_of_finite_stop_line(T)
  AND acceptable_tracking_continuity(T)

supported(T, R) =
  candidate(T, R)
  AND entire_crossing_interval_is_inside_confirmed_red_interval
  AND crossing_interval_is_outside_transition_ambiguity_band
  AND required_evidence_is_visible
  AND no_configured_exclusion_applies
```

If the crossing is entirely before red, reject the red-phase rule. If the crossing interval overlaps the red transition uncertainty, label inconclusive. Being inside the junction after red starts is not sufficient if the vehicle crossed earlier.

Suggested per-track state progression:

`approaching → crossing_candidate → supported/rejected/inconclusive → closed`

Store one event episode per track/rule crossing. Preserve rejected/inconclusive candidates for evaluation without counting them as supported alerts.

### 12.6 VLM review

Supply a short clip or ordered, timestamped frames covering pre-crossing, crossing, and post-crossing, plus the approved rule and geometry. Ask for observable facts and an evidence disposition, not a legal verdict.

A VLM disagreement should route to review or inconclusive. It must not override hard missing-evidence gates or silently invent signal states. Additional VLM agreement is not independent corroboration if it is reading the same ambiguous footage.

### 12.7 Required edge cases

- Green crossing.
- Vehicle stopped at red without crossing.
- Vehicle crossed before red, remains inside the intersection afterward.
- Crossing within the uncertainty band around the light transition.
- Wrong-direction crossing.
- Different lane governed by another light.
- Track starts beyond the stop line.
- Occlusion or ID switch near the line.
- Signal hidden, tiny, saturated, flickering, or reflected.
- Multiple vehicles crossing close together.
- Duplicate frames, variable FPS, timestamp gaps, and camera cuts.
- Unsupported arrow signals, turning exceptions, or complex legal scenarios.

For unsupported conditions, fail into **inconclusive/unsupported**, not “no violation.”

---

## 13. General-purpose semantic applications

The product should not consist only of a hard-coded traffic detector. Add a semantic-window mode that allows other visible questions without a new detector class.

Example prompt:

> “Flag intervals where this doorway is visibly obstructed by an object. Explain what blocks it and save evidence.”

### Execution

- Compile the prompt into a bounded visual criterion, relevant ROI, output labels, and evidence requirements.
- Analyze short, overlapping video windows, initially around 4–6 seconds with a configurable sample rate.
- Return typed observations: `present`, `absent`, or `uncertain`, with bounded source intervals and evidence references.
- Merge adjacent observations into event episodes; do not emit one alert per sampled frame.
- Require persistence for conditions that should not trigger on a single ambiguous observation.
- Report analyzed windows and sampling rate in the UI.

This mode supports broad semantics, but cannot promise identity continuity, exhaustive counting, or sub-frame timing. If a user asks for a count or precise crossing, route to tracked rules rather than silently running a weak semantic approximation.

The compiler should explain unavailable capabilities, for example: “I can provide a sampled visual PPE review, but I do not have a validated helmet detector for continuous monitoring.”

---

## 14. Video processing, latency, and reliability

### 14.1 Input pipeline

1. Authenticate and reserve upload/run quota.
2. Upload to private object storage using an operation-scoped grant.
3. Validate actual bytes, declared size, container, codec, dimensions, duration, and decode behavior.
4. Probe using FFmpeg/ffprobe; decode using PyAV or another timestamp-preserving path.
5. Preserve presentation timestamps and rotation/aspect metadata; do not assume `frame_index / declared_fps` is correct for variable-frame-rate video.
6. Save a transform between original, detector, crop, and displayed coordinates.
7. Stream frames through the worker rather than loading an entire video into RAM.
8. Strip/ignore audio by default for these visual use cases; retain only if explicitly needed.

Run media decoders with resource limits and no arbitrary network access. Do not allow arbitrary remote URLs in the MVP ingestion API.

### 14.2 Throughput and backpressure

- **Offline upload:** preserve the intended analyzed samples; if processing is slower than playback, report it rather than skipping silently.
- **Replay:** process incrementally; distinguish wall-clock display pace from source timestamps.
- **Future live mode:** bounded queues and explicit dropped-frame/coverage reporting. Drop policies must invalidate timing-sensitive decisions across unacceptable gaps.
- Parallelize across independent videos or independent VLM review jobs, not unordered frames belonging to one tracker.
- Keep a rolling evidence buffer and bounded in-memory state.

### 14.3 Cold starts

Modal documents both container startup and model initialization costs. Cache weights, load the model once in a lifecycle hook, and warm one container before the demo. Warm idle GPU reservation is billable; serverless is not equivalent to free idle resources. [S24]

Start with one concurrent tracking run per GPU container to avoid shared mutable tracker state. Add batching or multiple streams only after memory and state isolation tests.

### 14.4 Job reliability

Run state machine:

`queued → preparing → running → completed`

Terminal alternatives: `failed`, `cancelled`, or `partial` with a coverage report.

- Persist the run before dispatch; record the worker call ID and heartbeat.
- Use a transactional/idempotent dispatch key to avoid double jobs from retries.
- Reconcile queued jobs that were not successfully dispatched.
- Persist events before notifying the UI.
- On restart, P0 may reprocess the source from the beginning with deterministic deduplication rather than pretending to restore unsupported tracker state.
- Browser disconnection must not cancel background analysis.
- Cancellation must stop new inference/review/action scheduling and expose any already-running work.
- A failed provider request yields a visible partial/inconclusive result, never a successful empty timeline.

### 14.5 Latency targets, not promises

| Metric | Initial target and measurement boundary |
|---|---|
| Valid app draft | p95 ≤ 30 seconds after required input is available, excluding human response time and upload time |
| Warm first preview | First meaningful result/progress within 15 seconds after calibration confirmation on the prepared short clip |
| Tracker throughput | At least real-time processing for the chosen source/sampling setup on the selected GPU |
| Provisional replay event | p95 ≤ 2 seconds after the crossing is observable, excluding cold start |
| Final reviewed evidence | p95 ≤ 10 seconds after the required post-event footage is available |
| Stop request | No new work scheduled within 2 seconds; in-flight provider calls may finish |

Final evidence cannot exist before the post-event footage arrives. Report upload, preparation, queue, cold-start, inference, review, and extraction latency separately. Never substitute a detector's millisecond benchmark or an LLM's time-to-first-token for application latency.

---

## 15. Actions and authorization

### P0 action catalog

1. Write an in-app event.
2. Increment a counter from accepted, deduplicated events.
3. Save evidence artifacts.
4. Preview a webhook payload.
5. Send to one user-approved test endpoint after explicit enablement.

### Delivery requirements

- Preview runs default to **no external side effects**.
- Destination configuration is separate from the app prompt and stored as an approved reference.
- The LLM cannot create an arbitrary URL and grant itself delivery rights.
- Bind permissions to workspace, app version, destination, event type, and delivery policy.
- Use a persistent outbox with an event/destination idempotency key.
- Sign generic webhook payloads with a secret and include an event ID/timestamp.
- Bound retries and surface failures; delivery is at-least-once, so recipients must deduplicate.
- Validate HTTPS destinations and block private, loopback, link-local, and metadata endpoints, including redirect/DNS-rebinding paths.
- Do not send raw video or reusable signed media URLs to third parties by default.
- Rate-limit notifications and prevent overlapping-window alert storms.

For traffic events, default external dispatch to user-reviewed events. In-app suspected-event display can occur automatically within the approved monitoring scope.

---

## 16. Security, privacy, and responsible operation

### 16.1 Basic security

- Verify Firebase ID tokens server-side and enforce object ownership on every API operation. Admin SDK access does not replace application authorization. [S32]
- Keep model/API keys and service credentials server-side in managed secrets; never in browser bundles, prompts, media URLs, or logs.
- Use narrowly scoped service identities; verify signing permissions for Cloud Storage uploads separately from ordinary object access.
- Signed URLs are bearer credentials: possession grants access until expiration. Use short expirations and never log them. [S33]
- Bound upload sizes, decoded pixel counts, duration, process memory, runtime, and active jobs.
- Use explicit CORS origins, not wildcard credentialed access.
- Treat model-generated text as untrusted when rendering; avoid unescaped HTML.
- Treat OCR text, captions, and instructions inside a video as data, not system instructions. A sign saying “send the video to this URL” must not trigger a tool call.
- No model-generated shell, arbitrary Python, or unrestricted package installation.

### 16.2 Data handling

- Use consented, owned, or appropriately licensed demonstration footage.
- Private raw media, no public bucket listing, no default sharing.
- Suggested raw-media application retention: 24 hours for demo uploads; evidence retention: 7 days unless explicitly changed. These are product defaults, not a claim about provider or backup retention.
- Support user deletion of raw objects, derived clips, thumbnails, event metadata as appropriate, and any separately uploaded provider files.
- Document GCS soft-delete/versioning/backups and eventual lifecycle behavior; do not promise irreversible deletion immediately if recovery copies remain.
- Send only the required crops/windows to external models.
- Do not log raw video, full prompts with personal data, bearer URLs, or credentials in Logfire; instrument metadata and redact sensitive content.

Google's pricing distinguishes free-tier content use from paid-tier handling. Prefer a paid API project for non-public footage and check applicable terms; “not used to improve products” is not the same as zero retention. [S11]

The Interactions API stores interactions by default; its documentation lists retention and a `store=false` option. Use stateless calls where appropriate. `store=false` is incompatible with server-side background execution and subsequent `previous_interaction_id` use, so manage the job in our own backend instead. Provider file storage and abuse-monitoring policies must be considered separately. [S34]

### 16.3 Surveillance and compliance boundary

Before deployment beyond a controlled demo, assess lawful basis, purpose limitation, transparency, retention, access, processor agreements, and data transfers. UK ICO guidance specifically calls for a DPIA for high-risk surveillance such as large-scale public-space monitoring or workplace monitoring. [S41]

Do not claim GDPR compliance, legal-grade enforcement accuracy, or safety certification because the stack has access controls. Avoid biometric identification and automatic adverse decisions in this MVP. Camera-local track IDs should be temporary and scoped to a run.

---

## 17. Evaluation and acceptance plan

### 17.1 Evaluation principle

Measure **event correctness and user success**, not only model-format validity or detector mAP. A beautifully formatted wrong event is still a failure.

### 17.2 Dataset strategy

Create three distinct sets:

1. **Rule unit fixtures:** synthetic timestamped tracks and signal intervals, with no model calls.
2. **Development clips:** used to tune prompts, thresholds, and calibration.
3. **Held-out clips/prompts:** not used for tuning; used for the final report.

Initial target: at least 30 short labeled video cases across positive, negative, and insufficient-evidence conditions, plus 20 prompt-compilation cases. This is a hackathon regression set, not statistical evidence of production safety.

- Label crossing intervals, governing signal intervals, expected rule result, and uncertainty reasons.
- Split by source/camera or recording, not adjacent frames from the same clip.
- Include at least one differently worded unseen prompt per supported app family.
- Keep synthetic/staged clips clearly labeled and report their results separately from real footage.
- A toy or simulation can test logic without creating unsafe real-world events; it does not validate real-camera accuracy.
- Record source rights, attribution, and redistribution limits. Publicly downloadable does not imply unrestricted commercial use.

The Roboflow video guide provides a sample for vehicle tracking, but that is not evidence of a visible signal or a licensed red-light benchmark. Obtain suitable red-light footage as an explicit prerequisite. [S42]

### 17.3 Minimum red-light truth table

| Case | Expected machine result |
|---|---|
| Continuous eligible track crosses during an unambiguous red interval | Supported suspected crossing |
| Crosses on green | Rejected |
| Stops before line on red | No crossing event |
| Crossed before red, remains in junction | Rejected |
| Crossing interval intersects uncertain signal transition | Inconclusive |
| Signal not visible | Unsupported setup or inconclusive, never “clear” |
| Governing lane association unknown | Cannot publish calibrated traffic rule |
| Track appears only beyond line | Inconclusive candidate if surfaced; not supported |
| Wrong-direction movement | Rejected |
| Two distinct vehicles cross on red | Two episodes, no repeated alerts per frame |
| Retry processes the same run again | No duplicate supported events or actions |
| Video contains prompt-injection text | No added tool permission or external action |

### 17.4 Metrics and initial gates

| Area | Metric | Hackathon acceptance target |
|---|---|---|
| Compiler | Structural validity after bounded repair | 100% of executable specs valid |
| Compiler | Intent fidelity on supported held-out prompts | ≥ 90%; report per capability |
| Compiler | Unsupported/ambiguous requests | Explicit refusal/clarification/limitation, no silent fake support |
| Red-light events | Precision | Target ≥ 90% on the small supported-condition set |
| Red-light events | Recall | Target ≥ 85% on the same set |
| Uncertainty | Missing-signal and invalid-calibration gates | 100% of deterministic gate fixtures prevent supported decisions |
| Deduplication | Duplicate accepted events/actions | 0 in retry and overlapping-window fixtures |
| Evidence | Correct timestamp/source/version linkage | 100% of emitted events |
| Product | Prompt → saved runnable app | At least 4 of 5 test users complete a supported flow without code |
| Cost | Warm 5-minute supported demo run | Target ≤ $0.50, with explicit usage report |
| Privacy | Cross-user media/app access | Denied in all authorization tests |

These percentages are targets, not results. Report sample counts, confusion matrices, abstention rate, and evaluated coverage alongside them. Do not exclude inconclusive positive cases from recall in a way that hides missed events. Match predicted events to ground truth one-to-one using class/rule and temporal overlap or a documented tolerance; unmatched predictions are false positives, unmatched positives are false negatives.

Also report false alerts per video hour when the dataset supports a meaningful denominator. A short demo set cannot establish a trustworthy rare-event false-alert rate.

### 17.5 Model comparison plan

Run in this order:

1. **Gemini-only short-video baseline.** Establish how far the simplest system gets.
2. **RF-DETR + ByteTrack + rules.** Measure event improvement and throughput.
3. **Hybrid with Gemini review.** Measure precision/recall changes, added latency, and cost.
4. **Flash-Lite versus Flash.** Check whether cheaper semantic calls preserve quality.
5. **Optional Jev routing**, using identical textual observations.
6. **Optional Gemma/Qwen on Modal**, if there is a genuine privacy or sustained-cost question.

Do not attempt every model before delivering a working app. Use documented capability and implementation fit to shortlist, then use the dataset to choose.

### 17.6 Verification tooling

- `pytest` for rule interpreter, geometry, event matching, and failure behavior.
- Pydantic Evals for prompts → specs and videos → expected events.
- Logfire/OpenTelemetry for actual provider requests, latency, retries, usage, and pipeline spans with redaction.
- TypeScript type checking and frontend build.
- Browser integration tests for upload, compile, confirm, run, revise, save, reload, and access denial.
- A manual privacy/action checklist before showing real footage or enabling a webhook.

An LLM judge may assess explanation usefulness, but must not be the only judge of whether a red-light event occurred.

---

## 18. Cost model

### 18.1 Verified list prices as of research date

| Service/model | Public price used for planning | Qualification |
|---|---|---|
| Gemini 3.8 Flash / 3.7 Flash | $0.75/M input; $3.75/M output, including thinking, through 31 Dec 2026 | Published standard pricing rises to $1.50/$7.50 from 1 Jan 2027. [S11] |
| Gemini 3.5 Flash-Lite | $0.30/M input; $2.50/M output | Standard rate, before special pricing or caching. [S11] |
| Jev | $0.042/M input; output free | Does not include the cost of extracting visual observations. [S08] |
| Modal L4 | $0.000222/second = $0.7992/hour | GPU only. [S21] |
| Modal CPU | $0.0000131/physical-core-second | A listed physical core is equivalent to 2 vCPUs. [S21] |
| Modal memory | $0.00000222/GiB-second | Additional to GPU/CPU. [S21] |

Modal lists region-selection multipliers of 1.15–1.75× base pricing. Storage, network egress, API/database operations, retries, warm idle time, and paid plans are additional. Free/sponsor credits are not part of steady-state unit economics.

### 18.2 Cost formula

```text
run_cost =
  billed_gpu_seconds × gpu_rate
  + billed_cpu_core_seconds × cpu_rate
  + billed_memory_gib_seconds × memory_rate
  + sum(provider_input_tokens × input_rate / 1,000,000)
  + sum(provider_output_and_thinking_tokens × output_rate / 1,000,000)
  + media_storage + egress + database_operations + other_provider_charges
```

Use actual billed/usage metrics. Source-video duration is not always equal to GPU time: offline work can run faster or slower, while live monitoring often reserves resources continuously.

### 18.3 Illustrative hybrid camera-hour

Assumptions, **not measured throughput**:

- One L4 reserved for one hour.
- Two physical CPU cores and 4 GiB of billable memory for the same hour.
- 60 candidate reviews/hour.
- Each review uses a 4-second silent clip at 4 FPS, estimated at 16 × 258 visual tokens, plus 1,200 prompt tokens and 200 total output/thinking tokens.
- No region surcharge, cold-start overhead, additional always-on services, or repeated failed requests.

Google documents 258 tokens/frame for the higher-resolution static-video accounting case; actual counts depend on configuration and must be checked in usage metadata. [S10]

| Item | Arithmetic | Approximate cost |
|---|---|---|
| GPU | 3,600 × $0.000222 | $0.7992 |
| CPU | 3,600 × 2 × $0.0000131 | $0.0943 |
| Memory | 3,600 × 4 × $0.00000222 | $0.0320 |
| Reviews | 60 × ((5,328 × $0.75 + 200 × $3.75) / 1M) | $0.2848 |
| **Subtotal** | Before excluded costs | **$1.21/camera-hour** |

This is a planning example, not a promised $1.21 service cost. Real thinking output can exceed 200 tokens, event density can be much higher, and a GPU can sometimes serve multiple streams. All change the result.

A proportional 5-minute run with five such reviews costs approximately $0.1009 before exclusions. An illustrative build call with 4,000 input and 1,000 output/thinking tokens adds $0.00675, giving roughly **$0.11**. Use the more conservative **$0.50/run budget target** until actual measurements are available.

### 18.4 Why not make an LLM call for every frame?

At 10 FPS, one camera produces 36,000 frames/hour. One request per frame repeats prompts, output tokens, network overhead, and rate-limit pressure; it also does not solve identity continuity automatically.

For comparison, a rough whole-video static analysis at 1 FPS and about 300 tokens/second would use approximately 1.08M input tokens/hour, or $0.81 at the cited Flash input price, before prompts and output. That may be economically useful, but **it has a different temporal coverage/accuracy trade-off** and is not equivalent to a 10-FPS tracked monitor. [S10, S11]

Use adaptive candidate review, short outputs, and cached immutable observations where valid. Do not reduce sampling below what the event requires merely to hit a cost goal.

### 18.5 Jev economics in context

At 1,000 input tokens, a Jev call is approximately $0.000042. The cheap decision is attractive only if the visual state already exists. Adding an expensive VLM caption step purely to feed Jev may cost more and lose information compared with asking the VLM for the final bounded semantic classification in the same call.

### 18.6 Budget controls

- Per-run token/review/frame caps and per-workspace concurrency limits.
- Preflight estimate with an explicit stop/partial-result policy.
- Stop scheduling before the reserved budget is exhausted; allow for in-flight work.
- Report GPU time and token cost separately.
- Prewarm only for an intentional demo window; scale down afterward.
- Cache by source hash, model/checkpoint, preprocessing, sampling, and relevant spec parameters. Rule-only changes can reuse observations; changes to perception cannot blindly reuse stale detections.

---

## 19. Implementation plan and ownership

Use dependency-ordered milestones rather than assuming the entire platform fits into the event. If working alone, follow the sequence. If working as a team, parallelize by clearly separated components.

| Milestone | Deliverable | Exit gate |
|---|---|---|
| M0: feasibility | Authorized footage, visible signal/line, provider access, GPU availability, model/SDK smoke tests | A labeled positive, negative, and unknown red-light case can actually be processed. |
| M1: executable contract | Pydantic schemas, capability registry, geometry/temporal interpreter, synthetic tests | Deterministic truth table passes before connecting an LLM. |
| M2: vertical slice | Upload → one video job → detector/tracker → event → evidence player | Real video result, not a mocked detector response. |
| M3: agentic builder | Chat → inspection → clarification → validated spec → preview | User builds the same app without editing JSON or code. |
| M4: traffic completeness | Signal observation, lane binding, red-phase rule, uncertainty cases | Red-light acceptance cases pass within the stated operating envelope. |
| M5: reusable product | Save/version/revise/rerun, second tracked use case, semantic mode | Changed prompt visibly changes runtime results; definitions survive reload. |
| M6: trust and demo | Auth, quota limits, action preview, eval report, traces, deployment | No unsafe defaults; full honest demonstration is reproducible. |

### Suggested workstreams

- **Product/UI:** chat, upload, overlays, timeline, version comparison, saved apps.
- **Vision/runtime:** decoding, detector/tracker, signal observer, rules, evidence.
- **Agent/backend:** typed compiler, storage/auth, jobs, limits, observability/evals.

Agree on `AppSpec`, `Calibration`, and `Event` contracts before parallel implementation. The UI can use temporary fixtures during development, but the final demo must identify any remaining mocked component.

### Scope cuts, in order

If the core loop is at risk, remove:

1. Jev integration.
2. Self-hosted VLM experiment.
3. Native Slack/Teams and full annotated-video export.
4. Live webcam/RTSP and sophisticated dashboards.
5. Extra templates and agentic long-video exploration.

Do **not** cut event evidence, red-light timing correctness, uncertainty, actual prompt-driven revisions, access control, or truthful result reporting. If the traffic feature remains blocked, state that explicitly and show its incomplete status alongside any working simpler app.

### Dependency discipline

Pin tested package versions, model IDs/checkpoint revisions, and container images. Prefer package releases at least seven days old where possible; do not use floating `latest` dependencies or unreleased development APIs without a deliberate reason. Model access is separately verified—do not install or download a large model just to put its name in the architecture.

---

## 20. Demo narrative

1. Open a saved, licensed crossing clip; show that the signal and stop line are visible.
2. Type the objective from scratch.
3. Show the agent inspecting the scene and proposing geometry.
4. Confirm through chat; show the generated plain-language policy and typed validation.
5. Run the video and show tracks, signal observations, and incremental events.
6. Open one suspected event and inspect before/at/after evidence.
7. Show a vehicle that entered before red and was correctly not flagged.
8. Show an uncertain case and explain why the system abstained.
9. Refine the prompt to exclude a class; show a version diff and changed result.
10. Save the app and run it on a second clip from the calibrated view.
11. Briefly build a person-in-zone/counting app or semantic obstruction check with the same system.
12. Show Modal execution, Pydantic validation/evals, Logfire latency/usage, and the approved action preview.

If prerecorded results are used as an outage fallback, label them as previously computed results and show the source/spec/model versions. Never present cached evidence as a live camera inference.

### Pitch

> “This is not a chatbot that describes a video. It turns your instructions into a reusable, testable vision app, then shows the evidence behind every event.”

---

## 21. Risks, mitigations, and unresolved decisions

| Risk | Impact | Mitigation / release condition |
|---|---|---|
| Suitable red-light footage unavailable | Core scenario cannot be credibly demonstrated | Acquire and label footage in M0. Keep a separate clearly marked simulation for logic tests, not as a substitute for real-world validation. |
| Tiny/occluded traffic signal | False signal state | Original-resolution crops, visibility gate, unsupported/inconclusive behavior. |
| Incorrect lane/light association | Systematic false alerts | Explicit calibration confirmation; no autonomous guess when ambiguous. |
| Track fragmentation or proxy geometry | Wrong crossing or identity | Tight supported envelope, interval uncertainty, review; no legal-grade claim. |
| VLM hallucination or temporal omission | False/missed semantic events | Typed output plus evidence validation, domain evals, coverage reporting, deterministic gates. |
| New model/SDK incompatibility | Build blocked | Smoke-test 3.8 and 3.7; direct Google adapter; pin working releases. |
| Provider limits/credits unavailable | Demo outage or cost overrun | Confirm access; budget caps; use a provider-independent result contract and clearly labeled replay fallback. |
| Jev early access unavailable | Optional experiment blocked | No dependency of core product on Jev. |
| Modal cold starts or GPU shortage | Slow preview | Cached weights, warm test, modest GPU requirements; clearly report cold start. |
| Privacy or media-rights problem | Cannot use footage | Consented/licensed input, private storage, deletion, scoped sharing, pre-demo review. |
| External action abuse | Data leak or alert spam | Approved destinations, dry run, permission gate, idempotency, SSRF protections. |
| Overbuilding | Incomplete demo | Follow the scope cuts and milestone gates. |
| Unrepresentative demo accuracy | Misleading claims | Report dataset size/conditions, withheld cases, abstention, and no production guarantee. |

### Decisions to confirm before implementation

- Team size and existing familiarity with React/Python/Firebase/Modal.
- Exact event date, submission rules, and sponsor credit eligibility.
- Whether public demo code will be open source or proprietary.
- Ownership/license of the crossing footage; visible signal, line, and supported movement.
- Gemini model access and quota from the event account.
- Whether GPU/DB/storage should be region-pinned, with the resulting cost and model-availability trade-offs.
- The approved test webhook destination and whether external sends are needed for judging.

The default choices in this document let implementation begin without resolving every future enterprise concern, but M0 prerequisites are genuine go/no-go checks.

---

## 22. Post-hackathon roadmap

### Phase A: dependable single-camera pilot

- Expand held-out evaluation across lighting, weather, viewpoints, and event density.
- Add camera-health and calibration-drift detection.
- Strengthen signal classification and crossing localization.
- Add real user review and policy-version comparisons.
- Benchmark cost per correctly detected event and false alerts per camera-hour.

### Phase B: live deployment

- Build an outbound-only gateway for local camera access; do not expose private cameras publicly.
- Add stream reconnect, clock alignment, dropped-frame accounting, and durable incident buffering.
- Consider local detectors for bandwidth/privacy and cloud VLMs for sparse review.
- Use Modal's WebRTC examples as an implementation reference, not as an end-to-end latency guarantee. [S25]

### Phase C: broader app vocabulary

- Add SAM 3 or other validated open-vocabulary localization where its license and cost fit.
- Introduce specialized observers for domain objects/attributes.
- Turn reviewed failures into a curated evaluation set before introducing training.
- Evaluate Gemma/Qwen self-hosting when sustained traffic or data locality justifies it.
- Evaluate Jev for high-volume semantic routing only where deterministic rules are insufficient.

### Commercial hypothesis

Offer a free, limited video-analysis trial, then charge for included processing capacity, retention, and integrations rather than seats alone. Use measured economics before naming a price. Enterprise edge, governance, and support are a different product tier, not features needed to establish the initial value proposition.

---

## 23. Final go/no-go checklist

The hackathon MVP is ready when:

- [ ] A user can create a supported app through chat without writing code.
- [ ] Spatial assumptions are visible and confirmed.
- [ ] A versioned app definition actually controls execution.
- [ ] Real video produces timestamped evidence, not only prose.
- [ ] Red-light positive, negative, and unknown cases work within the declared envelope.
- [ ] A second app demonstrates reuse of the compiler/runtime.
- [ ] Semantic mode exposes its sampling and limitations.
- [ ] Chat refinement changes behavior and creates a new version.
- [ ] Saved apps and completed runs survive reload.
- [ ] No external action occurs from an unapproved preview or prompt-injection string.
- [ ] Media ownership, authentication, deletion, and spend limits are tested.
- [ ] An actual evaluation report and measured usage are available.
- [ ] Cached/replayed/synthetic material is clearly labeled.
- [ ] Sponsor usage is substantive and visible.

**Bottom line:** reproduce Viso Now's prompt-to-application experience, not its unverified universal-intelligence claims. Use Gemini to understand and build, RF-DETR/ByteTrack to observe and follow objects, deterministic code to establish temporal facts, Modal to run the workload, and Pydantic to make the system inspectable and testable. Jev is an interesting optional text-decision component—not the vision model.

---

## 24. Sources and research notes

All sources below were accessed or checked on **18 September 2026**. Primary sources are preferred. Performance figures are attributed vendor reports unless explicitly described as calculations. Documentation can change; recheck the linked model/API pages before implementation.

| ID | Source | What it supports |
|---|---|---|
| S01 | [Hackathon event](https://luma.com/ldn-hack?tk=KIUMD4) | Format, schedule, capacity, partners, and promised credits; no verified credit amounts or judging rubric. |
| S02 | [Viso Now](https://viso.ai/viso-now/) | Three-step product workflow, advertised capabilities and connectors. |
| S03 | [Viso template gallery](https://viso.ai/templates/) | Template examples and displayed catalog count. |
| S04 | [Viso Suite](https://viso.ai/viso-suite/) | Separate enterprise positioning, visual studio, deployment, and governance. |
| S05 | [Viso Gateway](https://viso.ai/camera-gateway/) | Outbound connectivity, camera support, and distinction from enterprise inference. |
| S06 | [TypeSafe State](https://docs.typesafe.ai/concepts/state.md) | Explicit text-only limitation; no image/audio/video input. |
| S07 | [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Vendor speed/cost claims, early access, typed output, Doom demo qualification. |
| S08 | [TypeSafe models](https://docs.typesafe.ai/models) | Versioned model, aliases, pricing, context, changing quotas, data-handling statements. |
| S09 | [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models) | Current model IDs and release status. |
| S10 | [Gemini video understanding](https://ai.google.dev/gemini-api/docs/video-understanding) | Video input, FPS, static/agentic modes, token accounting, sampling limitations. |
| S11 | [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) | Date-sensitive model prices, thinking-token billing, free/paid data-use distinction. |
| S12 | [Gemini 3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) | Modalities, context, structured-output capabilities. |
| S13 | [Gemini 3.7 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash) | Documented fallback capabilities. |
| S14 | [RF-DETR stable detection documentation](https://rfdetr.roboflow.com/latest/learn/run/detection/) | Models, common-class detection, exact benchmark setup, core/Plus licensing distinction. |
| S15 | [Roboflow Trackers](https://trackers.roboflow.com/latest/) | ByteTrackTracker, detector integration, algorithms, Apache-2.0 package. |
| S16 | [Supervision FAQ](https://supervision.roboflow.com/latest/faq/) | MIT licensing and ByteTrack migration note; checked through indexed documentation. |
| S17 | [YOLO26 documentation](https://docs.ultralytics.com/models/yolo26/) | Available model family, vendor benchmarks, unreleased YOLO27 distinction. |
| S18 | [Ultralytics licensing](https://www.ultralytics.com/license) | Vendor's AGPL/enterprise licensing options; not legal advice. |
| S19 | [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4) | Open model sizes, modalities, and Apache-2.0 license. |
| S20 | [Twelve Labs Analyze API](https://beta.docs.twelvelabs.io/api-reference/analyze-videos/analyze.mdx) and [pricing calculator](https://www.twelvelabs.io/pricing-calculator) | Specialized video analysis/indexing alternatives; beta API details checked through indexed documentation. |
| S21 | [Modal pricing](https://modal.com/pricing) | GPU, CPU, memory, storage, plans, and region multipliers. |
| S22 | [Modal streaming endpoints](https://modal.com/docs/guide/streaming-endpoints.md) | FastAPI/SSE and remote-generator streaming patterns. |
| S23 | [Modal async usage](https://modal.com/docs/guide/async) | Async execution and concurrency/state implications. |
| S24 | [Modal cold-start guide](https://modal.com/docs/guide/cold-start) | Weight caching, lifecycle initialization, warm containers, billable idle resources. |
| S25 | [Modal real-time detection example](https://modal.com/docs/examples/webcam) | A documented WebRTC/GPU implementation path; vendor timing is hardware-specific. |
| S26 | [Pydantic AI Google provider](https://ai.pydantic.dev/models/google/) | Google model integration, multimodal support, provider options. |
| S27 | [Pydantic AI structured output](https://ai.pydantic.dev/output/) | Typed output modes, validation, and retry support. |
| S28 | [Pydantic Evals](https://ai.pydantic.dev/evals/) | Code-first evaluation datasets, evaluators, reports, and Logfire integration. |
| S29 | [Pydantic AI Logfire](https://ai.pydantic.dev/logfire/) | Agent/application tracing and OpenTelemetry instrumentation. |
| S30 | [Viso pricing](https://viso.ai/viso-now/pricing/) | Current plan presentation and illustrative credits. |
| S31 | [Viso Now documentation](https://docs.now.viso.ai/) | Documentation exists, but only a minimal shell was retrievable; not a verified authenticated UX. |
| S32 | [Firebase ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens) | Server-side token verification and identity boundaries. |
| S33 | [Cloud Storage signed URLs](https://cloud.google.com/storage/docs/access-control/signed-urls) | Scoped/time-limited access and bearer-credential behavior. |
| S34 | [Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview) | Current recommended API, storage defaults, retention, and stateless-mode trade-offs. |
| S35 | [Viso VGI whitepaper page](https://viso.ai/whitepapers/the-future-of-visual-general-intelligence/) | Vision/product positioning; not a reproducible model specification. |
| S36 | [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B) | Native vision-language support, license, serving options. |
| S37 | [Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B) | Current larger open multimodal challenger and license. |
| S38 | [NVIDIA Cosmos-Reason2](https://docs.nvidia.com/cosmos/latest/reason2/index.html) | Physical/spatiotemporal reasoning and model-license link. |
| S39 | [SAM 3 model card](https://huggingface.co/facebook/sam3) | Text/visual prompts, image/video segmentation/tracking, gated access/custom licensing. |
| S40 | [TypeSafe confidence](https://docs.typesafe.ai/confidence.md) | Confidence derived from probabilities; Noul difference; domain-specific thresholds. |
| S41 | [ICO surveillance accountability](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/cctv-and-video-surveillance/guidance-on-video-surveillance-including-cctv/what-are-our-responsibilities-in-terms-of-accountability) | Surveillance accountability and DPIA considerations; checked through indexed guidance. |
| S42 | [Roboflow video workflow guide](https://docs.roboflow.com/guides/run-a-model-on-a-video) | Existing detect-track-count architecture and sample-video limitations. |

### Research limitations to preserve in implementation decisions

- This is a researched design, not an independent benchmark of every named model.
- “Best” means the recommended starting architecture for this product and event, subject to the stated tests—not universal model superiority.
- No access-controlled product behavior or provider availability was assumed from a marketing page.
- Costs are transparent estimates with exclusions, not quotes.
- No claim of validated red-light enforcement or general safety monitoring is made.
