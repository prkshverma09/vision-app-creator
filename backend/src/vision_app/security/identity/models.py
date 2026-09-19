"""Authenticated identity values shared by API authorization boundaries."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity derived exclusively from a successfully verified token."""

    user_id: str
    email: str | None
    workspace_ids: frozenset[str]

    def is_member(self, workspace_id: str) -> bool:
        return workspace_id in self.workspace_ids
