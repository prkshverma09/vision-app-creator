from __future__ import annotations

from collections.abc import Sequence

import pytest

from vision_app.contracts.models import (
    CrossingBracket,
    ModelInvocationMetadata,
    MoneyMicrousd,
    ResourceId,
    RuleCandidate,
    SemanticObservation,
    SourceTimeMs,
    TimeRange,
)
from vision_app.reasoning import (
    ReasoningBudget,
    ReviewDisposition,
    ScriptedVisualReasoner,
    SemanticReasoningService,
)


def span(start: int, end: int) -> TimeRange:
    return TimeRange(start_ms=SourceTimeMs(start), end_ms=SourceTimeMs(end))


def observation(
    start: int,
    end: int,
    decision: str,
    observed: Sequence[tuple[int, int]],
    *,
    evidence: Sequence[str] = ("clip-1",),
) -> SemanticObservation:
    return SemanticObservation(
        condition_id=ResourceId("blocked-exit"),
        decision=decision,
        requested_range=span(start, end),
        observed_ranges=[span(a, b) for a, b in observed],
        evidence_refs=[ResourceId(item) for item in evidence],
        invocation=ModelInvocationMetadata(
            provider="scripted",
            model="fake",
            revision="test",
            prompt_hash="fixture",
            input_tokens=0,
            output_tokens=0,
            duration_ms=0,
            retry_count=0,
            adapter_mode="scripted",
            estimated_cost=MoneyMicrousd(0),
        ),
    )


@pytest.mark.asyncio
async def test_missing_signal_candidate_cannot_be_upgraded_by_agreeing_vlm() -> None:
    reasoner = ScriptedVisualReasoner(reviews=[{"agreement": "agree", "reason": "crossing visible"}])
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=1, timeout_ms=100))
    candidate = RuleCandidate(
        rule_id=ResourceId("red-crossing"),
        episode_id="episode-1",
        crossing=CrossingBracket(last_pre_ms=SourceTimeMs(100), first_post_ms=SourceTimeMs(200)),
        persistence=None,
        fact_refs=["crossing:100:200", "signal:no_red_interval"],
        disposition="rejected",
    )

    reviewed = await service.review_candidates([candidate], prompt="Did it cross on red?")

    assert reviewed[0].review == ReviewDisposition.PRESENT
    assert reviewed[0].candidate.disposition == "rejected"
    assert reviewed[0].hard_gate_preserved is True


@pytest.mark.asyncio
async def test_overlapping_windows_merge_without_duplicate_incidents() -> None:
    reasoner = ScriptedVisualReasoner(classifications=[
        observation(0, 1_000, "present", [(700, 1_000)], evidence=("clip-a",)),
        observation(500, 1_500, "present", [(700, 1_200)], evidence=("clip-b",)),
        observation(1_000, 2_000, "absent", [], evidence=("clip-c",)),
    ])
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=3, timeout_ms=100))

    result = await service.analyze(
        source_id="source-1", condition_id="blocked-exit", prompt="Is exit blocked?",
        source_range=span(0, 2_000), window_ms=1_000, stride_ms=500,
    )

    assert [(e.source_range.start_ms.root, e.source_range.end_ms.root) for e in result.episodes] == [(700, 1_200)]
    assert result.episodes[0].evidence_refs == ("clip-a", "clip-b")


@pytest.mark.asyncio
async def test_unknown_span_is_not_bridged_when_merging_episodes() -> None:
    reasoner = ScriptedVisualReasoner(classifications=[
        observation(0, 1_000, "present", [(100, 400)], evidence=("clip-a",)),
        observation(1_000, 2_000, "uncertain", [], evidence=("clip-unknown",)),
        observation(2_000, 3_000, "present", [(2_100, 2_400)], evidence=("clip-b",)),
    ])
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=3, timeout_ms=100))

    result = await service.analyze(
        source_id="source-1", condition_id="blocked-exit", prompt="Is exit blocked?",
        source_range=span(0, 3_000), window_ms=1_000, stride_ms=1_000,
    )

    assert [(e.source_range.start_ms.root, e.source_range.end_ms.root) for e in result.episodes] == [(100, 400), (2_100, 2_400)]
    assert result.disposition == ReviewDisposition.PARTIAL


@pytest.mark.asyncio
async def test_out_of_window_provider_evidence_is_rejected() -> None:
    reasoner = ScriptedVisualReasoner(classifications=[
        observation(0, 1_000, "present", [(900, 1_100)]),
    ])
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=1, timeout_ms=100))

    with pytest.raises(ValueError, match="outside requested window"):
        await service.analyze(
            source_id="source-1", condition_id="blocked-exit", prompt="blocked?",
            source_range=span(0, 1_000), window_ms=1_000, stride_ms=1_000,
        )


@pytest.mark.asyncio
async def test_budget_limited_review_queue_is_honestly_partial() -> None:
    candidates = [
        RuleCandidate(rule_id=ResourceId("line"), episode_id=f"ep-{i}", crossing=None,
                      persistence=span(i * 10 + 1, i * 10 + 2), fact_refs=[f"track:{i}"], disposition="candidate")
        for i in range(3)
    ]
    reasoner = ScriptedVisualReasoner(reviews=[{"agreement": "agree", "reason": "visible"}])
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=1, timeout_ms=100))

    reviewed = await service.review_candidates(candidates, prompt="review")

    assert [item.review for item in reviewed] == [ReviewDisposition.PRESENT, ReviewDisposition.PARTIAL, ReviewDisposition.PARTIAL]
    assert reasoner.review_calls == 1


@pytest.mark.asyncio
async def test_timeout_becomes_partial_not_false_absence() -> None:
    reasoner = ScriptedVisualReasoner(classifications=[observation(0, 1_000, "absent", [])], delay_ms=50)
    service = SemanticReasoningService(reasoner, ReasoningBudget(max_calls=1, timeout_ms=1))

    result = await service.analyze(
        source_id="source-1", condition_id="blocked-exit", prompt="blocked?",
        source_range=span(0, 1_000), window_ms=1_000, stride_ms=1_000,
    )

    assert result.disposition == ReviewDisposition.PARTIAL
    assert result.completed_windows == 0
    assert result.unknown_ranges == (span(0, 1_000),)
