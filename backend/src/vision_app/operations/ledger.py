"""Canonical repository-backed budget accounting.

The service deliberately owns no mutable budget counter. Every decision is made by a
compare-and-swap over the repository account document, so competing service instances
observe the same reservations.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any

from vision_app.contracts.ports import IdFactory, Repository

_ACCOUNT_KIND = "budget_account"
_MAX_CAS_ATTEMPTS = 100


class BudgetError(RuntimeError):
    """Base class for budget failures."""


class BudgetExceeded(BudgetError):
    """The reservation would exceed the owner's configured monetary budget."""


class ReservationNotFound(BudgetError):
    """The reservation does not exist or has already reached a terminal state."""


class BudgetContention(BudgetError):
    """The repository could not commit after bounded optimistic retries."""


@dataclass(frozen=True)
class BudgetSnapshot:
    limit_microusd: int
    estimated_total_microusd: int
    estimated_reserved_microusd: int
    measured_microusd: int
    released_microusd: int
    active_reservations: int


class BudgetLedgerService:
    """Atomic monetary reservations and measured settlement over ``Repository``."""

    def __init__(self, repository: Repository, ids: IdFactory, *, budget_microusd: int) -> None:
        if budget_microusd < 0:
            raise ValueError("budget_microusd must be nonnegative")
        self._repository = repository
        self._ids = ids
        self._limit = budget_microusd

    async def reserve(self, owner_id: str, microusd: int) -> str:
        if not owner_id:
            raise ValueError("owner_id is required")
        if microusd <= 0:
            raise ValueError("reservation must be positive")
        reservation_id = self._reservation_id(owner_id)

        def mutate(state: dict[str, Any]) -> None:
            committed = int(state["measured_microusd"])
            reserved = sum(int(item) for item in state["reservations"].values())
            if committed + reserved + microusd > int(state["limit_microusd"]):
                raise BudgetExceeded("budget exhausted")
            state["estimated_total_microusd"] += microusd
            state["reservations"][reservation_id] = microusd

        await self._update(owner_id, mutate)
        return reservation_id

    async def settle(self, reservation_id: str, actual_microusd: int) -> None:
        if actual_microusd < 0:
            raise ValueError("actual usage must be nonnegative")
        owner_id = self._owner_from_reservation(reservation_id)

        def mutate(state: dict[str, Any]) -> None:
            estimated = state["reservations"].pop(reservation_id, None)
            if estimated is None:
                raise ReservationNotFound(reservation_id)
            state["measured_microusd"] += actual_microusd
            state["released_microusd"] += max(0, int(estimated) - actual_microusd)

        await self._update(owner_id, mutate)

    async def release(self, reservation_id: str) -> None:
        owner_id = self._owner_from_reservation(reservation_id)

        def mutate(state: dict[str, Any]) -> None:
            estimated = state["reservations"].pop(reservation_id, None)
            if estimated is None:
                raise ReservationNotFound(reservation_id)
            state["released_microusd"] += int(estimated)

        await self._update(owner_id, mutate)

    async def cancel(
        self,
        in_flight: list[tuple[str, int]],
        not_started: list[str],
    ) -> None:
        """Settle unavoidable calls and release only work that never started."""
        for reservation_id, measured in in_flight:
            await self.settle(reservation_id, measured)
        for reservation_id in not_started:
            await self.release(reservation_id)

    async def snapshot(self, owner_id: str) -> BudgetSnapshot:
        state = await self._read(owner_id)
        reservations = state["reservations"]
        return BudgetSnapshot(
            limit_microusd=int(state["limit_microusd"]),
            estimated_total_microusd=int(state["estimated_total_microusd"]),
            estimated_reserved_microusd=sum(int(value) for value in reservations.values()),
            measured_microusd=int(state["measured_microusd"]),
            released_microusd=int(state["released_microusd"]),
            active_reservations=len(reservations),
        )

    async def _read(self, owner_id: str) -> dict[str, Any]:
        stored = await self._repository.get_owned(_ACCOUNT_KIND, owner_id, owner_id)
        if stored is None:
            return self._initial_state(owner_id)
        if not isinstance(stored, dict):
            raise BudgetError("invalid repository budget state")
        return stored

    async def _update(self, owner_id: str, mutate: Any) -> None:
        for _ in range(_MAX_CAS_ATTEMPTS):
            state = await self._read(owner_id)
            revision = int(state["revision"])
            mutate(state)
            state["revision"] = revision + 1
            if await self._repository.compare_and_swap(
                _ACCOUNT_KIND, owner_id, revision, state
            ):
                return
        raise BudgetContention("budget account remained contended")

    def _initial_state(self, owner_id: str = "") -> dict[str, Any]:
        return {
            "revision": 0,
            "workspace_id": owner_id,
            "limit_microusd": self._limit,
            "estimated_total_microusd": 0,
            "measured_microusd": 0,
            "released_microusd": 0,
            "reservations": {},
        }

    def _reservation_id(self, owner_id: str) -> str:
        owner = urlsafe_b64encode(owner_id.encode()).decode().rstrip("=")
        return f"{owner}.{self._ids.new('reservation')}"

    @staticmethod
    def _owner_from_reservation(reservation_id: str) -> str:
        try:
            encoded, _ = reservation_id.split(".", 1)
            return urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        except (ValueError, UnicodeDecodeError) as error:
            raise ReservationNotFound(reservation_id) from error
