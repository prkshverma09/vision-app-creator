"""Installed-capability registry for semantic spec validation.

The registry lists the supported model, detection, tracking, reasoning,
signal, and action capabilities that the runtime can actually execute,
together with the allowed combinations and installed component set.
It is read-only at runtime; the canonical capability vocabulary lives in
``vision_app.contracts.capabilities`` (C0), and this module extends it with
metadata needed by the validator (model revisions, action vocabulary,
execution limits).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vision_app.contracts.capabilities import CAPABILITIES, INSTALLED_COMPONENTS
from vision_app.contracts.models import ExecutionLimits


@dataclass(frozen=True)
class CapabilityEntry:
    """A supported app capability and its runtime requirements."""

    capability_id: str
    mode: Literal["tracked_rules", "semantic_windows"]
    requires: frozenset[str]
    supported_classes: frozenset[str]


@dataclass(frozen=True)
class ModelCapability:
    """An installed model / detection / tracking / reasoning component."""

    component_id: str
    provider: str
    model: str
    revision: str


@dataclass(frozen=True)
class ActionCapability:
    """An action capability that may be referenced by an approved permission.

    Action refs stored on a spec are opaque resource IDs pointing to an
    externally approved authorization record.  The validator only checks that
    the referenced permission exists; it never treats the spec itself as proof
    of authorization.
    """

    action_id: str
    requires_external_approval: bool = True


@dataclass(frozen=True)
class CapabilityRegistry:
    """Read-only registry of installed capabilities, models, and actions."""

    capabilities: dict[str, CapabilityEntry]
    models: dict[str, ModelCapability]
    actions: frozenset[str] = frozenset()
    installed_components: frozenset[str] = frozenset()
    max_limits: ExecutionLimits = ExecutionLimits()

    def capability_ids(self) -> frozenset[str]:
        return frozenset(self.capabilities.keys())

    def components(self) -> frozenset[str]:
        return self.installed_components

    def combinations_are_consistent(self) -> bool:
        """Every capability references only installed components and uses a known mode."""
        return all(
            entry.capability_id == key
            and entry.mode in {"tracked_rules", "semantic_windows"}
            and entry.requires <= self.installed_components
            for key, entry in self.capabilities.items()
        )


REGISTRY = CapabilityRegistry(
    capabilities={
        key: CapabilityEntry(
            capability_id=cap.id,
            mode=cap.mode,  # type: ignore[arg-type]
            requires=cap.requires,
            supported_classes=cap.supported_classes,
        )
        for key, cap in CAPABILITIES.items()
    },
    models={
        "detector.common": ModelCapability(
            component_id="detector.common", provider="roboflow", model="rf-detr-small", revision="v1"
        ),
        "tracker.bytetrack": ModelCapability(
            component_id="tracker.bytetrack", provider="roboflow", model="bytetrack", revision="v1"
        ),
        "signal.roi": ModelCapability(
            component_id="signal.roi", provider="vision_app", model="signal_roi_classifier", revision="v1"
        ),
        "reasoner.window": ModelCapability(
            component_id="reasoner.window", provider="google", model="gemini-3.8-flash", revision="v1"
        ),
    },
    actions=frozenset(
        {
            "action.in_app_event",
            "action.webhook_preview",
            "action.webhook_dispatch",
        }
    ),
    installed_components=INSTALLED_COMPONENTS,
    max_limits=ExecutionLimits(),
)
