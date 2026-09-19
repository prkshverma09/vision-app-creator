"""Ordered state reducer for tracked rules."""
from __future__ import annotations

from collections.abc import Sequence

from vision_app.contracts.models import (
    CrossingBracket,
    QualityFlag,
    ResourceId,
    RuleCandidate,
    SignalInterval,
    SourceTimeMs,
    TimeRange,
    TrackObservation,
)
from vision_app.geometry.polygons import BoundaryPolicy, point_in_polygon

from .anchor import AnchorPolicy, box_anchor
from .config import LineRuleConfig, ZoneRuleConfig
from .disposition import line_crossing_disposition, red_phase_disposition
from .geometry import is_valid_crossing, line_side
from .ids import episode_id
from .intervals import merge_time_ranges
from .state import CrossingEpisode, RuleState, TrackState, ZoneEpisode

RuleConfig = LineRuleConfig | ZoneRuleConfig


def _line_track_state(
    ts: TrackState,
    rule: LineRuleConfig,
    obs: TrackObservation,
) -> TrackState:
    time_ms = obs.frame_ref.source_time_ms.root
    anchor = box_anchor(obs.box, rule.anchor_policy)
    side = line_side(anchor, rule.line, rule.band_width)

    predicted = not obs.observed or QualityFlag.PREDICTED_ONLY in obs.quality.flags

    # A gap invalidates the continuity of the current approach/crossing state.
    if ts.last_time_ms is not None and time_ms - ts.last_time_ms > rule.max_gap_ms:
        ts = TrackState(last_anchor=anchor, last_time_ms=time_ms)

    new_confirmed_side = ts.confirmed_side
    new_last_pre = ts.last_pre_time_ms
    new_last_pre_predicted = ts.last_pre_predicted
    new_last_post = ts.last_post_time_ms
    new_episodes = list(ts.episodes)

    if side == 0:
        # Dead band: keep the previously confirmed side, only update timestamp.
        return TrackState(
            last_anchor=anchor,
            last_time_ms=time_ms,
            confirmed_side=new_confirmed_side,
            last_pre_time_ms=new_last_pre,
            last_pre_predicted=new_last_pre_predicted,
            last_post_time_ms=new_last_post,
            episodes=new_episodes,
        )

    if ts.confirmed_side is None or side == ts.confirmed_side:
        new_confirmed_side = side
        if side == rule.valid_from_side:
            new_last_pre = time_ms
            new_last_pre_predicted = predicted
        if side == rule.valid_to_side:
            new_last_post = time_ms
        return TrackState(
            last_anchor=anchor,
            last_time_ms=time_ms,
            confirmed_side=new_confirmed_side,
            last_pre_time_ms=new_last_pre,
            last_pre_predicted=new_last_pre_predicted,
            last_post_time_ms=new_last_post,
            episodes=new_episodes,
        )

    # Side change: either a valid crossing or a reversed one.
    if is_valid_crossing(ts.confirmed_side, side, rule.valid_from_side, rule.valid_to_side):
        if ts.last_pre_time_ms is None:
            # No pre-side observation to anchor the bracket.
            last_pre = time_ms
            pre_predicted = predicted
        else:
            last_pre = ts.last_pre_time_ms
            pre_predicted = ts.last_pre_predicted

        bracket = CrossingBracket(
            last_pre_ms=SourceTimeMs(last_pre),
            first_post_ms=SourceTimeMs(time_ms),
        )
        ep = CrossingEpisode(
            episode_id=episode_id(
                rule.rule_id,
                obs.track_id,
                "crossing",
                bracket.last_pre_ms.root,
                bracket.first_post_ms.root,
            ),
            track_id=obs.track_id,
            bracket=bracket,
            predicted_in_bracket=pre_predicted or predicted,
        )
        new_episodes.append(ep)
        new_confirmed_side = side
        new_last_post = time_ms
        new_last_pre = None
        new_last_pre_predicted = False
    elif is_valid_crossing(
        ts.confirmed_side, side, rule.valid_to_side, rule.valid_from_side
    ):
        # Reversed crossing: discard as invalid for this rule.
        new_confirmed_side = side
        new_last_pre = time_ms
        new_last_pre_predicted = predicted
        new_last_post = None
    else:
        # Any other transition is treated as the new confirmed side.
        new_confirmed_side = side
        if side == rule.valid_from_side:
            new_last_pre = time_ms
            new_last_pre_predicted = predicted
        else:
            new_last_post = time_ms

    return TrackState(
        last_anchor=anchor,
        last_time_ms=time_ms,
        confirmed_side=new_confirmed_side,
        last_pre_time_ms=new_last_pre,
        last_pre_predicted=new_last_pre_predicted,
        last_post_time_ms=new_last_post,
        episodes=new_episodes,
    )


