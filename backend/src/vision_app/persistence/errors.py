"""Persistence-level errors surfaced to callers."""


class PersistenceError(RuntimeError):
    """Base for repository failures."""


class ConflictError(PersistenceError):
    """Optimistic concurrency or duplicate identifier."""


class NotFoundError(PersistenceError):
    """Missing or inaccessible resource."""
