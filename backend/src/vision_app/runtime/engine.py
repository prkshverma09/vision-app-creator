"""Ordered runtime engine that composes perception, rules, reasoning and evidence."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Iterator, cast

from vision_app.contracts.models import (
    Calibration,
    CrossingBracket,
    DecodedFrame,
    Event,
    EvidenceManifest,
    FrameRef,
    MoneyMicrousd,
    ResourceId,
    RuleCandidate,
    RunProgress,
    SignalInterval,
    SourceTimeMs,
    TimeRange,
    TrackedRule,
    TrackedRulesSpec,
    SemanticWindowsSpec,
)
from vision_app.contracts.ports import (
    BudgetLedger,
    Detector,
    EventSink,
    IdFactory,
    SignalObserver,
    TraceSink,
    TrackerFactory,
    VideoDecoder,
)
from vision_app.evidence.extractor import EvidenceExtractor, EvidenceRequest
from vision_app.operations.limits import LimitGuard
from vision_app.operations.tracing import InMemoryTraceSink, SafeTraceSink
from vision_app.operations.usage import UsageAggregator
from vision_app.perception.signal.intervals import ConfirmedSignalIntervals
from vision_app.reasoning import SemanticReasoningService
from vision_app.rules.config import LineRuleConfig, ZoneRuleConfig
from vision_app.rules.reducer import apply_observations, flush
from vision_app.rules.state import RuleState

from .context import RunContext


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single attempt."""

    phase: str
    progress: RunProgress
    usage: UsageAggregator
    events: dict[str, Event]


def _make_progress(
    ctx: RunContext,
    phase: str,
    processed_ranges: list[TimeRange],
    requested_samples: int,
    processed_samples: int,
    cancel_requested: bool,
    usage: UsageAggregator,
    sequence: int,
) -> RunProgress:
    """Build a progress update; ``phase`` is validated at runtime, not by mypy."""
    return RunProgress(
        run_id=ctx.run_id,
        attempt_id=ctx.attempt_id,
        phase=phase,  # type: ignore[arg-type]
        processed_ranges=processed_ranges,
        requested_samples=requested_samples,
        processed_samples=processed_samples,
        review_backlog=0,
        cancel_requested=cancel_requested,
        usage=MoneyMicrousd(usage.snapshot().measured_microusd),
        sequence=sequence,
    )


class EngineRuntimeError(RuntimeError):  # noqa: N818
    """Runtime-level error that prevents completion."""


def _line_rule(rule: TrackedRule, calibration: Calibration) -> LineRuleConfig:
    line_points = list(calibration.lines.get(rule.rule_id.root, []))
    if len(line_points) != 2:
        # Fall back to the first configured line when the rule id is not mapped.
        for pts in calibration.lines.values():
            if len(pts) == 2:
                line_points = list(pts)
                break
    if len(line_points) != 2:
        raise EngineRuntimeError(f"no usable line for rule {rule.rule_id.root}")
    return LineRuleConfig(
        rule_id=rule.rule_id.root,
        capability_id=rule.capability_id,
        object_classes=tuple(rule.object_classes),
        line=(line_points[0], line_points[1]),
        # Calibrated lines are directed so that the approach side is +1 and
        # the far side is -1 (see component rules tests for this convention).
        valid_from_side=1,
        valid_to_side=-1,
    )


def _zone_rule(rule: TrackedRule, calibration: Calibration) -> ZoneRuleConfig:
    polygon = tuple(calibration.lanes.get(rule.rule_id.root, []))
    if len(polygon) < 3:
        for pts in calibration.lanes.values():
            if len(pts) >= 3:
                polygon = tuple(pts)
                break
    if len(polygon) < 3:
        raise EngineRuntimeError(f"no usable zone polygon for rule {rule.rule_id.root}")
    return ZoneRuleConfig(
        rule_id=rule.rule_id.root,
        capability_id=rule.capability_id,
        object_classes=tuple(rule.object_classes),
        polygon=polygon,
    )


