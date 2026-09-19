"""Persistence repository port extending the C0 Repository contract."""
from typing import Any, Protocol

from vision_app.contracts.models import DeliveryAttempt, Event, RunProgress
from vision_app.contracts.ports import Repository


class PersistenceRepository(Repository, Protocol):
    """Workspace-scoped durable store with atomic commands used across services."""

    # Generic ownership helpers extending the base C0 Repository.
    async def list_owned(self, kind: str, principal: Any) -> list[Any]: ...
    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool: ...

    # Budget / reservation primitives
    async def reserve_quota(
        self,
        workspace_id: str,
        owner_id: str,
        microusd: int,
        reservation_id: str,
        principal: Any,
    ) -> dict[str, Any] | None: ...
    async def release_reservation(self, reservation_id: str) -> bool: ...

    # Version / app lifecycle
    async def create_version(
        self,
        app_id: str,
        expected_revision: int,
        version: Any,
        principal: Any,
    ) -> tuple[bool, Any | None]: ...
    async def publish_version(
        self,
        app_id: str,
        version_id: str,
        expected_revision: int,
        principal: Any,
    ) -> bool: ...

    # Atomic reservation/run transaction
    async def reserve_quota_and_create_run(
        self,
        workspace_id: str,
        owner_id: str,
        microusd: int,
        reservation_id: str,
        run: Any,
        principal: Any,
        idempotency_key: str,
    ) -> tuple[bool, Any | None]: ...

    # Runs / attempts
    async def create_run(
        self,
        run: Any,
        principal: Any,
        idempotency_key: str,
        reservation_id: str,
    ) -> Any | None: ...
    async def claim_attempt(
        self, run_id: str, attempt_id: str, worker_id: str, fence: int
    ) -> bool: ...
    async def commit_event(
        self, run_id: str, attempt_id: str, fence: int, event: Event
    ) -> bool: ...
    async def commit_progress(
        self, run_id: str, attempt_id: str, fence: int, progress: RunProgress
    ) -> bool: ...
    async def finalize_run(
        self, run_id: str, attempt_id: str, outcome: str
    ) -> bool: ...
    async def review_event(
        self,
        run_id: str,
        event_id: str,
        expected_revision: int,
        review: str,
        principal: Any,
    ) -> Event | None: ...

    # Action outbox
    async def create_delivery(
        self, event_id: str, delivery: DeliveryAttempt, principal: Any
    ) -> tuple[bool, str | None]: ...
    async def claim_delivery(
        self, delivery_id: str, principal: Any
    ) -> DeliveryAttempt | None: ...
    async def mark_delivery_dispatched(
        self, delivery_id: str, principal: Any
    ) -> bool: ...

    # Deletion generation tracking
    async def request_deletion(
        self, kind: str, resource_id: str, expected_generation: int, principal: Any
    ) -> bool: ...
    async def bump_deletion_generation(
        self, kind: str, resource_id: str, principal: Any
    ) -> int: ...

    # Pagination helpers
    async def list_events(
        self,
        run_id: str,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[list[Event], tuple[int, str] | None]: ...
    async def list_progress(
        self,
        run_id: str,
        attempt_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> list[RunProgress]: ...
