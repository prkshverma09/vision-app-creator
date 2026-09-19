"""Builder-local ports and deterministic doubles.

The shared C0 ports define the external inspector/compiler/preview boundaries.  This
module adds the state and semantic-validator boundaries owned by the builder.
"""

from __future__ import annotations

from typing import Any, Protocol

from vision_app.contracts.models import AppSpec, BuildTurn
from vision_app.validation.validator import ValidationOutcome


class BuildTurnStore(Protocol):
    """Durable state boundary; composition supplies the real repository adapter."""

    async def save(self, turn: BuildTurn) -> None: ...
    async def get(self, turn_id: str) -> BuildTurn | None: ...


class SpecValidator(Protocol):
    def __call__(self, spec: AppSpec, **kwargs: Any) -> ValidationOutcome: ...


class InMemoryBuildTurnStore:
    """Component-test store. It never publishes versions or authorizes actions."""

    def __init__(self) -> None:
        self._turns: dict[str, BuildTurn] = {}

    async def save(self, turn: BuildTurn) -> None:
        self._turns[turn.id.root] = turn

    async def get(self, turn_id: str) -> BuildTurn | None:
        return self._turns.get(turn_id)
