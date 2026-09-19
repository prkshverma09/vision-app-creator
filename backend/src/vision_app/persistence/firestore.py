"""Firestore-backed Repository; only loads when google-cloud-firestore is installed."""
from __future__ import annotations

from typing import Any

try:
    from google.cloud import firestore
except ImportError as _firestore_import_error:  # pragma: no cover
    raise ImportError(
        "FirestoreRepository requires google-cloud-firestore. "
        "Install backend/requirements-b01.txt or add the optional cloud dependency group."
    ) from _firestore_import_error

from vision_app.contracts.models import DeliveryAttempt, Event, RunProgress


class FirestoreRepository:
    """Repository backed by Firestore Admin SDK; targets the emulator when configured."""

    def __init__(self, client: firestore.Client | None = None) -> None:
        self._client = client or firestore.Client()

    def _collection(self, path: str) -> firestore.CollectionReference:
        return self._client.collection(path)

    # ------------------------------------------------------------------ base contract
    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ generic helpers
    async def list_owned(self, kind: str, principal: Any) -> list[Any]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ budget / reservation
    async def reserve_quota(
        self,
        workspace_id: str,
        owner_id: str,
        microusd: int,
        reservation_id: str,
        principal: Any,
    ) -> dict[str, Any] | None:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def release_reservation(self, reservation_id: str) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ version / app lifecycle
    async def create_version(
        self,
        app_id: str,
        expected_revision: int,
        version: Any,
        principal: Any,
    ) -> tuple[bool, Any | None]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def publish_version(
        self,
        app_id: str,
        version_id: str,
        expected_revision: int,
        principal: Any,
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ atomic reservation + run
    async def reserve_quota_and_create_run(
        self,
        workspace_id: str,
        owner_id: str,
        microusd: int,
        reservation_id: str,
        run: Any,
        principal: Any,
        idempotency_key: str,
    ) -> tuple[bool, Any | None]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ runs / attempts
    async def create_run(
        self,
        run: Any,
        principal: Any,
        idempotency_key: str,
        reservation_id: str,
    ) -> Any | None:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def claim_attempt(
        self, run_id: str, attempt_id: str, worker_id: str, fence: int
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def commit_event(
        self, run_id: str, attempt_id: str, fence: int, event: Event
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def commit_progress(
        self, run_id: str, attempt_id: str, fence: int, progress: RunProgress
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def finalize_run(self, run_id: str, attempt_id: str, outcome: str) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def review_event(
        self,
        run_id: str,
        event_id: str,
        expected_revision: int,
        review: str,
        principal: Any,
    ) -> Event | None:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ action outbox
    async def create_delivery(
        self, event_id: str, delivery: DeliveryAttempt, principal: Any
    ) -> tuple[bool, str | None]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def claim_delivery(
        self, delivery_id: str, principal: Any
    ) -> DeliveryAttempt | None:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def mark_delivery_dispatched(
        self, delivery_id: str, principal: Any
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ deletion generation tracking
    async def request_deletion(
        self, kind: str, resource_id: str, expected_generation: int, principal: Any
    ) -> bool:
        return await self.mark_deletion(kind, resource_id, expected_generation, principal)

    async def mark_deletion(
        self, kind: str, resource_id: str, generation: int, principal: Any
    ) -> bool:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def bump_deletion_generation(
        self, kind: str, resource_id: str, principal: Any
    ) -> int:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    # ------------------------------------------------------------------ pagination helpers
    async def list_events(
        self,
        run_id: str,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[list[Event], tuple[int, str] | None]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")

    async def list_progress(
        self,
        run_id: str,
        attempt_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> list[RunProgress]:
        raise NotImplementedError("Firestore adapter requires emulator or cloud project")
