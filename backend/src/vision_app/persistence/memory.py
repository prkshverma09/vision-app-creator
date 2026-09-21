"""In-memory Repository implementation for component tests and local profiles."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, fields
from typing import Any, cast

from vision_app.contracts.models import DeliveryAttempt, Event, ResourceId, RunProgress
from vision_app.security.identity.models import Principal

from .errors import ConflictError, NotFoundError


@dataclass(slots=True)
class _Doc:
    value: Any
    revision: int = 0
    generation: int = 1
    deleted: bool = False


class InMemoryRepository:
    """Thread-safe in-memory repository conforming to the Repository port.

    All writes are serialized with a single asyncio lock, which gives the same atomicity
    guarantees as Firestore transactions for in-process tests.
    """

    def __init__(self) -> None:
        # workspace_id -> collection -> doc_id -> _Doc
        self._store: dict[str, dict[str, dict[str, _Doc]]] = {}
        self._lock = asyncio.Lock()
        # idempotency: (workspace_id, collection, key) -> doc_id
        self._idempotency: dict[tuple[str, str, str], str] = {}
        # budget: workspace_id -> available microusd
        self._budgets: dict[str, int] = {}
        # reservation_id -> (workspace_id, microusd)
        self._reservations: dict[str, tuple[str, int]] = {}
        # run_id -> current attempt_id
        self._run_active_attempts: dict[str, str] = {}
        # run_id -> monotonic fence
        self._run_fences: dict[str, int] = {}
        # (run_id, attempt_id) -> worker_id (recordkeeping)
        self._attempt_workers: dict[tuple[str, str], str] = {}
        # run_id -> selected_attempt_id
        self._selected_attempts: dict[str, str] = {}

    # ------------------------------------------------------------------ testing helpers
    def _seed_budget(self, workspace_id: str, microusd: int) -> None:
        self._budgets[workspace_id] = microusd

    # ------------------------------------------------------------------ ownership resolution
    async def resolve_workspace(self, kind: str, resource_id: str) -> str | None:
        """Return the workspace that owns ``resource_id`` in collection ``kind``.

        This is an integration helper for the local in-memory adapter; production
        Firestore uses indexed queries instead.
        """
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None or found[1].deleted:
                return None
            return found[0]

    def _coerce_principal(self, principal: Any) -> Principal | None:
        """Accept either a Principal or a workspace-id string used by routers.

        Integration tests compose the repository with services that pass the
        workspace string as the ``principal`` argument; composition tests use real
        Principal instances.
        """
        if isinstance(principal, Principal):
            return principal
        if isinstance(principal, str):
            return Principal(principal, None, frozenset({principal}))
        return None

    # ------------------------------------------------------------------ internal helpers
    def _workspace(self, value: Any) -> str | None:
        if isinstance(value, dict):
            return cast(str | None, value.get("workspace_id"))
        if hasattr(value, "workspace_id"):
            ws = getattr(value, "workspace_id")
            if hasattr(ws, "root"):
                return cast(str, ws.root)
            return cast(str, ws)
        return None

    def _id(self, value: Any) -> str | None:
        if isinstance(value, dict):
            return cast(str | None, value.get("id") or value.get("run_id"))
        if hasattr(value, "id"):
            id_val = getattr(value, "id")
            if hasattr(id_val, "root"):
                return cast(str, id_val.root)
            return cast(str, id_val)
        if hasattr(value, "run_id"):
            id_val = getattr(value, "run_id")
            if hasattr(id_val, "root"):
                return cast(str, id_val.root)
            return cast(str, id_val)
        return None

    def _ensure(self, workspace_id: str, collection: str) -> dict[str, _Doc]:
        return self._store.setdefault(workspace_id, {}).setdefault(collection, {})

    def _find_doc(self, collection: str, doc_id: str) -> tuple[str, _Doc] | None:
        for workspace_id, cols in self._store.items():
            doc = cols.get(collection, {}).get(doc_id)
            if doc is not None:
                return workspace_id, doc
        return None

    def _is_owned(self, doc: _Doc, principal: Any) -> bool:
        principal = self._coerce_principal(principal)
        if principal is None:
            return False
        workspace_id = self._workspace(doc.value)
        if workspace_id is None:
            return False
        return bool(principal.is_member(workspace_id))

    def _clone(self, value: Any) -> Any:
        return copy.deepcopy(value)

    def _with_field(self, value: Any, field: str, new_value: Any) -> Any:
        """Return a shallow copy of a dataclass or Pydantic model with one field changed."""
        if hasattr(value, "model_copy"):
            return value.model_copy(update={field: new_value})
        if hasattr(value, "__dataclass_fields__"):
            kwargs = {f.name: getattr(value, f.name) for f in fields(value)}
            kwargs[field] = new_value
            return type(value)(**kwargs)
        raise TypeError(f"cannot update field {field} on {type(value)}")

    # ------------------------------------------------------------------ base Repository contract
    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any | None:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None:
                return None
            workspace_id, doc = found
            if principal is None:
                return None
            if not principal.is_member(workspace_id) or doc.deleted:
                return None
            return self._clone(doc.value)

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None:
                if revision != 0:
                    return False
                workspace_id = self._workspace(value)
                if workspace_id is None:
                    raise ValueError(
                        f"value for {kind}/{resource_id} has no workspace_id"
                    )
                docs = self._ensure(workspace_id, kind)
                if resource_id in docs:
                    return False
                generation = 1
                if isinstance(value, dict):
                    generation = value.get("generation", 1)
                elif hasattr(value, "generation"):
                    gen_val = getattr(value, "generation")
                    generation = gen_val.root if hasattr(gen_val, "root") else gen_val
                doc_revision = 0
                if isinstance(value, dict):
                    doc_revision = value.get("revision", 0)
                elif hasattr(value, "revision"):
                    rev_val = getattr(value, "revision")
                    doc_revision = rev_val.root if hasattr(rev_val, "root") else rev_val
                docs[resource_id] = _Doc(
                    value=self._clone(value), revision=doc_revision, generation=generation
                )
                return True
            workspace_id, doc = found
            if doc.revision != revision or doc.deleted:
                return False
            if kind == "versions":
                raise ConflictError("versions are immutable")
            doc.value = self._clone(value)
            doc.revision = revision + 1
            return True

    # ------------------------------------------------------------------ generic ownership helpers
    async def delete_owned(
        self, kind: str, resource_id: str, principal: Principal
    ) -> bool:
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None:
                return False
            workspace_id, doc = found
            if not principal.is_member(workspace_id) or doc.deleted:
                return False
            doc.deleted = True
            doc.revision += 1
            doc.generation += 1
            return True

    async def list_owned(self, kind: str, principal: Any) -> list[Any]:
        principal = self._coerce_principal(principal)
        async with self._lock:
            if principal is None:
                return []
            items: list[Any] = []
            for workspace_id in principal.workspace_ids:
                for doc in self._ensure(workspace_id, kind).values():
                    if not doc.deleted:
                        items.append(self._clone(doc.value))
            return items

    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool:
        async with self._lock:
            workspace_id = self._workspace(value)
            if workspace_id is None:
                raise ValueError(f"value for {kind}/{resource_id} has no workspace_id")
            docs = self._ensure(workspace_id, kind)
            if resource_id in docs:
                return False
            generation = 1
            revision = 0
            if isinstance(value, dict):
                generation = value.get("generation", 1)
                revision = value.get("revision", 0)
            elif hasattr(value, "generation"):
                gen_val = getattr(value, "generation")
                generation = gen_val.root if hasattr(gen_val, "root") else gen_val
            if hasattr(value, "revision"):
                rev_val = getattr(value, "revision")
                revision = rev_val.root if hasattr(rev_val, "root") else rev_val
            docs[resource_id] = _Doc(
                value=self._clone(value), revision=revision, generation=generation
            )
            return True

    # ------------------------------------------------------------------ budget / reservation
    async def reserve_quota(
        self,
        workspace_id: str,
        owner_id: str,
        microusd: int,
        reservation_id: str,
        principal: Any,
    ) -> dict[str, Any] | None:
        principal = self._coerce_principal(principal)
        if principal is None or not principal.is_member(workspace_id):
            return None
        async with self._lock:
            if reservation_id in self._reservations:
                return {"reservation_id": reservation_id, "workspace_id": workspace_id}
            available = self._budgets.get(workspace_id, 0)
            if available < microusd:
                return None
            self._budgets[workspace_id] = available - microusd
            self._reservations[reservation_id] = (workspace_id, microusd)
            return {"reservation_id": reservation_id, "workspace_id": workspace_id}

    async def release_reservation(self, reservation_id: str) -> bool:
        async with self._lock:
            entry = self._reservations.pop(reservation_id, None)
            if entry is None:
                return False
            workspace_id, microusd = entry
            self._budgets[workspace_id] = self._budgets.get(workspace_id, 0) + microusd
            return True

    # ------------------------------------------------------------------ version / app lifecycle
    async def create_version(
        self,
        app_id: str,
        expected_revision: int,
        version: Any,
        principal: Any,
    ) -> tuple[bool, Any | None]:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc("apps", app_id)
            if found is None:
                return False, None
            workspace_id, app_doc = found
            if principal is None or not principal.is_member(workspace_id):
                return False, None
            if app_doc.revision != expected_revision or app_doc.deleted:
                return False, None
            version_id = self._id(version)
            if version_id is None:
                raise ValueError("version has no id")
            versions = self._ensure(workspace_id, "versions")
            if version_id in versions:
                return False, None
            versions[version_id] = _Doc(value=self._clone(version))
            updated = self._with_field(
                app_doc.value, "draft_version_id", ResourceId(version_id)
            )
            updated = self._with_field(updated, "revision", expected_revision + 1)
            app_doc.value = updated
            app_doc.revision = expected_revision + 1
            return True, self._clone(app_doc.value)

    async def publish_version(
        self,
        app_id: str,
        version_id: str,
        expected_revision: int,
        principal: Any,
    ) -> bool:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc("apps", app_id)
            if found is None:
                return False
            workspace_id, app_doc = found
            if principal is None or not principal.is_member(workspace_id):
                return False
            if app_doc.revision != expected_revision or app_doc.deleted:
                return False
            version_doc = self._ensure(workspace_id, "versions").get(version_id)
            if version_doc is None or version_doc.deleted:
                return False
            updated = self._with_field(
                app_doc.value, "published_version_id", ResourceId(version_id)
            )
            updated = self._with_field(updated, "revision", expected_revision + 1)
            app_doc.value = updated
            app_doc.revision = expected_revision + 1
            return True

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
        principal = self._coerce_principal(principal)
        if principal is None or not principal.is_member(workspace_id):
            return False, None
        async with self._lock:
            idem_key = (workspace_id, "run", idempotency_key)
            existing_id = self._idempotency.get(idem_key)
            if existing_id is not None:
                doc = self._ensure(workspace_id, "run").get(existing_id)
                return True, self._clone(doc.value) if doc is not None else None

            available = self._budgets.get(workspace_id, 0)
            if available < microusd:
                return False, None

            run_id = self._id(run)
            if run_id is None:
                raise ValueError("run has no id")
            runs = self._ensure(workspace_id, "run")
            if run_id in runs:
                return False, None

            self._budgets[workspace_id] = available - microusd
            self._reservations[reservation_id] = (workspace_id, microusd)
            runs[run_id] = _Doc(value=self._clone(run))
            self._idempotency[idem_key] = run_id
            return True, self._clone(run)

    # ------------------------------------------------------------------ runs / attempts
    async def create_run(
        self,
        run: Any,
        principal: Any,
        idempotency_key: str,
        reservation_id: str,
    ) -> Any | None:
        workspace_id = self._workspace(run)
        if workspace_id is None:
            return None
        principal = self._coerce_principal(principal)
        if principal is None or not principal.is_member(workspace_id):
            return None
        async with self._lock:
            idem_key = (workspace_id, "run", idempotency_key)
            existing_id = self._idempotency.get(idem_key)
            if existing_id is not None:
                doc = self._ensure(workspace_id, "run").get(existing_id)
                return self._clone(doc.value) if doc is not None else None

            run_id = self._id(run)
            if run_id is None:
                return None
            runs = self._ensure(workspace_id, "run")
            if run_id in runs:
                return None

            runs[run_id] = _Doc(value=self._clone(run))
            self._idempotency[idem_key] = run_id
            return self._clone(run)

    async def claim_attempt(
        self, run_id: str, attempt_id: str, worker_id: str, fence: int
    ) -> bool:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                return False
            workspace_id, doc = found
            key = (run_id, attempt_id)
            current_run_fence = self._run_fences.get(run_id, 0)
            existing_worker = self._attempt_workers.get(key)
            if existing_worker is not None and fence < current_run_fence:
                return False
            # Claiming a new attempt bumps the run fence past any previous active attempt.
            new_fence = max(fence, current_run_fence + 1)
            self._run_fences[run_id] = new_fence
            self._run_active_attempts[run_id] = attempt_id
            self._attempt_workers[key] = worker_id
            # Update the run document's attempt_id only if the schema includes it.
            if isinstance(doc.value, dict) and "attempt_id" in doc.value:
                doc.value["attempt_id"] = attempt_id
            elif hasattr(doc.value, "attempt_id"):
                doc.value = self._with_field(doc.value, "attempt_id", attempt_id)
            return True

    async def commit_event(
        self, run_id: str, attempt_id: str, fence: int, event: Event
    ) -> bool:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                return False
            workspace_id, _ = found
            if self._run_active_attempts.get(run_id) != attempt_id:
                return False
            current_fence = self._run_fences.get(run_id, 0)
            if fence < current_fence:
                return False
            self._run_fences[run_id] = fence
            events = self._ensure(workspace_id, "events")
            event_id = event.id.root
            events[event_id] = _Doc(value=self._clone(event), revision=event.revision)
            return True

    async def commit_progress(
        self, run_id: str, attempt_id: str, fence: int, progress: RunProgress
    ) -> bool:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                return False
            workspace_id, _ = found
            if self._run_active_attempts.get(run_id) != attempt_id:
                return False
            current_fence = self._run_fences.get(run_id, 0)
            if fence < current_fence:
                return False
            self._run_fences[run_id] = fence
            progress_collection = self._ensure(workspace_id, "run_progress")
            progress_key = f"{run_id}:{attempt_id}:{progress.sequence}"
            progress_collection[progress_key] = _Doc(
                value=self._clone(progress), revision=progress.sequence
            )
            return True

    async def finalize_run(self, run_id: str, attempt_id: str, outcome: str) -> bool:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                return False
            workspace_id, doc = found
            if self._run_active_attempts.get(run_id) != attempt_id:
                return False
            self._selected_attempts[run_id] = attempt_id
            value = doc.value
            if isinstance(value, dict):
                value["selected_attempt_id"] = attempt_id
            else:
                value = self._with_field(value, "selected_attempt_id", attempt_id)
            doc.value = value
            return True

    async def review_event(
        self,
        run_id: str,
        event_id: str,
        expected_revision: int,
        review: str,
        principal: Any,
    ) -> Event | None:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                return None
            workspace_id, _ = found
            if principal is None or not principal.is_member(workspace_id):
                return None
            events = self._ensure(workspace_id, "events")
            doc = events.get(event_id)
            if doc is None or doc.revision != expected_revision:
                return None
            event: Event = self._clone(doc.value)
            event = event.model_copy(
                update={"human_review": review, "revision": event.revision + 1}
            )
            doc.value = event
            doc.revision = event.revision
            return cast(Event, self._clone(event))

    # ------------------------------------------------------------------ action outbox
    async def create_delivery(
        self, event_id: str, delivery: DeliveryAttempt, principal: Any
    ) -> tuple[bool, str | None]:
        principal = self._coerce_principal(principal)
        async with self._lock:
            event_found = self._find_doc("events", event_id)
            if event_found is None:
                return False, None
            workspace_id, _ = event_found
            if principal is None or not principal.is_member(workspace_id):
                return False, None
            deliveries = self._ensure(workspace_id, "deliveries")
            delivery_id = delivery.id.root
            if delivery_id in deliveries:
                return False, None
            deliveries[delivery_id] = _Doc(value=self._clone(delivery))
            return True, delivery_id

    async def claim_delivery(
        self, delivery_id: str, principal: Any
    ) -> DeliveryAttempt | None:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc("deliveries", delivery_id)
            if found is None:
                return None
            workspace_id, doc = found
            if principal is None or not principal.is_member(workspace_id):
                return None
            delivery: DeliveryAttempt = self._clone(doc.value)
            if delivery.state != "pending":
                return None
            delivery = delivery.model_copy(update={"state": "dispatched"})
            doc.value = delivery
            return cast(DeliveryAttempt, self._clone(delivery))

    async def mark_delivery_dispatched(
        self, delivery_id: str, principal: Any
    ) -> bool:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc("deliveries", delivery_id)
            if found is None:
                return False
            workspace_id, doc = found
            if principal is None or not principal.is_member(workspace_id):
                return False
            delivery: DeliveryAttempt = doc.value
            if delivery.state != "pending":
                return False
            doc.value = delivery.model_copy(update={"state": "dispatched"})
            return True

    # ------------------------------------------------------------------ deletion generation tracking
    async def request_deletion(
        self, kind: str, resource_id: str, expected_generation: int, principal: Any
    ) -> bool:
        return await self.mark_deletion(kind, resource_id, expected_generation, principal)

    async def mark_deletion(
        self, kind: str, resource_id: str, generation: int, principal: Any
    ) -> bool:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None:
                return False
            workspace_id, doc = found
            if principal is None or not principal.is_member(workspace_id):
                return False
            if doc.generation != generation or doc.deleted:
                return False
            doc.generation = generation + 1
            if isinstance(doc.value, dict):
                doc.value["state"] = "deleting"
                doc.value["generation"] = doc.generation
            elif hasattr(doc.value, "model_copy"):
                doc.value = doc.value.model_copy(
                    update={"state": "deleting", "generation": doc.generation}
                )
            return True

    async def bump_deletion_generation(
        self, kind: str, resource_id: str, principal: Any
    ) -> int:
        principal = self._coerce_principal(principal)
        async with self._lock:
            found = self._find_doc(kind, resource_id)
            if found is None:
                raise NotFoundError(f"{kind}/{resource_id} not found")
            workspace_id, doc = found
            if principal is None or not principal.is_member(workspace_id):
                raise NotFoundError(f"{kind}/{resource_id} not found")
            doc.generation += 1
            if isinstance(doc.value, dict):
                doc.value["generation"] = doc.generation
            elif hasattr(doc.value, "model_copy"):
                doc.value = doc.value.model_copy(update={"generation": doc.generation})
            return doc.generation

    # ------------------------------------------------------------------ pagination helpers
    async def list_events(
        self,
        run_id: str,
        after: tuple[int, str] | None = None,
        limit: int = 50,
    ) -> tuple[list[Event], tuple[int, str] | None]:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                raise NotFoundError(f"run/{run_id} not found")
            workspace_id, _ = found
            events = self._ensure(workspace_id, "events").values()
            items = [self._clone(doc.value) for doc in events if not doc.deleted]
            items.sort(key=lambda e: (e.source_range.start_ms.root, e.id.root))
            if after is not None:
                items = [e for e in items if (e.source_range.start_ms.root, e.id.root) > after]
            page = items[:limit]
            next_cursor: tuple[int, str] | None = None
            if len(items) > limit:
                last = page[-1]
                next_cursor = (last.source_range.start_ms.root, last.id.root)
            return page, next_cursor

    async def list_progress(
        self,
        run_id: str,
        attempt_id: str,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> list[RunProgress]:
        async with self._lock:
            found = self._find_doc("run", run_id)
            if found is None:
                raise NotFoundError(f"run/{run_id} not found")
            workspace_id, _ = found
            progress_col = self._ensure(workspace_id, "run_progress")
            after = after_sequence if after_sequence is not None else -1
            prefix = f"{run_id}:{attempt_id}:"
            items = [
                self._clone(doc.value)
                for key, doc in progress_col.items()
                if key.startswith(prefix) and doc.value.sequence > after and not doc.deleted
            ]
            items.sort(key=lambda p: p.sequence)
            return items[:limit]
