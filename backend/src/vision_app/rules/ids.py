"""Deterministic episode identifier generation."""
from __future__ import annotations

import hashlib


def episode_id(
    rule_id: str,
    track_id: str,
    kind: str,
    *values: int,
) -> str:
    """Return a stable short identifier for an episode.

    The identifier is a truncated SHA-256 over rule, track, episode kind and
    the ordered integer values that define the episode boundaries. Truncation
    is acceptable here because the identifier is scoped to a single run attempt
    and is never used as a cryptographic token.
    """
    base = ":".join([rule_id, track_id, kind, *(str(v) for v in values)])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