def _zone_track_state(
    ts: TrackState,
    rule: ZoneRuleConfig,
    obs: TrackObservation,
) -> TrackState:
    time_ms = obs.frame_ref.source_time_ms.root
    anchor = box_anchor(obs.box, AnchorPolicy.BOTTOM_CENTER)
    inside = point_in_polygon(anchor, rule.polygon, boundary_policy=BoundaryPolicy.INSIDE)

    # A gap while inside the zone ends the current persistence episode.
    if (
        ts.zone_inside
        and ts.last_time_ms is not None
        and time_ms - ts.last_time_ms > rule.max_gap_ms
    ):
        entry = ts.zone_entry_ms
        assert entry is not None
        new_episodes = list(ts.episodes)
        new_episodes.append(
            ZoneEpisode(
                episode_id=episode_id(
                    rule.rule_id, obs.track_id, "zone", entry, ts.last_time_ms
                ),
                track_id=obs.track_id,
                persistence=TimeRange(
                    start_ms=SourceTimeMs(entry),
                    end_ms=SourceTimeMs(ts.last_time_ms),
                ),
            )
        )
        ts = TrackState(last_anchor=anchor, last_time_ms=time_ms)

    new_episodes = list(ts.episodes)
    zone_inside = ts.zone_inside
    entry_ms = ts.zone_entry_ms

    if zone_inside is None:
        zone_inside = inside
        if inside:
            entry_ms = time_ms
    elif not zone_inside and inside:
        zone_inside = True
        entry_ms = time_ms
    elif zone_inside and not inside:
        zone_inside = False
        assert entry_ms is not None
        new_episodes.append(
            ZoneEpisode(
                episode_id=episode_id(
                    rule.rule_id, obs.track_id, "zone", entry_ms, time_ms
                ),
                track_id=obs.track_id,
                persistence=TimeRange(
                    start_ms=SourceTimeMs(entry_ms),
                    end_ms=SourceTimeMs(time_ms),
                ),
            )
        )
        entry_ms = None

    return TrackState(
        last_anchor=anchor,
        last_time_ms=time_ms,
        episodes=new_episodes,
        zone_inside=zone_inside,
        zone_entry_ms=entry_ms,
    )


def apply_observations(
    rule: LineRuleConfig | ZoneRuleConfig,
    observations: Sequence[TrackObservation],
    state: RuleState | None = None,
) -> RuleState:
    """Advance ``state`` with a sequence of ordered track observations."""
    if state is None:
        state = RuleState()
    tracks = dict(state.tracks)
    ordered = sorted(
        observations, key=lambda o: o.frame_ref.source_time_ms.root
    )
    for obs in ordered:
        ts = tracks.get(obs.track_id, TrackState())
        if isinstance(rule, LineRuleConfig):
            new_ts = _line_track_state(ts, rule, obs)
        elif isinstance(rule, ZoneRuleConfig):
            new_ts = _zone_track_state(ts, rule, obs)
        else:
            raise TypeError(f"unsupported rule config: {type(rule)}")
        tracks[obs.track_id] = new_ts
    return RuleState(tracks=tracks)


def _merge_zone_episodes(
    episodes: Sequence[ZoneEpisode],
    rule_id: str,
    merge_gap_ms: int,
) -> list[ZoneEpisode]:
    if not episodes:
        return []
    merged_ranges = merge_time_ranges(
        [ep.persistence for ep in episodes], max_gap_ms=merge_gap_ms
    )
    result: list[ZoneEpisode] = []
    track_id = episodes[0].track_id
    for r in merged_ranges:
        result.append(
            ZoneEpisode(
                episode_id=episode_id(
                    rule_id,
                    track_id,
                    "zone",
                    r.start_ms.root,
                    r.end_ms.root,
                ),
                track_id=track_id,
                persistence=r,
            )
        )
    return result


def _candidate_from_crossing(
    rule: LineRuleConfig,
    ep: CrossingEpisode,
    red_intervals: Sequence[SignalInterval] | None,
) -> RuleCandidate:
    if rule.capability_id == "tracked.red_phase_crossing":
        disp, facts = red_phase_disposition(
            ep.bracket, red_intervals or [], rule.margin_ms
        )
    else:
        disp, facts = line_crossing_disposition(ep.bracket)
    if ep.predicted_in_bracket:
        disp = "inconclusive"
        facts.append("predicted_only")
    return RuleCandidate(
        rule_id=ResourceId(rule.rule_id),
        episode_id=ep.episode_id,
        crossing=ep.bracket,
        persistence=None,
        fact_refs=facts + [f"track:{ep.track_id}"],
        disposition=disp,
    )


def _candidate_from_zone(
    rule: ZoneRuleConfig,
    ep: ZoneEpisode,
) -> RuleCandidate:
    return RuleCandidate(
        rule_id=ResourceId(rule.rule_id),
        episode_id=ep.episode_id,
        crossing=None,
        persistence=ep.persistence,
        fact_refs=[
            f"zone:{rule.rule_id}",
            f"track:{ep.track_id}",
            f"persistence:{ep.persistence.start_ms.root}:{ep.persistence.end_ms.root}",
        ],
        disposition="supported",
    )


def flush(
    state: RuleState,
    rule: LineRuleConfig | ZoneRuleConfig,
    end_time_ms: int,
    red_intervals: Sequence[SignalInterval] | None = None,
) -> list[RuleCandidate]:
    """Finalize any pending episodes up to ``end_time_ms``."""
    candidates: list[RuleCandidate] = []

    for track_id, ts in state.tracks.items():
        if isinstance(rule, LineRuleConfig):
            for ep in ts.episodes:
                if isinstance(ep, CrossingEpisode):
                    candidates.append(
                        _candidate_from_crossing(rule, ep, red_intervals)
                    )
        elif isinstance(rule, ZoneRuleConfig):
            zone_eps = list(ts.episodes)
            if ts.zone_inside and ts.zone_entry_ms is not None:
                zone_eps.append(
                    ZoneEpisode(
                        episode_id=episode_id(
                            rule.rule_id, track_id, "zone", ts.zone_entry_ms, end_time_ms
                        ),
                        track_id=track_id,
                        persistence=TimeRange(
                            start_ms=SourceTimeMs(ts.zone_entry_ms),
                            end_ms=SourceTimeMs(end_time_ms),
                        ),
                    )
                )
            merged = _merge_zone_episodes(zone_eps, rule.rule_id, rule.merge_gap_ms)
            for ep in merged:
                candidates.append(_candidate_from_zone(rule, ep))
        else:
            raise TypeError(f"unsupported rule config: {type(rule)}")

    return candidates
