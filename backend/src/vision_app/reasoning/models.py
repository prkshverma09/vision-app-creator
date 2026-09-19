"""Typed results for bounded semantic analysis and optional candidate review."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vision_app.contracts.models import RuleCandidate, SemanticObservation, TimeRange


class ReviewDisposition(StrEnum):
    """What a bounded visual review established; partial means work was not completed."""

    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"
    PARTIAL = "partial"


@dataclass(frozen=True)
class SemanticEpisode:
    condition_id: str
    source_range: TimeRange
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class SemanticAnalysis:
    disposition: ReviewDisposition
    episodes: tuple[SemanticEpisode, ...]
    observations: tuple[SemanticObservation, ...]
    unknown_ranges: tuple[TimeRange, ...]
    requested_windows: int
    completed_windows: int


@dataclass(frozen=True)
class CandidateReview:
    candidate: RuleCandidate
    review: ReviewDisposition
    reason: str
    hard_gate_preserved: bool
