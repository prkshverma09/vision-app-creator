"""Mutable-free state containers for the rule reducer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vision_app.contracts.models import CrossingBracket, PointN, TimeRange


@dataclass(frozen=True, slots=True)
class CrossingEpisode:
    episode_id: str
    track_id: str
    bracket: CrossingBracket
    predicted_in_bracket: bool = False
    facts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ZoneEpisode:
    episode_id: str
    track_id: str
    persistence: TimeRange
    facts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TrackState:
    last_anchor: PointN | None = None
    last_time_ms: int | None = None
    confirmed_side: int | None = None
    last_pre_time_ms: int | None = None
    last_pre_predicted: bool = False
    last_post_time_ms: int | None = None
    episodes: list[Any] = field(default_factory=list)
    zone_inside: bool | None = None
    zone_entry_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RuleState:
    tracks: dict[str, TrackState] = field(default_factory=dict)
