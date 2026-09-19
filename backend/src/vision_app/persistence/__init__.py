"""Persistence adapters implementing the Repository port."""
from .errors import ConflictError, NotFoundError, PersistenceError
from .memory import InMemoryRepository
from .models import EventCursor, collection_path

__all__ = [
    "InMemoryRepository",
    "ConflictError",
    "NotFoundError",
    "PersistenceError",
    "EventCursor",
    "collection_path",
]

try:
    from .firestore import FirestoreRepository
    __all__.append("FirestoreRepository")
except ImportError:  # pragma: no cover - optional cloud adapter
    FirestoreRepository = None  # type: ignore[misc, assignment]
