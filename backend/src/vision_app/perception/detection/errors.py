"""Typed detection adapter errors."""
from __future__ import annotations


class DetectionError(Exception):
    """Base class for detector adapter failures."""


class CheckpointError(DetectionError):
    """Pinned checkpoint could not be loaded or its revision did not match."""


class ShapeError(DetectionError):
    """DecodedFrame RGB buffer did not match the declared dimensions/stride."""


class CoordinateError(DetectionError):
    """Backend emitted an invalid or unrecoverable box."""