def _rule_config(rule: TrackedRule, calibration: Calibration) -> LineRuleConfig | ZoneRuleConfig:
    if rule.capability_id in {"tracked.line_crossing", "tracked.red_phase_crossing"}:
        return _line_rule(rule, calibration)
    if rule.capability_id == "tracked.person_in_zone":
        return _zone_rule(rule, calibration)
    raise EngineRuntimeError(f"unsupported tracked capability: {rule.capability_id}")


def _frame_interval_ms(frame: FrameRef, duration_ms: int) -> int:
    """Conservative frame duration used for coverage ranges."""
    # Prefer a fixed small quantum; do not claim certainty beyond the next frame.
    return max(1, min(100, duration_ms - frame.source_time_ms.root))


class RunEngine:
    """Composes decoder -> detector -> tracker -> signal -> rules -> review -> evidence."""

    def __init__(
        self,
        *,
        decoder: VideoDecoder,
        detector: Detector,
        tracker_factory: TrackerFactory,
        signal_observer: SignalObserver | None = None,
        reasoner: SemanticReasoningService | None = None,
        evidence_extractor: EvidenceExtractor | None = None,
        ledger: BudgetLedger | None = None,
        event_sink: EventSink,
        trace_sink: TraceSink | None = None,
        id_factory: IdFactory,
        max_review_queue: int = 2,
    ) -> None:
        self._decoder = decoder
        self._detector = detector
        self._tracker_factory = tracker_factory
        self._signal_observer = signal_observer
        self._reasoner = reasoner
        self._evidence = evidence_extractor
        self._ledger = ledger
        self._sink = event_sink
        self._trace = SafeTraceSink(trace_sink or InMemoryTraceSink())
        self._ids = id_factory
        self._max_review_queue = max(1, max_review_queue)

    async def run(
        self,
        ctx: RunContext,
        fence: int,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> RunResult:
        self._trace.record(
            "runtime.run.started",
            {
                "run_id": ctx.run_id.root,
                "attempt_id": ctx.attempt_id.root,
                "source_id": ctx.source_id.root,
            },
        )

        guard = LimitGuard(ctx.limits)
        usage = UsageAggregator()
        reservation_id: str | None = None
        if self._ledger is not None:
            reservation_id = await self._ledger.reserve(ctx.owner_id, 1000)
            usage.record_call(estimated_microusd=1000, measured_microusd=0)

        probe = self._decoder.probe(ctx.source_path_str)
        duration_ms = int(getattr(probe, "duration_ms", 0))
        requested_samples = int(getattr(probe, "frame_count", 0) or 0)

        tracker = self._tracker_factory.create(ctx.attempt_id.root)
        rule_states: dict[str, RuleState] = {}
        rule_configs: list[tuple[TrackedRule, LineRuleConfig | ZoneRuleConfig]] = []
        signal_intervals: dict[str, ConfirmedSignalIntervals] = {}

        if isinstance(ctx.spec, TrackedRulesSpec):
            if ctx.calibration is None:
                raise EngineRuntimeError("tracked rules require a calibration")
            for rule in ctx.spec.rules:
                cfg = _rule_config(rule, ctx.calibration)
                rule_states[rule.rule_id.root] = RuleState()
                rule_configs.append((rule, cfg))
            for rule_id, roi_id in (ctx.calibration.governing_signals or {}).items():
                signal_intervals[roi_id] = ConfirmedSignalIntervals(stability_ms=0)
        elif isinstance(ctx.spec, SemanticWindowsSpec):
            raise EngineRuntimeError("semantic windows are not yet implemented in the runtime engine")
        else:
            raise EngineRuntimeError(f"unsupported spec kind: {type(ctx.spec)}")

        events: dict[str, Event] = {}
        processed_samples = 0
        sequence = 0
        phase = "running"
        last_source_ms = 0

        try:
            frames = self._decoder.decode(ctx.source_path_str)
            frame_iter = cast(Iterator[DecodedFrame], frames)
            for frame in frame_iter:
                if is_cancelled():
                    phase = "cancelled"
                    if hasattr(frame_iter, "close"):
                        frame_iter.close()
                    break

                guard.consume_frames(1)
                processed_samples += 1
                source_ms = frame.frame_ref.source_time_ms.root
                last_source_ms = source_ms

                batch = await self._detector.detect(frame)
                if batch.invocation:
                    invocation = batch.invocation
                else:
                    invocation = None
                usage.record_call(
                    estimated_microusd=invocation.estimated_cost.root if invocation else 0,
                    measured_microusd=0,
                    input_tokens=invocation.input_tokens if invocation else 0,
                    output_tokens=invocation.output_tokens if invocation else 0,
                )

                observations = list(tracker.update(batch))

                if self._signal_observer is not None and ctx.calibration is not None:
                    for roi_id in signal_intervals:
                        obs = self._signal_observer.observe(frame, roi_id)
                        signal_intervals[roi_id].update(obs)

                for rule, cfg in rule_configs:
                    rule_states[rule.rule_id.root] = apply_observations(
                        cfg, observations, rule_states[rule.rule_id.root]
                    )

                if processed_samples % 10 == 0 or duration_ms == 0:
                    end_ms = min(
                        source_ms + _frame_interval_ms(frame.frame_ref, duration_ms), duration_ms
                    )
                    progress = _make_progress(
                        ctx=ctx,
                        phase="running",
                        processed_ranges=[
                            TimeRange(
                                start_ms=SourceTimeMs(last_source_ms),
                                end_ms=SourceTimeMs(end_ms),
                            )
                        ],
                        requested_samples=max(requested_samples, processed_samples),
                        processed_samples=processed_samples,
                        cancel_requested=False,
                        usage=usage,
                        sequence=sequence,
                    )
                    await self._sink.progress(progress, fence)
                    sequence += 1

            if phase != "cancelled":
                phase = "completed"
                # Source-end flush of signal intervals.
                final_red: list[SignalInterval] = []
                end_time_ms = duration_ms or last_source_ms + 100
                for roi_id, intervals in signal_intervals.items():
                    # Only confirmed red intervals gate red-phase candidates.
                    final_red.extend(
                        interval
                        for interval in intervals.flush(end_time_ms)
                        if interval.state == "red"
                    )

                # Flush rule candidates.
                for rule, cfg in rule_configs:
                    candidates = flush(rule_states[cfg.rule_id], cfg, end_time_ms, final_red)
                    for candidate in candidates:
                        if candidate.disposition not in {"supported", "inconclusive"}:
                            continue
                        event = await self._emit_event(ctx, cfg, candidate, fence)
                        events[event.id.root] = event

                # Bounded review queue for semantic/candidate reviews.
                if self._reasoner is not None and ctx.review_prompt:
                    await self._run_reviews(ctx, events, fence, is_cancelled)

        except Exception as exc:
            phase = "failed"
            self._trace.record(
                "runtime.run.failed",
                {"run_id": ctx.run_id.root, "error": type(exc).__name__},
            )
            raise
        finally:
            tracker.close()
            if self._ledger is not None and reservation_id is not None:
                try:
                    await self._ledger.settle(reservation_id, usage.snapshot().measured_microusd)
                except Exception:
                    pass

        coverage_end = duration_ms if phase == "completed" else last_source_ms
        if coverage_end == 0:
            coverage_end = duration_ms or last_source_ms + 100

        self._trace.record(
            "runtime.run.finished",
            {
                "run_id": ctx.run_id.root,
                "phase": phase,
                "events": len(events),
                "processed_samples": processed_samples,
            },
        )

        progress = _make_progress(
            ctx=ctx,
            phase=phase,
            processed_ranges=[TimeRange(start_ms=SourceTimeMs(0), end_ms=SourceTimeMs(coverage_end))],
            requested_samples=max(requested_samples, processed_samples),
            processed_samples=processed_samples,
            cancel_requested=phase == "cancelled",
            usage=usage,
            sequence=sequence,
        )
        await self._sink.progress(progress, fence)
        return RunResult(phase=phase, progress=progress, usage=usage, events=events)

    async def _emit_event(
        self,
        ctx: RunContext,
        cfg: LineRuleConfig | ZoneRuleConfig,
        candidate: RuleCandidate,
        fence: int,
    ) -> Event:
        source_range = self._candidate_range(candidate)
        event_id = ResourceId(self._ids.new("event"))
        track_refs = [ref.split(":", 1)[1] for ref in candidate.fact_refs if ref.startswith("track:")]
        event = Event(
            id=event_id,
            run_id=ctx.run_id,
            attempt_id=ctx.attempt_id,
            spec_version_id=ctx.spec_version_id,
            calibration_id=ctx.calibration.id if ctx.calibration else None,
            source_range=source_range,
            rule_id=candidate.rule_id,
            track_refs=track_refs,
            facts={"episode_id": candidate.episode_id, "disposition": candidate.disposition},
            evidence=EvidenceManifest(
                requested_range=source_range,
                actual_range=None,
                state="pending",
            ),
            machine_decision=candidate.disposition,
            human_review="unreviewed",
            revision=0,
        )

        if self._evidence is not None:
            try:
                request = EvidenceRequest(
                    owner_id=ctx.owner_id,
                    source_id=ctx.source_id,
                    storage_ref=ctx.storage_ref,
                    source_generation=ctx.source_generation,
                    source_sha256=ctx.source_sha256,
                    source_path=ctx.source_path_str,
                    event_range=source_range,
                    attempt_id=ctx.attempt_id.root,
                    policy=ctx.evidence_policy,
                )
                result = await self._evidence.build(request)
                event = await self._evidence.publish(event, result, self._sink, fence)
            except Exception as exc:
                self._trace.record(
                    "runtime.evidence.failed",
                    {"event_id": event.id.root, "error": type(exc).__name__},
                )
                event = event.model_copy(
                    update={
                        "evidence": EvidenceManifest(
                            requested_range=source_range,
                            actual_range=None,
                            state="failed",
                        )
                    }
                )
                await self._sink.upsert(event, fence)
        else:
            await self._sink.upsert(event, fence)

        return event

    async def _run_reviews(
        self,
        ctx: RunContext,
        events: dict[str, Event],
        fence: int,
        is_cancelled: Callable[[], bool],
    ) -> None:
        reasoner = self._reasoner
        review_prompt = ctx.review_prompt
        assert reasoner is not None and review_prompt is not None
        sem = asyncio.Semaphore(self._max_review_queue)
        tasks: list[asyncio.Task[Any]] = []

        async def review_one(event: Event, candidate: RuleCandidate) -> None:
            async with sem:
                if is_cancelled():
                    return
                reviews = await reasoner.review_candidates(
                    [candidate], prompt=review_prompt
                )
                for review in reviews:
                    facts = dict(event.facts)
                    facts["review"] = review.review.value
                    facts["review_reason"] = review.reason
                    updated = event.model_copy(update={"facts": facts})
                    await self._sink.upsert(updated, fence)
                    events[event.id.root] = updated

        for event in list(events.values()):
            if is_cancelled():
                break
            # Reconstruct a candidate stub for review.
            candidate = RuleCandidate(
                rule_id=event.rule_id,
                episode_id=event.facts.get("episode_id", event.id.root),
                crossing=CrossingBracket(
                    last_pre_ms=SourceTimeMs(event.source_range.start_ms.root),
                    first_post_ms=SourceTimeMs(event.source_range.end_ms.root),
                ),
                persistence=None,
                fact_refs=[f"track:{ref}" for ref in event.track_refs],
                disposition=event.machine_decision,
            )
            tasks.append(asyncio.create_task(review_one(event, candidate)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _candidate_range(candidate: RuleCandidate) -> TimeRange:
        if candidate.crossing is not None:
            return TimeRange(
                start_ms=SourceTimeMs(candidate.crossing.last_pre_ms.root),
                end_ms=SourceTimeMs(candidate.crossing.first_post_ms.root),
            )
        if candidate.persistence is not None:
            return candidate.persistence
        raise EngineRuntimeError("candidate has neither crossing nor persistence")
