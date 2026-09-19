"""Component tests for the pure deterministic temporal rule interpreter (C02)."""
from __future__ import annotations

from conftest import (
    box_from_px,
    build_red_intervals,
    load_annotation,
    observations_from_annotation,
    red_interval,
    signal_observations_from_annotation,
    track_observation,
)
from vision_app.contracts.models import PointN
from vision_app.rules.anchor import AnchorPolicy, box_anchor
from vision_app.rules.config import LineRuleConfig, ZoneRuleConfig
from vision_app.rules.reducer import apply_observations, flush


def stop_line_rule() -> LineRuleConfig:
    return LineRuleConfig(
        rule_id="rule-red-phase",
        capability_id="tracked.red_phase_crossing",
        object_classes=("car",),
        line=(PointN(x=0.5, y=0.0), PointN(x=0.5, y=1.0)),
        anchor_policy=AnchorPolicy.BOTTOM_LEFT,
        band_width=0.01,
        max_gap_ms=500,
        valid_from_side=1,
        valid_to_side=-1,
    )


def test_red_phase_violation_matches_fixture() -> None:
    annotation = load_annotation("red_light_violation")
    obs = observations_from_annotation(annotation)
    red_intervals = build_red_intervals(signal_observations_from_annotation(annotation))
    rule = stop_line_rule()
    state = apply_observations(rule, obs)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.disposition == "supported"
    assert c.crossing is not None
    assert c.crossing.last_pre_ms.root == 2900
    assert c.crossing.first_post_ms.root == 3100
    assert len(c.episode_id) == 16
    assert "track:track-1" in c.fact_refs
    assert "signal:red" in " ".join(c.fact_refs)


def test_car_crossed_on_green_and_remains_in_junction_after_red_is_not_a_violation() -> None:
    """Vehicle that entered on green and stayed in the junction is not flagged."""
    frames = []
    # Approach and cross the stop line while the signal is still green.
    for i in range(20):
        t = i * 100
        x = min(40 + 8 * i, 296)
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    # Signal turns red after the vehicle has already crossed.
    for i in range(20, 50):
        t = i * 100
        # vehicle continues moving away from the line
        x = min(40 + 8 * i, 296)
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    red_intervals = [red_interval(2000, 5000)]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len([c for c in candidates if c.disposition != "rejected"]) == 0


def test_two_vehicles_produce_two_events() -> None:
    frames = []
    for i in range(50):
        t = i * 100
        for tid, base_x in (("track-a", 20), ("track-b", 100)):
            x = min(base_x + 4 * i, 296)
            frames.append(track_observation(tid, t, i, [x, 150, x + 24, 164]))
    red_intervals = [red_interval(0, 5000)]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 2
    assert {"track:track-a", "track:track-b"} <= set(
        fact for c in candidates for fact in c.fact_refs
    )


def test_unknown_signal_gap_not_bridged() -> None:
    frames = []
    for i in range(50):
        t = i * 100
        x = 40 + 4 * i
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    # Red is interrupted by unknown in the middle of the crossing window.
    red_intervals = [
        red_interval(0, 2800),
        red_interval(3300, 5000),
    ]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len([c for c in candidates if c.disposition == "supported"]) == 0
    inconclusive = [c for c in candidates if c.disposition == "inconclusive"]
    assert len(inconclusive) == 1


def test_predicted_only_crossing_is_refused() -> None:
    frames = []
    for i in range(50):
        t = i * 100
        x = 40 + 4 * i
        frames.append(
            track_observation(
                "track-1",
                t,
                i,
                [x, 150, x + 24, 164],
                predicted_only=(i in {29, 30}),
            )
        )
    red_intervals = [red_interval(0, 5000)]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len([c for c in candidates if c.disposition == "supported"]) == 0


def test_jitter_around_line_does_not_duplicate_episodes() -> None:
    """Repeated side changes inside the hysteresis band must not create duplicate episodes."""
    frames = []
    # Cross cleanly once, ending on the post side of the line.
    for i in range(32):
        t = i * 100
        x = 40 + 4 * i
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    # Jitter back and forth near the line for the remainder of the clip.
    for i in range(30):
        t = 3200 + i * 100
        side = -1 if i % 2 == 0 else 1
        x = 158 + side * 3
        frames.append(track_observation("track-1", t, 32 + i, [x, 150, x + 24, 164]))
    red_intervals = [red_interval(0, 5000)]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 1


def test_gap_in_track_resets_continuity() -> None:
    frames = []
    # Approach the stop line, then disappear for a long gap and reappear beyond it.
    for i in range(10):
        t = i * 100
        x = 40 + 4 * i
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    # After the gap the vehicle is already on the far side of the line.
    for i in range(25, 50):
        t = i * 100
        x = min(200 + 4 * i, 296)
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    red_intervals = [red_interval(0, 5000)]
    rule = stop_line_rule()
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    # With max_gap_ms of 500, the 1500 ms gap means the crossing cannot be supported.
    assert len([c for c in candidates if c.disposition == "supported"]) == 0


