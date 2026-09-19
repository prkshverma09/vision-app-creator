"""Evidence extraction errors."""


class EvidenceError(Exception):
    """Base class for evidence artifact extraction failures."""

    code = "evidence_error"


class StaleSourceError(EvidenceError):
    """The source generation/tombstone changed; artifacts must not be registered."""

    code = "stale_source"


class EvidenceRangeError(EvidenceError):
    """The requested evidence window lies entirely outside the source media."""

    code = "evidence_range"
