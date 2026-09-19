"""Internal persistence helpers and error types."""
import base64
import json
from dataclasses import dataclass

from vision_app.persistence.errors import ConflictError, NotFoundError, PersistenceError


__all__ = [
    "ConflictError",
    "NotFoundError",
    "PersistenceError",
    "EventCursor",
    "collection_path",
]


@dataclass(frozen=True)
class EventCursor:
    source_time_ms: int
    event_id: str

    def encode(self) -> str:
        payload = json.dumps({"t": self.source_time_ms, "e": self.event_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "EventCursor":
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return cls(source_time_ms=payload["t"], event_id=payload["e"])


def collection_path(kind: str, workspace_id: str, parent: tuple[str, str] | None = None) -> str:
    """Return a Firestore-style workspace-scoped collection path."""
    if parent:
        return f"workspaces/{workspace_id}/{parent[0]}/{parent[1]}/{kind}"
    return f"workspaces/{workspace_id}/{kind}"
