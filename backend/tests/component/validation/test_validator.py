"""CT-VALIDATION: semantic spec validator acceptance and rejection cases.

Covers the C03 RED cases:
- schema-valid semantic app requesting exact tracked counts is rejected
- red-light app missing governing-signal binding cannot publish
- invalid capability combination is rejected

And the CT-VALIDATION family for tracked and semantic apps.
"""
from __future__ import annotations

from datetime import datetime, timezone

from vision_app.contracts.models import (
    AppSpec,
    Calibration,
    EvidencePolicy,
    ExecutionLimits,
    FrameRef,
    ResourceId,
    SemanticCondition,
    SemanticWindowsSpec,
    SourceTimeMs,
    TrackedRule,
    TrackedRulesSpec,
    UtcTimestamp,
)
from vision_app.validation.registry import REGISTRY
from vision_app.validation.validator import validate_app_spec


UTC = timezone.utc


def _utc_now() -> UtcTimestamp:
    return UtcTimestamp(datetime.now(UTC))


def _resource_id(value: str) -> ResourceId:
    return ResourceId(value)


def _frame_ref(source_id: str = "source_1") -> FrameRef:
    return FrameRef(
        source_id=_resource_id(source_id),
        source_hash="a" * 64,
        pts=0,
        time_base_num=1,
        time_base_den=30,
        source_time_ms=SourceTimeMs(0),
        sequence=0,
        width=1920,
        height=1080,
        transform_id=_resource_id("transform_1"),
    )


def _calibration(
    *,
    confirmed: bool = True,
    signals: dict[str, str] | None = None,
    lanes: dict[str, list[tuple[float, float]]] | None = None,
    lines: dict[str, list[tuple[float, float]]] | None = None,
) -> Calibration:
    from vision_app.contracts.models import PointN

    default_line = [(0.4, 0.5), (0.6, 0.5)]
    default_lane = [(0.3, 0.9), (0.7, 0.9), (0.7, 0.5), (0.3, 0.5)]
    pts = [PointN(x=x, y=y) for x, y in (lines or {}).get("stop_line", default_line)]
    lane_points = {
        "approach": [PointN(x=x, y=y) for x, y in (lanes or {}).get("approach", default_lane)]
    }
    return Calibration(
        id=_resource_id("cal_1"),
        source_id=_resource_id("source_1"),
        workspace_id=_resource_id("workspace-a"),
        camera_binding="fixed_camera_north",
        revision=1,
        reference_frame=_frame_ref(),
        lanes=lane_points,
        lines=lines or {"stop_line": pts},
        rois={},
        governing_signals=signals if signals is not None else {"stop_line": "main_signal"},
        confirmed_by=_resource_id("user_1") if confirmed else None,
        confirmed_at=_utc_now() if confirmed else None,
        scene_fingerprint="fp_1",
    )


def _tracked_spec(
    capability_id: str = "tracked.line_crossing",
    object_classes: list[str] | None = None,
) -> TrackedRulesSpec:
    return TrackedRulesSpec(
        title="Line counter",
        objective="Count cars crossing a line",
        evidence_policy=EvidencePolicy(),
        approved_action_refs=[],
        limits=ExecutionLimits(),
        kind="tracked_rules",
        rules=[
            TrackedRule(
                rule_id=_resource_id("rule_1"),
                capability_id=capability_id,  # type: ignore[arg-type]
                object_classes=object_classes or ["car"],
            )
        ],
    )


def _semantic_spec(prompt: str = "Is the exit obstructed?") -> SemanticWindowsSpec:
    return SemanticWindowsSpec(
        title="Exit check",
        objective="Detect whether the emergency exit is blocked",
        evidence_policy=EvidencePolicy(),
        approved_action_refs=[],
        limits=ExecutionLimits(),
        kind="semantic_windows",
        conditions=[
            SemanticCondition(
                condition_id=_resource_id("cond_1"),
                prompt=prompt,
            )
        ],
        window_ms=5000,
        stride_ms=2500,
        sample_fps=1.0,
    )


def test_registry_lists_supported_capabilities() -> None:
    """Registry exposes the installed capability vocabulary."""
    ids = REGISTRY.capability_ids()
    assert "tracked.line_crossing" in ids
    assert "tracked.red_phase_crossing" in ids
    assert "semantic.visible_condition" in ids
    assert "detector.common" in REGISTRY.components()


def test_contract_example_tracked_spec_is_publication_ready() -> None:
    """An independently generated valid tracked spec from C0 examples validates."""
    from pathlib import Path

    from pydantic import TypeAdapter

    example = Path(__file__).resolve().parents[4] / "packages/contracts/examples/tracked_rules.valid.json"
    spec = TypeAdapter(AppSpec).validate_json(example.read_text())
    cal = _calibration(signals={"red_line": "signal_a"})
    outcome = validate_app_spec(spec, calibration=cal, publication=True)
    assert outcome.state == "publication_ready"
    assert outcome.model_manifest.get("detector.common") == "roboflow/rf-detr-small:v1"


def test_contract_example_semantic_spec_is_publication_ready() -> None:
    """An independently generated valid semantic spec from C0 examples validates."""
    from pathlib import Path

    from pydantic import TypeAdapter

    example = Path(__file__).resolve().parents[4] / "packages/contracts/examples/semantic_windows.valid.json"
    spec = TypeAdapter(AppSpec).validate_json(example.read_text())
    outcome = validate_app_spec(spec, publication=True)
    assert outcome.state == "publication_ready"
    assert outcome.model_manifest.get("reasoner.window") == "google/gemini-3.8-flash:v1"


