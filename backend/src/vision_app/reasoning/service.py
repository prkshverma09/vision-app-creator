"""Bounded orchestration around the VisualReasoner port."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from vision_app.contracts.models import RuleCandidate, SemanticObservation, SourceTimeMs, TimeRange
from vision_app.contracts.ports import VisualReasoner
from vision_app.rules.intervals import merge_time_ranges

from .models import CandidateReview, ReviewDisposition, SemanticAnalysis, SemanticEpisode


class CandidateReasoner(Protocol):
    async def review_candidate(self, prompt: str, *, evidence_refs: list[str]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReasoningBudget:
    max_calls: int
    timeout_ms: int

    def __post_init__(self) -> None:
        if self.max_calls < 0:
            raise ValueError("max_calls must be nonnegative")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")


class SemanticReasoningService:
    """Schedules finite source windows, validates facts, and deterministically merges episodes."""

    def __init__(self, reasoner: VisualReasoner, budget: ReasoningBudget) -> None:
        self._reasoner = reasoner
        self._budget = budget

    async def _bounded(self, awaitable: Any) -> Any:
        return await asyncio.wait_for(awaitable, timeout=self._budget.timeout_ms / 1000)

    @staticmethod
    def _windows(source_range: TimeRange, window_ms: int, stride_ms: int) -> list[TimeRange]:
        if window_ms <= 0 or stride_ms <= 0:
            raise ValueError("window_ms and stride_ms must be positive")
        start = source_range.start_ms.root
        end = source_range.end_ms.root
        result: list[TimeRange] = []
        while start < end:
            result.append(TimeRange(start_ms=SourceTimeMs(start), end_ms=SourceTimeMs(min(start + window_ms, end))))
            start += stride_ms
        return result

    @staticmethod
    def _validate(observation: SemanticObservation, requested: TimeRange, condition_id: str) -> None:
        if observation.requested_range != requested:
            raise ValueError("reasoner requested range does not match bounded request")
        if observation.condition_id.root != condition_id:
            raise ValueError("reasoner condition does not match request")
        if not observation.evidence_refs:
            raise ValueError("semantic observation requires factual evidence references")
        for item in observation.observed_ranges:
            if (item.start_ms.root < requested.start_ms.root or item.end_ms.root > requested.end_ms.root):
                raise ValueError("observed range outside requested window")
        if observation.decision != "present" and observation.observed_ranges:
            raise ValueError("only present observations may contain observed ranges")

    async def analyze(
        self, *, source_id: str, condition_id: str, prompt: str, source_range: TimeRange,
        window_ms: int, stride_ms: int,
    ) -> SemanticAnalysis:
        windows = self._windows(source_range, window_ms, stride_ms)
        observations: list[SemanticObservation] = []
        unknown: list[TimeRange] = []
        for index, window in enumerate(windows):
            if index >= self._budget.max_calls:
                unknown.extend(windows[index:])
                break
            try:
                obs = await self._bounded(self._reasoner.classify(
                    source_id, window.start_ms.root, window.end_ms.root, prompt
                ))
            except (TimeoutError, asyncio.TimeoutError):
                unknown.append(window)
                continue
            self._validate(obs, window, condition_id)
            observations.append(obs)
            if obs.decision == "uncertain":
                unknown.append(window)

        present_ranges = [item for obs in observations if obs.decision == "present" for item in obs.observed_ranges]
        merged = merge_time_ranges(present_ranges, max_gap_ms=0)
        episodes: list[SemanticEpisode] = []
        for item in merged:
            refs = sorted({ref.root for obs in observations if obs.decision == "present"
                           for observed in obs.observed_ranges
                           if observed.start_ms.root < item.end_ms.root and observed.end_ms.root > item.start_ms.root
                           for ref in obs.evidence_refs})
            episodes.append(SemanticEpisode(condition_id=condition_id, source_range=item, evidence_refs=tuple(refs)))

        if unknown:
            disposition = ReviewDisposition.PARTIAL
        elif episodes:
            disposition = ReviewDisposition.PRESENT
        elif observations and all(obs.decision == "absent" for obs in observations):
            disposition = ReviewDisposition.ABSENT
        else:
            disposition = ReviewDisposition.UNCERTAIN
        return SemanticAnalysis(
            disposition=disposition, episodes=tuple(episodes), observations=tuple(observations),
            unknown_ranges=tuple(merge_time_ranges(unknown)), requested_windows=len(windows),
            completed_windows=len(observations),
        )

    async def review_candidates(self, candidates: list[RuleCandidate], *, prompt: str) -> list[CandidateReview]:
        reviewer = self._reasoner
        if not hasattr(reviewer, "review_candidate"):
            return [CandidateReview(c, ReviewDisposition.PARTIAL, "review unavailable", True) for c in candidates]
        results: list[CandidateReview] = []
        for index, candidate in enumerate(candidates):
            if index >= self._budget.max_calls:
                results.append(CandidateReview(candidate, ReviewDisposition.PARTIAL, "review budget exhausted", True))
                continue
            try:
                raw = await self._bounded(reviewer.review_candidate(prompt, evidence_refs=candidate.fact_refs))
                agreement = raw.get("agreement", "inconclusive")
                review = {"agree": ReviewDisposition.PRESENT, "disagree": ReviewDisposition.ABSENT}.get(
                    agreement, ReviewDisposition.UNCERTAIN
                )
                reason = str(raw.get("reason", ""))
            except (TimeoutError, asyncio.TimeoutError):
                review, reason = ReviewDisposition.PARTIAL, "review timed out"
            # Reviews are annotations only. Deterministic signal/geometry gates remain authoritative.
            results.append(CandidateReview(candidate, review, reason, candidate.disposition != "supported"))
        return results