def test_directional_line_count_only_counts_valid_direction() -> None:
    rule = LineRuleConfig(
        rule_id="rule-count",
        capability_id="tracked.line_crossing",
        object_classes=("car",),
        line=(PointN(x=0.5, y=0.0), PointN(x=0.5, y=1.0)),
        anchor_policy=AnchorPolicy.BOTTOM_LEFT,
        band_width=0.01,
        max_gap_ms=500,
        valid_from_side=1,
        valid_to_side=-1,
    )
    frames = []
    for i in range(30):
        t = i * 100
        x = min(40 + 8 * i, 296)
        frames.append(track_observation("track-1", t, i, [x, 150, x + 24, 164]))
    # Then one reversed right-to-left crossing on the same track.
    for i in range(30):
        t = 3000 + i * 100
        x = max(280 - 8 * i, 0)
        frames.append(track_observation("track-1", t, 30 + i, [x, 150, x + 24, 164]))
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=6000)
    supported = [c for c in candidates if c.disposition == "supported"]
    assert len(supported) == 1


def test_zone_persistence_emits_one_event_per_entry_exit() -> None:
    zone = ZoneRuleConfig(
        rule_id="rule-zone",
        capability_id="tracked.person_in_zone",
        object_classes=("person",),
        polygon=(
            PointN(x=0.3, y=0.3),
            PointN(x=0.7, y=0.3),
            PointN(x=0.7, y=0.7),
            PointN(x=0.3, y=0.7),
        ),
        max_gap_ms=200,
        merge_gap_ms=0,
    )
    frames = []
    # Enter at t=1000, stay, exit at t=3000.
    positions = [(0.2, 0.5)] * 10 + [(0.5, 0.5)] * 20 + [(0.8, 0.5)] * 10
    for i, (nx, ny) in enumerate(positions):
        t = i * 100
        frames.append(
            track_observation(
                "track-1",
                t,
                i,
                [
                    int((nx - 0.03) * 320),
                    int((ny - 0.05) * 240),
                    int((nx + 0.03) * 320),
                    int((ny + 0.05) * 240),
                ],
            )
        )
    state = apply_observations(zone, frames)
    candidates = flush(state, zone, end_time_ms=4000)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.disposition == "supported"
    assert c.persistence is not None
    assert c.persistence.start_ms.root == 1000
    assert c.persistence.end_ms.root == 3000


def test_box_anchor_bottom_left() -> None:
    box = box_anchor(box_from_px([10, 20, 30, 40], width=100, height=100), AnchorPolicy.BOTTOM_LEFT)
    assert box.x == 0.1
    assert box.y == 0.4


def test_red_phase_boundary_equality() -> None:
    """A crossing whose bracket starts exactly at r0 + margin is supported."""
    rule = stop_line_rule()
    frames = [
        track_observation("track-1", 2100, 0, [140, 150, 164, 164]),
        track_observation("track-1", 2300, 1, [180, 150, 204, 164]),
    ]
    # Red starts at 2000, margin is 100, so bracket [2100, 2300] begins exactly
    # at the supported boundary.
    red_intervals = [red_interval(2000, 5000)]
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 1
    assert candidates[0].disposition == "supported"


def test_red_phase_inside_margin_is_inconclusive() -> None:
    """A crossing whose bracket starts inside the ambiguity margin is inconclusive."""
    rule = stop_line_rule()
    frames = [
        track_observation("track-1", 2050, 0, [140, 150, 164, 164]),
        track_observation("track-1", 2250, 1, [180, 150, 204, 164]),
    ]
    red_intervals = [red_interval(2000, 5000)]
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 1
    assert candidates[0].disposition == "inconclusive"


def test_stopped_before_line_is_not_a_crossing() -> None:
    rule = stop_line_rule()
    frames = [
        track_observation("track-1", i * 100, i, [20 + 4 * i, 150, 44 + 4 * i, 164])
        for i in range(20)
    ]
    red_intervals = [red_interval(0, 5000)]
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 0


def test_first_observation_beyond_line_cannot_prove_crossing() -> None:
    rule = stop_line_rule()
    frames = [
        track_observation(
            "track-1",
            i * 100,
            i,
            [min(200 + 4 * i, 296), 150, min(224 + 4 * i, 320), 164],
        )
        for i in range(20)
    ]
    red_intervals = [red_interval(0, 5000)]
    state = apply_observations(rule, frames)
    candidates = flush(state, rule, end_time_ms=5000, red_intervals=red_intervals)
    assert len(candidates) == 0
