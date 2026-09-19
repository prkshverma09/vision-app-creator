from datetime import datetime, timedelta, timezone

import pytest

from vision_app.privacy.service import (
    CleanupGraph,
    CleanupState,
    DeletionService,
    GenerationMismatch,
    ResourceRecord,
    RetentionPolicy,
    TombstonedResource,
    retention_deadline,
    retention_eligible,
)


NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


class RepositoryDouble:
    def __init__(self, records: list[ResourceRecord]) -> None:
        self.records = {(record.kind, record.id): record for record in records}

    async def get_owned(self, kind: str, resource_id: str, principal: str) -> ResourceRecord:
        record = self.records[(kind, resource_id)]
        if record.workspace_id != principal:
            raise PermissionError(resource_id)
        if record.deleted_at is not None:
            raise TombstonedResource(kind, resource_id)
        return record

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: ResourceRecord
    ) -> bool:
        current = self.records[(kind, resource_id)]
        if current.revision != revision:
            return False
        self.records[(kind, resource_id)] = value
        return True

    def raw(self, kind: str, resource_id: str) -> ResourceRecord:
        return self.records[(kind, resource_id)]


class MediaStoreDouble:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, int]] = []

    async def delete_artifact(self, resource_id: str, generation: int) -> None:
        self.deleted.append((resource_id, generation))


class CleanerDouble:
    def __init__(self, failing_ref: str | None = None) -> None:
        self.failing_ref = failing_ref
        self.deleted: list[str] = []

    async def delete(self, provider_ref: str) -> None:
        if provider_ref == self.failing_ref:
            raise RuntimeError("provider unavailable")
        self.deleted.append(provider_ref)


def record(kind: str, resource_id: str, workspace: str = "ws-a") -> ResourceRecord:
    return ResourceRecord(kind=kind, id=resource_id, workspace_id=workspace, generation=3, revision=7)


def graph(*records: ResourceRecord) -> CleanupGraph:
    return CleanupGraph(resources=tuple((item.kind, item.id) for item in records))


@pytest.mark.asyncio
async def test_stale_write_after_deletion_is_rejected_and_cannot_resurrect() -> None:
    asset = record("asset", "asset-1")
    repository = RepositoryDouble([asset])
    service = DeletionService(repository, MediaStoreDouble(), CleanerDouble(), lambda: NOW)

    await service.tombstone("ws-a", graph(asset), requested_by="user-1")

    with pytest.raises(GenerationMismatch, match="expected generation 3, current generation 4"):
        await service.write_if_current("ws-a", "asset", "asset-1", 3, {"evidence": "late"})
    assert repository.raw("asset", "asset-1").deleted_at == NOW


@pytest.mark.asyncio
async def test_tombstone_revokes_reads_for_all_privacy_resource_families() -> None:
    resources = [record(kind, f"{kind}-1") for kind in ("app", "version", "asset", "run", "event", "delivery")]
    repository = RepositoryDouble(resources)
    service = DeletionService(repository, MediaStoreDouble(), CleanerDouble(), lambda: NOW)

    await service.tombstone("ws-a", graph(*resources), requested_by="user-1")

    for item in resources:
        with pytest.raises(TombstonedResource):
            await repository.get_owned(item.kind, item.id, "ws-a")
        tombstone = repository.raw(item.kind, item.id)
        assert tombstone.generation == 4
        assert tombstone.cancel_requested is (item.kind == "run")


@pytest.mark.asyncio
async def test_hard_delete_reports_provider_failure_and_remains_retryable() -> None:
    asset = record("asset", "asset-1")
    repository = RepositoryDouble([asset])
    media = MediaStoreDouble()
    cleaner = CleanerDouble(failing_ref="provider-file-1")
    service = DeletionService(repository, media, cleaner, lambda: NOW)
    cleanup = CleanupGraph(
        resources=(("asset", "asset-1"),),
        local_artifacts=(("object-1", 9),),
        provider_refs=("provider-file-1",),
    )
    job = await service.tombstone("ws-a", cleanup, requested_by="user-1")

    failed = await service.hard_delete(job)

    assert failed.state == CleanupState.FAILED
    assert failed.pending_provider_refs == ("provider-file-1",)
    assert failed.errors == ("provider:provider-file-1: provider unavailable",)
    assert failed.irreversible is False
    assert media.deleted == [("object-1", 9)]

    cleaner.failing_ref = None
    completed = await service.hard_delete(failed)
    assert completed.state == CleanupState.COMPLETE
    assert completed.pending_provider_refs == ()
    assert completed.irreversible is False


@pytest.mark.asyncio
async def test_generation_mismatch_detected_even_without_tombstone() -> None:
    asset = record("asset", "asset-1")
    repository = RepositoryDouble([asset])
    service = DeletionService(repository, MediaStoreDouble(), CleanerDouble(), lambda: NOW)

    with pytest.raises(GenerationMismatch):
        await service.write_if_current("ws-a", "asset", "asset-1", 2, {"state": "ready"})


@pytest.mark.asyncio
async def test_cleanup_is_explicitly_scoped_and_idempotent() -> None:
    mine = record("asset", "asset-1")
    other = record("asset", "asset-2", "ws-b")
    repository = RepositoryDouble([mine, other])
    media = MediaStoreDouble()
    service = DeletionService(repository, media, CleanerDouble(), lambda: NOW)
    cleanup = CleanupGraph(resources=(("asset", "asset-1"),), local_artifacts=(("object-1", 1),))

    job = await service.tombstone("ws-a", cleanup, requested_by="user-1")
    same_job = await service.tombstone("ws-a", cleanup, requested_by="user-1")
    completed = await service.hard_delete(job)
    repeated = await service.hard_delete(completed)

    assert same_job.id == job.id
    assert repository.raw("asset", "asset-2") == other
    assert media.deleted == [("object-1", 1)]
    assert repeated == completed


def test_retention_policy_schedules_raw_and_evidence_independently() -> None:
    policy = RetentionPolicy(raw_media=timedelta(hours=24), evidence=timedelta(days=7))

    assert retention_deadline(NOW, "raw_media", policy) == NOW + timedelta(hours=24)
    assert retention_deadline(NOW, "evidence", policy) == NOW + timedelta(days=7)
    assert retention_eligible(NOW, NOW - timedelta(seconds=1))
    assert not retention_eligible(NOW, NOW + timedelta(seconds=1))
    assert not retention_eligible(NOW, None)
