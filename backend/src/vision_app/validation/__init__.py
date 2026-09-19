"""Semantic spec validation and capability registry."""

from vision_app.validation.registry import (
    ActionCapability,
    CapabilityEntry,
    CapabilityRegistry,
    ModelCapability,
    REGISTRY,
)
from vision_app.validation.validator import (
    ValidationIssue,
    ValidationOutcome,
    validate_app_spec,
)

__all__ = [
    "ActionCapability",
    "CapabilityEntry",
    "CapabilityRegistry",
    "ModelCapability",
    "REGISTRY",
    "ValidationIssue",
    "ValidationOutcome",
    "validate_app_spec",
]
