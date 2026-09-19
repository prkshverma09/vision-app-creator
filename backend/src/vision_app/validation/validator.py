"""Semantic spec validator cross-referencing AppSpec against the capability registry.

The validator is intentionally deterministic and does not call models,
decode video, or infer geometry.  It returns typed issues and one of three
outcomes:

* ``invalid`` -- the spec cannot be run as proposed;
* ``needs_calibration`` -- structurally valid but missing confirmed scene data;
* ``publication_ready`` -- valid and, when ``publication=True``, sufficiently
  calibrated and approved for publication.

Action refs on a spec are opaque resource IDs.  They are treated as references to
externally approved authorizations, never as embedded permission to act.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from vision_app.contracts.models import (
    AppSpec,
    Calibration,
    ExecutionLimits,
    ResourceId,
    SemanticCondition,
    SemanticWindowsSpec,
    TrackedRule,
    TrackedRulesSpec,
)
from vision_app.validation.registry import REGISTRY, CapabilityRegistry


@dataclass
class ValidationIssue:
    """A single typed, actionable validation finding."""

    code: str
    message: str
    severity: Literal["error", "calibration"] = "error"
    field: str | None = None
    capability_id: str | None = None


@dataclass
class ValidationOutcome:
    """Result of validating an AppSpec."""

    state: Literal["invalid", "needs_calibration", "publication_ready"] = "invalid"
    issues: list[ValidationIssue] = field(default_factory=list)
    capability_manifest: dict[str, str] = field(default_factory=dict)
    model_manifest: dict[str, str] = field(default_factory=dict)


def validate_app_spec(
    spec: AppSpec,
    *,
    calibration: Calibration | None = None,
    approved_action_refs: frozenset[str] = frozenset(),
    publication: bool = False,
    registry: CapabilityRegistry = REGISTRY,
) -> ValidationOutcome:
    """Validate ``spec`` against the capability registry.

    Args:
        spec: the application specification to validate.
        calibration: optional confirmed calibration; required for most tracked
            rules at publication time.
        approved_action_refs: set of externally approved action permission IDs.
            Spec action refs not in this set are rejected.
        publication: if True, enforce calibration confirmation and action
            approval gates in addition to base validity.
        registry: capability registry to validate against (default is the
            installed C0 registry).
    """
    issues: list[ValidationIssue] = []
    issues.extend(_validate_limits(spec.limits, registry.max_limits))
    issues.extend(_validate_action_refs(spec.approved_action_refs, approved_action_refs))

    if isinstance(spec, TrackedRulesSpec):
        issues.extend(_validate_tracked_rules(spec, calibration, registry, publication))
    elif isinstance(spec, SemanticWindowsSpec):
        issues.extend(_validate_semantic_windows(spec, calibration, registry, publication))

    errors = [i for i in issues if i.severity == "error"]
    calibration_issues = [i for i in issues if i.severity == "calibration"]

    if errors:
        state: Literal["invalid", "needs_calibration", "publication_ready"] = "invalid"
    elif calibration_issues:
        state = "needs_calibration"
    else:
        state = "publication_ready"

    return ValidationOutcome(
        state=state,
        issues=issues,
        capability_manifest=_build_capability_manifest(spec, registry),
        model_manifest=_build_model_manifest(spec, registry),
    )


def _validate_limits(limits: ExecutionLimits, max_limits: ExecutionLimits) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if limits.max_duration_ms > max_limits.max_duration_ms:
        issues.append(
            ValidationIssue(
                code="limit_exceeded",
                field="limits.max_duration_ms",
                message=(
                    f"max_duration_ms {limits.max_duration_ms} exceeds "
                    f"allowed maximum {max_limits.max_duration_ms}"
                ),
            )
        )
    if limits.max_model_calls > max_limits.max_model_calls:
        issues.append(
            ValidationIssue(
                code="limit_exceeded",
                field="limits.max_model_calls",
                message=(
                    f"max_model_calls {limits.max_model_calls} exceeds "
                    f"allowed maximum {max_limits.max_model_calls}"
                ),
            )
        )
    return issues


def _validate_action_refs(
    spec_refs: list[ResourceId], approved_action_refs: frozenset[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for ref in spec_refs:
        ref_value = ref.root if hasattr(ref, "root") else str(ref)
        if ref_value not in approved_action_refs:
            issues.append(
                ValidationIssue(
                    code="unapproved_action",
                    field="approved_action_refs",
                    message=(
                        f"Action reference '{ref_value}' is not present in the "
                        "externally approved action permissions"
                    ),
                )
            )
    return issues


def _validate_tracked_rules(
    spec: TrackedRulesSpec,
    calibration: Calibration | None,
    registry: CapabilityRegistry,
    publication: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if publication and calibration is None:
        issues.append(
            ValidationIssue(
                code="missing_calibration",
                severity="calibration",
                message="Publication requires a confirmed calibration for tracked rules",
            )
        )
    if publication and calibration is not None and not _calibration_confirmed(calibration):
        issues.append(
            ValidationIssue(
                code="calibration_unconfirmed",
                severity="calibration",
                message="Calibration exists but has not been confirmed by a user",
            )
        )

    for rule in spec.rules:
        issues.extend(_validate_tracked_rule(rule, calibration, registry))
    return issues


def _validate_tracked_rule(
    rule: TrackedRule,
    calibration: Calibration | None,
    registry: CapabilityRegistry,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    entry = registry.capabilities.get(rule.capability_id)
    if entry is None:
        issues.append(
            ValidationIssue(
                code="unknown_capability",
                field=f"rules[{rule.rule_id.root}].capability_id",
                message=f"Capability '{rule.capability_id}' is not installed",
                capability_id=rule.capability_id,
            )
        )
        return issues

    if entry.mode != "tracked_rules":
        issues.append(
            ValidationIssue(
                code="capability_mode_mismatch",
                field=f"rules[{rule.rule_id.root}].capability_id",
                message=(
                    f"Capability '{rule.capability_id}' is a semantic capability "
                    "and cannot be used in a tracked_rules spec"
                ),
                capability_id=rule.capability_id,
            )
        )

    for cls in rule.object_classes:
        if cls not in entry.supported_classes:
            issues.append(
                ValidationIssue(
                    code="unsupported_class",
                    field=f"rules[{rule.rule_id.root}].object_classes",
                    message=(
                        f"Class '{cls}' is not supported by capability "
                        f"'{rule.capability_id}'; supported: "
                        f"{sorted(entry.supported_classes)}"
                    ),
                    capability_id=rule.capability_id,
                )
            )

    if rule.capability_id == "tracked.red_phase_crossing":
        if calibration is None or not calibration.governing_signals:
            issues.append(
                ValidationIssue(
                    code="missing_governing_signal",
                    severity="calibration",
                    field="calibration.governing_signals",
                    message=(
                        "tracked.red_phase_crossing requires a confirmed "
                        "governing-signal binding in the calibration"
                    ),
                    capability_id=rule.capability_id,
                )
            )

    return issues


def _validate_semantic_windows(
    spec: SemanticWindowsSpec,
    calibration: Calibration | None,
    registry: CapabilityRegistry,
    publication: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for idx, condition in enumerate(spec.conditions):
        issues.extend(_validate_semantic_condition(idx, condition, calibration, registry, publication))
    return issues


def _validate_semantic_condition(
    idx: int,
    condition: SemanticCondition,
    calibration: Calibration | None,
    registry: CapabilityRegistry,
    publication: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    prompt = condition.prompt.lower()
    field = f"conditions[{idx}].prompt"

    if _requests_exact_count(prompt):
        issues.append(
            ValidationIssue(
                code="semantic_exact_count_unsupported",
                field=field,
                message=(
                    "Semantic windows cannot request exact counts or tracking; "
                    "use a tracked rule for countable objects"
                ),
            )
        )

    if _requests_tracking(prompt):
        issues.append(
            ValidationIssue(
                code="semantic_tracking_unsupported",
                field=field,
                message=(
                    "Semantic windows cannot request per-object tracking or "
                    "trajectories; use a tracked rule instead"
                ),
            )
        )

    if condition.roi_id is not None:
        roi_value = condition.roi_id.root if hasattr(condition.roi_id, "root") else str(condition.roi_id)
        if calibration is None:
            issues.append(
                ValidationIssue(
                    code="missing_calibration",
                    severity="calibration",
                    field=f"conditions[{idx}].roi_id",
                    message="ROI reference requires a calibration",
                )
            )
        elif roi_value not in calibration.rois:
            issues.append(
                ValidationIssue(
                    code="missing_roi",
                    severity="calibration",
                    field=f"conditions[{idx}].roi_id",
                    message=f"ROI '{roi_value}' is not defined in the calibration",
                )
            )

    return issues


def _requests_exact_count(prompt: str) -> bool:
    """Detect whether a semantic prompt asks for exact counting of objects."""
    p = prompt.lower()
    count_markers = {
        "exactly",
        "precise count",
        "exact count",
        "count exactly",
        "count the",
        "number of",
        "how many",
    }
    countable_terms = {
        "car",
        "cars",
        "vehicle",
        "vehicles",
        "person",
        "people",
        "pedestrian",
        "pedestrians",
        "motorcycle",
        "motorcycles",
        "truck",
        "trucks",
        "bus",
        "buses",
    }
    has_count_marker = any(marker in p for marker in count_markers)
    has_countable = any(term in p for term in countable_terms)
    has_number = bool(re.search(r"\b\d+\b", p))
    return (has_count_marker and has_countable) or (has_count_marker and has_number and has_countable)


def _requests_tracking(prompt: str) -> bool:
    """Detect whether a semantic prompt asks for per-object tracking."""
    p = prompt.lower()
    return any(term in p for term in {"track", "trajectory", "path", "follow"})


def _calibration_confirmed(calibration: Calibration) -> bool:
    return calibration.confirmed_by is not None and calibration.confirmed_at is not None


def _build_capability_manifest(spec: AppSpec, registry: CapabilityRegistry) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if isinstance(spec, TrackedRulesSpec):
        for rule in spec.rules:
            entry = registry.capabilities.get(rule.capability_id)
            if entry is not None:
                manifest[rule.rule_id.root] = entry.capability_id
    elif isinstance(spec, SemanticWindowsSpec):
        for condition in spec.conditions:
            manifest[condition.condition_id.root] = "semantic.visible_condition"
    return manifest


def _build_model_manifest(spec: AppSpec, registry: CapabilityRegistry) -> dict[str, str]:
    components: set[str] = set()
    if isinstance(spec, TrackedRulesSpec):
        for rule in spec.rules:
            entry = registry.capabilities.get(rule.capability_id)
            if entry is not None:
                components.update(entry.requires)
    elif isinstance(spec, SemanticWindowsSpec):
        components.add("reasoner.window")

    manifest: dict[str, str] = {}
    for component in components:
        model = registry.models.get(component)
        if model is not None:
            manifest[component] = f"{model.provider}/{model.model}:{model.revision}"
    return manifest