class TestTrackedValidation:
    """CT-VALIDATION for tracked (geometric/temporal) apps."""

    def test_valid_tracked_spec_is_publication_ready_with_confirmed_calibration(self) -> None:
        spec = _tracked_spec()
        cal = _calibration(confirmed=True)
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "publication_ready"
        assert not outcome.issues

    def test_missing_calibration_blocks_publication(self) -> None:
        spec = _tracked_spec()
        outcome = validate_app_spec(
            spec,
            calibration=None,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "needs_calibration"
        assert any(i.code == "missing_calibration" for i in outcome.issues)

    def test_unconfirmed_calibration_blocks_publication(self) -> None:
        spec = _tracked_spec()
        cal = _calibration(confirmed=False)
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "needs_calibration"
        assert any(i.code == "calibration_unconfirmed" for i in outcome.issues)

    def test_red_light_missing_signal_cannot_publish(self) -> None:
        spec = _tracked_spec(capability_id="tracked.red_phase_crossing")
        cal = _calibration(signals={})
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "needs_calibration"
        assert any(
            i.code == "missing_governing_signal" and i.capability_id == "tracked.red_phase_crossing"
            for i in outcome.issues
        )

    def test_red_light_with_signal_can_publish(self) -> None:
        spec = _tracked_spec(capability_id="tracked.red_phase_crossing")
        cal = _calibration(signals={"stop_line": "main_signal"})
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "publication_ready"

    def test_unknown_object_class_rejected(self) -> None:
        spec = _tracked_spec(object_classes=["car", "airplane"])
        cal = _calibration()
        outcome = validate_app_spec(spec, calibration=cal)
        assert outcome.state == "invalid"
        assert any(i.code == "unsupported_class" and "airplane" in i.message for i in outcome.issues)

    def test_class_capability_mismatch_rejected(self) -> None:
        # person_in_zone only supports "person"; "car" is an invalid combination.
        spec = _tracked_spec(capability_id="tracked.person_in_zone", object_classes=["car"])
        cal = _calibration()
        outcome = validate_app_spec(spec, calibration=cal)
        assert outcome.state == "invalid"
        assert any(
            i.code == "unsupported_class"
            and i.capability_id == "tracked.person_in_zone"
            and "car" in i.message
            for i in outcome.issues
        )

    def test_forbidden_action_ref_rejected(self) -> None:
        spec = _tracked_spec()
        spec = spec.model_copy(update={"approved_action_refs": [_resource_id("action_1")]})
        cal = _calibration()
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "invalid"
        assert any(i.code == "unapproved_action" for i in outcome.issues)

    def test_approved_action_ref_allowed(self) -> None:
        spec = _tracked_spec()
        spec = spec.model_copy(update={"approved_action_refs": [_resource_id("action_1")]})
        cal = _calibration()
        outcome = validate_app_spec(
            spec,
            calibration=cal,
            approved_action_refs=frozenset({"action_1"}),
            publication=True,
        )
        assert outcome.state == "publication_ready"

    def test_exceeding_limits_rejected(self) -> None:
        spec = _tracked_spec()
        spec = spec.model_copy(update={"limits": ExecutionLimits(max_duration_ms=999999, max_model_calls=999)})
        cal = _calibration()
        outcome = validate_app_spec(spec, calibration=cal)
        assert outcome.state == "invalid"
        assert any(i.code == "limit_exceeded" for i in outcome.issues)


class TestSemanticValidation:
    """CT-VALIDATION for semantic-window apps."""

    def test_valid_semantic_spec_is_publication_ready(self) -> None:
        spec = _semantic_spec()
        outcome = validate_app_spec(
            spec,
            calibration=None,
            approved_action_refs=frozenset(),
            publication=True,
        )
        assert outcome.state == "publication_ready"
        assert not outcome.issues

    def test_semantic_exact_count_request_rejected(self) -> None:
        spec = _semantic_spec("Count exactly how many cars cross the line")
        outcome = validate_app_spec(spec)
        assert outcome.state == "invalid"
        assert any(
            i.code == "semantic_exact_count_unsupported"
            and i.field == "conditions[0].prompt"
            for i in outcome.issues
        )

    def test_semantic_tracking_request_rejected(self) -> None:
        spec = _semantic_spec("Track each person and report their exact path")
        outcome = validate_app_spec(spec)
        assert outcome.state == "invalid"
        assert any(i.code == "semantic_tracking_unsupported" for i in outcome.issues)

    def test_semantic_roi_requires_calibration(self) -> None:
        spec = _semantic_spec("Is the loading dock obstructed?")
        spec = spec.model_copy(
            update={
                "conditions": [
                    SemanticCondition(
                        condition_id=_resource_id("cond_1"),
                        prompt="Is the loading dock obstructed?",
                        roi_id=_resource_id("roi_dock"),
                    )
                ]
            }
        )
        outcome = validate_app_spec(spec, calibration=None, publication=True)
        assert outcome.state == "needs_calibration"
        assert any(i.code == "missing_calibration" for i in outcome.issues)


class TestCapabilityCombinations:
    """Combinations and registry consistency."""

    def test_registry_rejects_uninstalled_component(self) -> None:
        from vision_app.validation.registry import CapabilityEntry, CapabilityRegistry

        bad_registry = CapabilityRegistry(
            capabilities={
                "tracked.line_crossing": CapabilityEntry(
                    capability_id="tracked.line_crossing",
                    mode="tracked_rules",
                    requires=frozenset({"detector.common", "tracker.bytetrack", "missing.component"}),
                    supported_classes=frozenset({"person"}),
                )
            },
            models={},
            actions=frozenset(),
            installed_components=frozenset({"detector.common", "tracker.bytetrack"}),
            max_limits=ExecutionLimits(),
        )
        assert not bad_registry.combinations_are_consistent()

    def test_registry_components_consistent(self) -> None:
        assert REGISTRY.combinations_are_consistent()
