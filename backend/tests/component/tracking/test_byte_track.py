"""CT-TRACK: ByteTrack tracking adapter with deterministic canned detections.

These tests exercise the real ByteTrack integration through ``supervision``.
No RF-DETR, torch, GPU, or network is required; detections are constructed by hand.
"""
from __future__ import annotations

import pytest

pytest.importorskip("supervision")

from vision_app.contracts.models import (
    BoxN,
    Detection,
    DetectionBatch,
    FrameRef,
    QualityFlag,
    ResourceId,
    SourceTimeMs,
)
from vision_app.perception.tracking.byte_track import (
    ByteTrackAdapterConfig,
    ByteTrackFactory,
)


WIDTH = 320
HEIGHT = 240
MODEL_REF = "fake-detector"


def _frame_ref(time_ms: int, sequence: int) -> FrameRef:
    return FrameRef(
        source_id=ResourceId("source-1"),
        source_hash="a" * 64,
        pts=time_ms,
        time_base_num=1,
        time_base_den=1000,
        source_time_ms=SourceTimeMs(time_ms),
        sequence=sequence,
        width=WIDTH,
        height=HEIGHT,
        transform_id=ResourceId("tfm-1"),
    )


def _box_from_px(box_px: tuple[int, int, int, int]) -> BoxN:
    x1, y1, x2, y2 = box_px
    return BoxN(
        x1=x1 / WIDTH,
        y1=y1 / HEIGHT,
        x2=x2 / WIDTH,
        y2=y2 / HEIGHT,
    )


def _detection(
    class_name: str,
    box_px: tuple[int, int, int, int],
    score: float = 0.9,
) -> Detection:
    return Detection(
        class_name=class_name,
        box=_box_from_px(box_px),
        score=score,
        model_ref=MODEL_REF,
    )


def _batch(
    time_ms: int,
    sequence: int,
    detections: list[Detection],
) -> DetectionBatch:
    return DetectionBatch(
        frame_ref=_frame_ref(time_ms, sequence),
        detections=detections,
        invocation=None,
    )


def _first_observation(batch: DetectionBatch) -> Detection:
    assert batch.detections
    return batch.detections[0]


class TestIndependentSessions:
    """Two sessions for different attempts must not share IDs or internal state."""

    def test_sessions_do_not_share_track_ids(self) -> None:
        factory = ByteTrackFactory()
        session_a = factory.create("attempt-a")
        session_b = factory.create("attempt-b")

        for i in range(3):
            box_a = (40 + 4 * i, 150, 64 + 4 * i, 164)
            box_b = (200 + 4 * i, 50, 224 + 4 * i, 64)
            session_a.update(_batch(i * 100, i, [_detection("car", box_a)]))
            session_b.update(_batch(i * 100, i, [_detection("car", box_b)]))

        ids_a = {obs.track_id for obs in session_a.update(_batch(300, 3, [_detection("car", (52, 150, 76, 164))]))}
        ids_b = {obs.track_id for obs in session_b.update(_batch(300, 3, [_detection("car", (212, 50, 236, 64))]))}

        assert ids_a == {"1"}
        assert ids_b == {"1"}

    def test_sessions_do_not_share_class_history(self) -> None:
        factory = ByteTrackFactory()
        session_a = factory.create("attempt-a")
        session_b = factory.create("attempt-b")

        # Session A sees a class fluctuation.
        session_a.update(_batch(0, 0, [_detection("car", (40, 150, 64, 164))]))
        session_a.update(_batch(100, 1, [_detection("truck", (44, 150, 68, 164))]))
        obs_a = session_a.update(_batch(200, 2, [_detection("car", (48, 150, 72, 164))]))

        # Session B sees only consistent classes.
        for i in range(3):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            session_b.update(_batch(i * 100, i, [_detection("car", box)]))
        obs_b = session_b.update(_batch(300, 3, [_detection("car", (52, 150, 76, 164))]))

        assert any("class_fluctuation" in r for obs in obs_a for r in obs.quality.reasons)
        assert not any("class_fluctuation" in r for obs in obs_b for r in obs.quality.reasons)


