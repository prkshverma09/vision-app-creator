"""Explicit, atomic JSON snapshots for the single-process local profile."""
from __future__ import annotations

import asyncio
import copy
import itertools
import json
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from vision_app.api.runs.router import RunRecord
from vision_app.contracts.models import (
    AppVersion,
    BuildTurn,
    Calibration,
    DeliveryAttempt,
    Event,
    MoneyMicrousd,
    ResourceId,
    RunProgress,
    SourceAsset,
    VisionApp,
)

from .memory import InMemoryRepository, _Doc

_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        VisionApp, AppVersion, Calibration, SourceAsset, Event, RunProgress,
        DeliveryAttempt, BuildTurn,
    )
}
_BINDINGS = ("app_sources", "app_calibrations", "app_seed_assets")
_TERMINAL = {"completed", "partial", "failed", "cancelled"}
_SECRET_FIELDS = {
    "api_key", "gemini_api_key", "authorization", "password", "secret", "secrets",
    "access_token", "refresh_token", "test_token", "credentials", "private_key",
    "upload_url", "read_url", "grant_id", "token", "client_secret", "signing_key",
}


class SnapshotError(RuntimeError):
    """Local state could not be safely saved or restored; existing state is retained."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Value(_StrictModel):
    type: str
    value: Any


class _Document(_StrictModel):
    workspace: str
    collection: str
    id: str
    revision: int = Field(ge=0)
    generation: int = Field(ge=1)
    deleted: bool
    value: _Value


class _CoreState(_StrictModel):
    documents: list[_Document]
    idempotency: list[tuple[str, str, str, str]]
    budgets: dict[str, int]
    reservations: dict[str, tuple[str, int]]
    run_active_attempts: dict[str, str]
    run_fences: dict[str, int]
    attempt_workers: list[tuple[str, str, str]]
    selected_attempts: dict[str, str]


class _Job(_StrictModel):
    revision: int = Field(ge=0)
    run_id: str
    state: Literal[
        "queued", "dispatching", "dispatched", "running", "completed", "partial",
        "failed", "cancelled",
    ]
    invocation_id: str | None
    cancel_requested: bool
    attempt_id: str | None
    fence: int = Field(ge=0)
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    progress_sequence: int = Field(ge=-1)
    failure_reason: str | None = None


class _Snapshot(_StrictModel):
    format_version: Literal[1]
    core: _CoreState
    media_assets: dict[str, _Value]
    media_revisions: dict[str, int]
    bindings: dict[str, dict[str, str]]
    jobs: dict[str, _Job]
    next_id: int | None = Field(default=None, ge=1)


def _check_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("snapshot mappings require string keys")
            if key.lower().replace("-", "_") in _SECRET_FIELDS:
                raise ValueError("credential or ephemeral grant fields cannot be snapshotted")
            _check_fields(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _check_fields(item)
    elif isinstance(value, float) and not isfinite(value):
        raise ValueError("snapshot numbers must be finite")


def _encode(value: Any) -> _Value:
    cls = type(value)
    if cls.__name__ in _MODELS and _MODELS[cls.__name__] is cls:
        payload = value.model_dump(mode="json")
        _check_fields(payload)
        return _Value(type=cls.__name__, value=payload)
    if cls is RunRecord:
        return _Value(type="RunRecord", value=asdict(value))
    if cls is datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return _Value(type="datetime", value=value.isoformat())
    if cls is dict:
        if not all(isinstance(key, str) for key in value):
            raise ValueError("snapshot mappings require string keys")
        _check_fields(value)
        return _Value(type="dict", value={k: _encode(v).model_dump() for k, v in value.items()})
    if cls in (list, tuple):
        return _Value(type=cls.__name__, value=[_encode(v).model_dump() for v in value])
    if value is None or cls in (str, int, float, bool):
        return _Value(type="scalar", value=value)
    raise ValueError(f"unsupported snapshot value type: {cls.__name__}")


def _decode(value: _Value) -> Any:
    kind, payload = value.type, value.value
    _check_fields(payload)
    if kind in _MODELS:
        return _MODELS[kind].model_validate(payload)
    if kind == "RunRecord":
        if not isinstance(payload, dict) or set(payload) != set(RunRecord.__dataclass_fields__):
            raise ValueError("invalid RunRecord fields")
        return TypeAdapter(RunRecord).validate_python(payload)
    if kind == "datetime":
        timestamp = datetime.fromisoformat(payload)
        if timestamp.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return timestamp
    if kind == "dict" and isinstance(payload, dict):
        return {k: _decode(_Value.model_validate(v)) for k, v in payload.items()}
    if kind in {"list", "tuple"} and isinstance(payload, list):
        items = [_decode(_Value.model_validate(v)) for v in payload]
        return tuple(items) if kind == "tuple" else items
    if kind == "scalar" and (payload is None or type(payload) in (str, int, float, bool)):
        return payload
    raise ValueError(f"unsupported snapshot type tag: {kind}")


class LocalStateSnapshot:
    """Persist only domain state, never settings, providers, identities, or grants.

    Restore synchronously during startup, before exposing repositories to tasks.
    Save from the same event loop as the repositories. Capture and disk replacement
    do not yield after acquiring repository locks. Wrap multi-step mutations in
    ``transaction()`` to prevent another participating request/worker from saving
    a partially applied operation. The gate is task-reentrant, not inherited by
    child tasks. This adapter requires one server process per data directory.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "local-state.json"
        self._gate = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and task is self._owner:
            yield
            return
        async with self._gate:
            self._owner = task
            try:
                yield
            finally:
                self._owner = None

    async def save(
        self,
        core_repo: InMemoryRepository,
        media_repo: Any,
        v1deps: Any,
        jobs_repo: Any = None,
        id_factory: Any = None,
    ) -> None:
        """Capture consistent in-process state and atomically replace the snapshot."""
        async with self.transaction(), core_repo._lock:
            if jobs_repo is not None:
                async with jobs_repo._lock:
                    self._save_locked(core_repo, media_repo, v1deps, jobs_repo, id_factory)
            else:
                self._save_locked(core_repo, media_repo, v1deps, jobs_repo, id_factory)

    def _save_locked(
        self, core: InMemoryRepository, media: Any, deps: Any, jobs: Any, ids: Any,
    ) -> None:
        try:
            counter = getattr(ids, "_counter", None)
            state = _Snapshot(
                format_version=1,
                core=_CoreState(
                    documents=[
                        _Document(
                            workspace=workspace, collection=kind, id=key,
                            revision=doc.revision, generation=doc.generation,
                            deleted=doc.deleted, value=_encode(doc.value),
                        )
                        for workspace, collections in core._store.items()
                        for kind, documents in collections.items()
                        for key, doc in documents.items()
                    ],
                    idempotency=[(*key, value) for key, value in core._idempotency.items()],
                    budgets=core._budgets,
                    reservations=core._reservations,
                    run_active_attempts=core._run_active_attempts,
                    run_fences=core._run_fences,
                    attempt_workers=[(*key, value) for key, value in core._attempt_workers.items()],
                    selected_attempts=core._selected_attempts,
                ),
                media_assets={key: _encode(value) for key, value in media._assets.items()},
                media_revisions=media._revisions,
                bindings={name: getattr(deps, name, {}) for name in _BINDINGS},
                jobs={} if jobs is None else jobs._jobs,
                next_id=next(copy.copy(counter)) if isinstance(counter, itertools.count) else None,
            )
            payload = json.dumps(state.model_dump(mode="json"), allow_nan=False).encode("utf-8")
            self._atomic_write(payload)
        except (OSError, ValueError, TypeError) as exc:
            raise SnapshotError(
                f"Cannot save local state at {self.path}; no partial snapshot was installed"
            ) from exc

    def _atomic_write(self, payload: bytes) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".local-state-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def restore(
        self,
        core_repo: InMemoryRepository,
        media_repo: Any,
        v1deps: Any,
        jobs_repo: Any = None,
        id_factory: Any = None,
    ) -> bool:
        """Restore before startup; corrupt or incompatible snapshots abort startup.

        Returns false only when no snapshot exists. Validation completes before
        any supplied repository is changed. In-flight jobs become explicitly failed.
        """
        try:
            payload = self.path.read_bytes()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SnapshotError(f"Cannot read local state at {self.path}") from exc
        try:
            state = _Snapshot.model_validate_json(payload)
            core = InMemoryRepository()
            identities: set[tuple[str, str]] = set()
            for document in state.core.documents:
                identity = (document.collection, document.id)
                if identity in identities:
                    raise ValueError("duplicate resource identity")
                identities.add(identity)
                value = _decode(document.value)
                workspace = core._workspace(value)
                if workspace is not None and workspace != document.workspace:
                    raise ValueError("snapshot document ownership mismatch")
                identifier = core._id(value)
                if (
                    document.collection != "run_progress" and identifier is not None
                    and identifier != document.id
                ):
                    raise ValueError("snapshot document identity mismatch")
                core._ensure(document.workspace, document.collection)[document.id] = _Doc(
                    value, document.revision, document.generation, document.deleted,
                )
            core._idempotency = {
                (ws, kind, key): value for ws, kind, key, value in state.core.idempotency
            }
            core._budgets = state.core.budgets
            core._reservations = state.core.reservations
            core._run_active_attempts = state.core.run_active_attempts
            core._run_fences = state.core.run_fences
            core._attempt_workers = {
                (run, attempt): worker for run, attempt, worker in state.core.attempt_workers
            }
            core._selected_attempts = state.core.selected_attempts
            assets = {key: _decode(value) for key, value in state.media_assets.items()}
            if any(
                type(asset) is not SourceAsset or asset.id.root != key
                for key, asset in assets.items()
            ):
                raise ValueError("invalid media asset identity or type")
            if set(state.bindings) != set(_BINDINGS):
                raise ValueError("unsupported binding dictionaries")
            if state.jobs and jobs_repo is None:
                raise ValueError("snapshot requires a jobs repository")
            jobs = {key: value.model_dump(exclude_none=False) for key, value in state.jobs.items()}
            for key, job in jobs.items():
                if job["run_id"] != key:
                    raise ValueError("invalid job identity")
            self._interrupt(core, jobs)
            bindings = {name: getattr(v1deps, name, None) for name in _BINDINGS}
            for name, target in bindings.items():
                if target is not None and not isinstance(target, dict):
                    raise ValueError(f"invalid binding target: {name}")
                if target is None and state.bindings[name]:
                    raise ValueError(f"missing binding target: {name}")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SnapshotError(
                f"Invalid local state snapshot at {self.path}; refusing to start with empty state"
            ) from exc
        for name in (
            "_store", "_idempotency", "_budgets", "_reservations", "_run_active_attempts",
            "_run_fences", "_attempt_workers", "_selected_attempts",
        ):
            setattr(core_repo, name, getattr(core, name))
        media_repo._assets = assets
        media_repo._revisions = state.media_revisions
        for name, target in bindings.items():
            if target is not None:
                target.clear()
                target.update(state.bindings[name])
        if jobs_repo is not None:
            jobs_repo._jobs = jobs
        if state.next_id is not None and isinstance(
            getattr(id_factory, "_counter", None), itertools.count,
        ):
            id_factory._counter = itertools.count(state.next_id)
        return True

    @staticmethod
    def _interrupt(core: InMemoryRepository, jobs: dict[str, dict[str, Any]]) -> None:
        for collections in core._store.values():
            for run_id, document in collections.get("run", {}).items():
                if (
                    not document.deleted and run_id not in jobs
                    and isinstance(document.value, RunRecord)
                    and document.value.selected_attempt_id is None
                ):
                    jobs[run_id] = _Job(
                        revision=0, run_id=run_id, state="queued", invocation_id=None,
                        cancel_requested=False,
                        attempt_id=core._run_active_attempts.get(run_id), fence=0,
                        lease_expires_at=None, heartbeat_at=None, progress_sequence=-1,
                    ).model_dump()
        for run_id, job in jobs.items():
            if job["state"] in _TERMINAL:
                continue
            job.update(
                state="failed", failure_reason="interrupted_by_restart",
                lease_expires_at=None, heartbeat_at=None,
                revision=job["revision"] + 1, fence=job["fence"] + 1,
            )
            attempt = job["attempt_id"] or core._run_active_attempts.get(run_id)
            core._run_active_attempts.pop(run_id, None)
            core._run_fences[run_id] = max(core._run_fences.get(run_id, 0) + 1, job["fence"])
            found = core._find_doc("run", run_id)
            if found is None or attempt is None:
                continue
            workspace, document = found
            if isinstance(document.value, RunRecord):
                document.value = replace(document.value, selected_attempt_id=attempt)
            core._selected_attempts[run_id] = attempt
            progress = [
                doc.value for doc in core._store[workspace].get("run_progress", {}).values()
                if isinstance(doc.value, RunProgress) and doc.value.run_id.root == run_id
                and doc.value.attempt_id.root == attempt
            ]
            previous = max(progress, key=lambda value: value.sequence) if progress else None
            sequence = max(job["progress_sequence"], previous.sequence if previous else -1) + 1
            final = (
                previous.model_copy(update={"phase": "failed", "sequence": sequence})
                if previous else RunProgress(
                    run_id=ResourceId(run_id), attempt_id=ResourceId(attempt), phase="failed",
                    processed_ranges=[], requested_samples=0, processed_samples=0,
                    review_backlog=0, cancel_requested=False,
                    usage=MoneyMicrousd(0), sequence=sequence,
                )
            )
            core._ensure(workspace, "run_progress")[f"{run_id}:{attempt}:{sequence}"] = _Doc(
                final, sequence,
            )
            job["progress_sequence"] = sequence
