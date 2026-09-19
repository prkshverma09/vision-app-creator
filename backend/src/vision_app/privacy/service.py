from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any

from vision_app.contracts.ports import MediaStore, ProviderAssetCleaner, Repository


RESOURCE_KINDS = frozenset({"app", "version", "asset", "run", "event", "delivery"})


class PrivacyError(RuntimeError):
    pass


class TombstonedResource(PrivacyError):
    def __init__(self, kind: str, resource_id: str) -> None:
        super().__init__(f"{kind} {resource_id} is deleted")


class GenerationMismatch(PrivacyError):
    def __init__(self, expected: int, current: int) -> None:
        super().__init__(f"expected generation {expected}, current generation {current}")
        self.expected = expected
        self.current = current


class ConcurrentDeletion(PrivacyError):
    pass


@dataclass(frozen=True)
class ResourceRecord:
    kind: str
    id: str
    workspace_id: str
    generation: int
    revision: int
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    cancel_requested: bool = False
    hard_deleted: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in RESOURCE_KINDS:
            raise ValueError(f"unsupported privacy resource kind: {self.kind}")
        if self.generation < 1 or self.revision < 0:
            raise ValueError("generation must be positive and revision nonnegative")


@dataclass(frozen=True)
class CleanupGraph:
    resources: tuple[tuple[str, str], ...]
    local_artifacts: tuple[tuple[str, int], ...] = ()
    provider_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.resources:
            raise ValueError("cleanup graph requires at least one resource")
        if any(kind not in RESOURCE_KINDS for kind, _ in self.resources):
            raise ValueError("cleanup graph contains an unsupported resource kind")
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("cleanup graph contains duplicate resources")


class CleanupState(StrEnum):
    PENDING = "pending"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass(frozen=True)
class DeletionJob:
    id: str
    workspace_id: str
    requested_by: str
    requested_at: datetime
    state: CleanupState
    resources: tuple[ResourceRecord, ...]
    pending_local_artifacts: tuple[tuple[str, int], ...]
    pending_provider_refs: tuple[str, ...]
    errors: tuple[str, ...] = ()
    completed_at: datetime | None = None
    irreversible: bool = False


@dataclass(frozen=True)
class RetentionPolicy:
    raw_media: timedelta = timedelta(hours=24)
    evidence: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        if self.raw_media <= timedelta(0) or self.evidence <= timedelta(0):
            raise ValueError("retention periods must be positive")


def retention_deadline(created_at: datetime, category: str, policy: RetentionPolicy) -> datetime:
    if category == "raw_media":
        return created_at + policy.raw_media
    if category == "evidence":
        return created_at + policy.evidence
    raise ValueError(f"unsupported retention category: {category}")


def retention_eligible(now: datetime, retention_until: datetime | None) -> bool:
    return retention_until is not None and retention_until <= now


class DeletionService:
    def __init__(
        self,
        repository: Repository,
        media_store: MediaStore,
        provider_cleaner: ProviderAssetCleaner,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._media_store = media_store
        self._provider_cleaner = provider_cleaner
        self._now = now
        self._jobs: dict[str, DeletionJob] = {}
        self._deleted_generations: dict[tuple[str, str], int] = {}

    async def tombstone(
        self,
        workspace_id: str,
        graph: CleanupGraph,
        requested_by: str,
    ) -> DeletionJob:
        job_id = self._job_id(workspace_id, graph)
        if job_id in self._jobs:
            return self._jobs[job_id]
        deleted_at = self._now()
        tombstones: list[ResourceRecord] = []
        for kind, resource_id in graph.resources:
            current = await self._repository.get_owned(kind, resource_id, workspace_id)
            if not isinstance(current, ResourceRecord):
                raise TypeError("privacy deletion requires ResourceRecord repository values")
            tombstone = replace(
                current,
                generation=current.generation + 1,
                revision=current.revision + 1,
                deleted_at=deleted_at,
                deleted_by=requested_by,
                cancel_requested=current.cancel_requested or kind == "run",
            )
            if not await self._repository.compare_and_swap(
                kind, resource_id, current.revision, tombstone
            ):
                raise ConcurrentDeletion(f"{kind} {resource_id} changed during deletion")
            tombstones.append(tombstone)
            self._deleted_generations[(kind, resource_id)] = tombstone.generation
        job = DeletionJob(
            id=job_id,
            workspace_id=workspace_id,
            requested_by=requested_by,
            requested_at=deleted_at,
            state=CleanupState.PENDING,
            resources=tuple(tombstones),
            pending_local_artifacts=graph.local_artifacts,
            pending_provider_refs=graph.provider_refs,
        )
        self._jobs[job_id] = job
        return job

    async def write_if_current(
        self,
        workspace_id: str,
        kind: str,
        resource_id: str,
        expected_generation: int,
        data: dict[str, Any],
    ) -> ResourceRecord:
        deleted_generation = self._deleted_generations.get((kind, resource_id))
        if deleted_generation is not None:
            raise GenerationMismatch(expected_generation, deleted_generation)
        current = await self._repository.get_owned(kind, resource_id, workspace_id)
        if not isinstance(current, ResourceRecord):
            raise TypeError("generation fencing requires ResourceRecord repository values")
        if current.generation != expected_generation:
            raise GenerationMismatch(expected_generation, current.generation)
        updated = replace(current, revision=current.revision + 1, data=data)
        if not await self._repository.compare_and_swap(kind, resource_id, current.revision, updated):
            raise ConcurrentDeletion(f"{kind} {resource_id} changed during write")
        return updated

    async def hard_delete(self, job: DeletionJob) -> DeletionJob:
        if job.state == CleanupState.COMPLETE:
            return job
        pending_local: list[tuple[str, int]] = []
        pending_provider: list[str] = []
        errors: list[str] = []
        for resource_id, generation in job.pending_local_artifacts:
            try:
                await self._media_store.delete_artifact(resource_id, generation)
            except Exception as exc:
                pending_local.append((resource_id, generation))
                errors.append(f"local:{resource_id}: {exc}")
        for provider_ref in job.pending_provider_refs:
            try:
                await self._provider_cleaner.delete(provider_ref)
            except Exception as exc:
                pending_provider.append(provider_ref)
                errors.append(f"provider:{provider_ref}: {exc}")
        state = CleanupState.FAILED if errors else CleanupState.COMPLETE
        completed_at = self._now() if state == CleanupState.COMPLETE else None
        result = replace(
            job,
            state=state,
            pending_local_artifacts=tuple(pending_local),
            pending_provider_refs=tuple(pending_provider),
            errors=tuple(errors),
            completed_at=completed_at,
            irreversible=False,
        )
        if state == CleanupState.COMPLETE:
            for resource in job.resources:
                hard_deleted = replace(
                    resource, revision=resource.revision + 1, hard_deleted=True, data={}
                )
                if not await self._repository.compare_and_swap(
                    resource.kind, resource.id, resource.revision, hard_deleted
                ):
                    result = replace(
                        result,
                        state=CleanupState.FAILED,
                        errors=(f"repository:{resource.kind}:{resource.id}: cleanup state changed",),
                        completed_at=None,
                    )
                    break
        self._jobs[job.id] = result
        return result

    @staticmethod
    def _job_id(workspace_id: str, graph: CleanupGraph) -> str:
        scope = "|".join(f"{kind}:{resource_id}" for kind, resource_id in graph.resources)
        digest = sha256(f"{workspace_id}|{scope}".encode()).hexdigest()[:20]
        return f"deletion-{digest}"