class TestContinuity:
    """ID continuity and gap/scene reset behavior."""

    def test_id_continuity_across_frames(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        track_ids: list[str] = []
        for i in range(5):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            batch = _batch(i * 100, i, [_detection("car", box)])
            observations = session.update(batch)
            assert len(observations) == 1
            track_ids.append(observations[0].track_id)

        assert len(set(track_ids)) == 1
        assert track_ids[0] == "1"

    def test_long_gap_causes_reset(self) -> None:
        config = ByteTrackAdapterConfig(max_gap_ms=1000)
        factory = ByteTrackFactory(config)
        session = factory.create("attempt-1")

        for i in range(3):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            session.update(_batch(i * 100, i, [_detection("car", box)]))

        # 2000 ms gap exceeds the 1000 ms configured limit.
        obs_after_gap = session.update(_batch(2200, 4, [_detection("car", (52, 150, 76, 164))]))
        assert len(obs_after_gap) == 1
        after_gap = obs_after_gap[0]

        # The new logical track has no memory of earlier observations.
        assert after_gap.last_observed_ms.root == 2200
        assert not any("class_fluctuation" in r for r in after_gap.quality.reasons)

    def test_track_survives_short_gap(self) -> None:
        config = ByteTrackAdapterConfig(max_gap_ms=1000)
        factory = ByteTrackFactory(config)
        session = factory.create("attempt-1")

        for i in range(3):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            session.update(_batch(i * 100, i, [_detection("car", box)]))

        # 500 ms gap is within the configured limit.
        obs = session.update(_batch(500, 3, [_detection("car", (48, 150, 72, 164))]))
        assert len(obs) == 1
        assert obs[0].track_id == "1"
        assert obs[0].last_observed_ms.root == 500


class TestObservedAndPredicted:
    """Observed/predicted flags and gap policy."""

    def test_predicted_only_frame_emits_no_observation(self) -> None:
        """A frame with no detections must not fabricate a track observation."""
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        session.update(_batch(0, 0, [_detection("car", (40, 150, 64, 164))]))
        session.update(_batch(100, 1, [_detection("car", (44, 150, 68, 164))]))

        predicted_only = session.update(_batch(200, 2, []))
        assert predicted_only == []

    def test_all_returned_observations_are_observed(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        for i in range(3):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            obs = session.update(_batch(i * 100, i, [_detection("car", box)]))
            assert len(obs) == 1
            assert obs[0].observed is True
            assert QualityFlag.PREDICTED_ONLY not in obs[0].quality.flags


class TestClassHistory:
    """Class labels should be stable; fluctuations are flagged."""

    def test_class_fluctuation_is_flagged(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        session.update(_batch(0, 0, [_detection("car", (40, 150, 64, 164))]))
        session.update(_batch(100, 1, [_detection("truck", (44, 150, 68, 164))]))
        obs = session.update(_batch(200, 2, [_detection("car", (48, 150, 72, 164))]))

        assert len(obs) == 1
        assert obs[0].track_id == "1"
        assert any("class_fluctuation" in reason for reason in obs[0].quality.reasons)

    def test_consistent_class_has_no_fluctuation_reason(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        for i in range(3):
            box = (40 + 4 * i, 150, 64 + 4 * i, 164)
            session.update(_batch(i * 100, i, [_detection("car", box)]))

        obs = session.update(_batch(300, 3, [_detection("car", (52, 150, 76, 164))]))
        assert len(obs) == 1
        assert not any("class_fluctuation" in reason for reason in obs[0].quality.reasons)


class TestCadenceAndOrdering:
    """Source-time ordering and cadence/gap reset behavior."""

    def test_out_of_order_source_time_raises(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        session.update(_batch(200, 0, [_detection("car", (40, 150, 64, 164))]))
        with pytest.raises(ValueError, match="out of order"):
            session.update(_batch(100, 1, [_detection("car", (44, 150, 68, 164))]))

    def test_equal_timestamp_is_allowed(self) -> None:
        """Two detections at the same source time are accepted (e.g., duplicate frame)."""
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        session.update(_batch(0, 0, [_detection("car", (40, 150, 64, 164))]))
        obs = session.update(_batch(0, 1, [_detection("car", (40, 150, 64, 164))]))
        assert len(obs) == 1


class TestNoFabricatedHistory:
    """A track that appears after the line must not have a before-line history."""

    def test_new_post_line_track_has_fresh_last_observed(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        # Object appears for the first time after the stop-line time.
        first_obs = session.update(
            _batch(3000, 30, [_detection("car", (170, 150, 194, 164))])
        )
        assert len(first_obs) == 1
        assert first_obs[0].last_observed_ms.root == 3000
        assert first_obs[0].track_id == "1"

        # Continues moving away from the line.
        later = session.update(
            _batch(3100, 31, [_detection("car", (180, 150, 204, 164))])
        )
        assert len(later) == 1
        assert later[0].last_observed_ms.root == 3100


class TestBoxAndAnchor:
    """Output geometry follows the source-time detection and uses bottom-center anchor."""

    def test_output_box_matches_input_box(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        box_px = (40, 150, 64, 164)
        batch = _batch(0, 0, [_detection("car", box_px)])
        obs = session.update(batch)
        assert len(obs) == 1

        out_box = obs[0].box
        assert out_box.x1 == pytest.approx(40 / WIDTH)
        assert out_box.y1 == pytest.approx(150 / HEIGHT)
        assert out_box.x2 == pytest.approx(64 / WIDTH)
        assert out_box.y2 == pytest.approx(164 / HEIGHT)

    def test_anchor_is_bottom_center(self) -> None:
        factory = ByteTrackFactory()
        session = factory.create("attempt-1")

        box_px = (40, 150, 64, 164)
        batch = _batch(0, 0, [_detection("car", box_px)])
        obs = session.update(batch)
        assert len(obs) == 1

        anchor = obs[0].anchor
        assert anchor.x == pytest.approx(((40 + 64) / 2) / WIDTH)
        assert anchor.y == pytest.approx(164 / HEIGHT)
