"""Opaque, non-path resource identifiers."""

from __future__ import annotations

import base64
import secrets


_PREFIX = "med"
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


def make_opaque_id(prefix: str = _PREFIX) -> str:
    """Return a short, URL-safe opaque identifier that cannot be interpreted as a path."""
    token = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
    return f"{prefix}_{token}"


def is_safe_opaque_id(value: str) -> bool:
    """True if ``value`` contains no path separators or traversal components."""
    if not value or value in {".", ".."}:
        return False
    return all(c in _ALPHABET for c in value)
