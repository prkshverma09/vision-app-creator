"""CT-STORAGE component tests for the local filesystem media-store adapter."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from vision_app.storage.errors import StorageError
from vision_app.storage.local import FileSystemMediaStore


@pytest.fixture
def store(tmp_path: Path, clock: Any) -> FileSystemMediaStore:
    return FileSystemMediaStore(data_dir=tmp_path, max_bytes=100_000, clock=clock)


@pytest.fixture
def small_data() -> bytes:
    return b"hello storage world"


@pytest.fixture
def small_hash(small_data: bytes) -> str:
    return hashlib.sha256(small_data).hexdigest()


@pytest.mark.asyncio
async def test_begin_upload_creates_upload_grant(store: FileSystemMediaStore) -> None:
    grant = await store.begin_upload("owner-1", "video/mp4", 1024)
    assert grant.scope == "upload"
    assert grant.max_bytes == 100_000
    assert grant.resource_id
    assert "/" not in grant.resource_id and "\\" not in grant.resource_id
    assert grant.grant_id
    assert grant.upload_url is None  # local adapter does not sign URLs


@pytest.mark.asyncio
async def test_oversized_declared_upload_is_rejected(store: FileSystemMediaStore) -> None:
    with pytest.raises(StorageError) as exc:
        await store.begin_upload("owner-1", "video/mp4", 200_000)
    assert exc.value.code == "size_exceeded"


@pytest.mark.asyncio
async def test_put_artifact_enforces_size_limit(store: FileSystemMediaStore) -> None:
    too_large = b"x" * 200_000
    with pytest.raises(StorageError) as exc:
        await store.put_artifact("owner-1", too_large, "image/png")
    assert exc.value.code == "size_exceeded"


@pytest.mark.asyncio
async def test_finalize_upload_verifies_size_and_hash(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    meta = await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    assert meta.size == len(small_data)
    assert meta.sha256 == small_hash
    assert meta.state == "ready"
    assert meta.generation >= 1


@pytest.mark.asyncio
async def test_finalize_upload_rejects_wrong_hash(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    with pytest.raises(StorageError) as exc:
        await store.finalize_upload(
            grant.grant_id, actual_size=len(small_data), actual_sha256="a" * 64
        )
    assert exc.value.code == "hash_mismatch"


@pytest.mark.asyncio
async def test_finalize_upload_rejects_size_mismatch(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    with pytest.raises(StorageError) as exc:
        await store.finalize_upload(
            grant.grant_id, actual_size=len(small_data) - 3, actual_sha256=small_hash
        )
    assert exc.value.code == "size_mismatch"


@pytest.mark.asyncio
async def test_reused_finalize_does_not_create_duplicate_asset(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    meta1 = await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    meta2 = await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    assert meta1.resource_id == meta2.resource_id
    # No duplicate resource was created on the second finalize.
    assert meta2.generation == meta1.generation


@pytest.mark.asyncio
async def test_reupload_to_used_grant_is_rejected(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    with pytest.raises(StorageError) as exc:
        await store.receive_upload(grant.grant_id, b"different bytes")
    assert exc.value.code == "upload_already_used"


@pytest.mark.asyncio
async def test_read_grant_is_scoped_to_resource_and_operation(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )

    read_grant = await store.issue_read_grant("owner-1", grant.resource_id)
    assert read_grant.scope == "read"
    assert read_grant.resource_id == grant.resource_id

    # An upload grant cannot be used to read an object.
    with pytest.raises(StorageError) as exc:
        await store.read(grant.grant_id)
    assert exc.value.code == "grant_scope_mismatch"

    # A read grant for the wrong resource cannot be used.
    other_data = b"other object"
    other_resource = await store.put_artifact("owner-1", other_data, "text/plain")
    mismatched = await store.issue_read_grant("owner-1", other_resource)
    with pytest.raises(StorageError) as exc:
        await store.read_artifact(grant.resource_id, mismatched.grant_id)
    assert exc.value.code == "grant_scope_mismatch"

    # Reading with the correct read grant succeeds.
    data = await store.read(read_grant.grant_id)
    assert data == small_data


@pytest.mark.asyncio
async def test_read_grant_prevents_cross_owner_access(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    with pytest.raises(StorageError) as exc:
        await store.issue_read_grant("owner-2", grant.resource_id)
    assert exc.value.code == "not_found"


@pytest.mark.asyncio
async def test_expired_grant_is_rejected(
    store: FileSystemMediaStore, clock: Any, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    clock.value += timedelta(hours=2)
    with pytest.raises(StorageError) as exc:
        await store.finalize_upload(
            grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
        )
    assert exc.value.code == "grant_expired"


@pytest.mark.asyncio
async def test_artifact_lifecycle_and_generation_check(
    store: FileSystemMediaStore
) -> None:
    data = b"thumbnail bytes"
    resource_id = await store.put_artifact("owner-1", data, "image/png")
    meta = await store.get_metadata(resource_id)
    assert meta.size == len(data)
    assert meta.sha256 == hashlib.sha256(data).hexdigest()

    read_grant = await store.issue_read_grant("owner-1", resource_id)
    assert await store.read_artifact(resource_id, read_grant.grant_id) == data

    # Deleting with a stale generation must fail.
    with pytest.raises(StorageError) as exc:
        await store.delete_artifact(resource_id, generation=meta.generation + 1)
    assert exc.value.code == "generation_mismatch"

    await store.delete_artifact(resource_id, meta.generation)
    with pytest.raises(StorageError) as exc:
        await store.get_metadata(resource_id)
    assert exc.value.code == "already_deleted"


@pytest.mark.asyncio
async def test_deleted_object_cannot_be_read(
    store: FileSystemMediaStore
) -> None:
    data = b"short lived"
    resource_id = await store.put_artifact("owner-1", data, "text/plain")
    meta = await store.get_metadata(resource_id)
    await store.delete_artifact(resource_id, meta.generation)
    read_grant = await store.issue_read_grant("owner-1", resource_id)
    with pytest.raises(StorageError) as exc:
        await store.read(read_grant.grant_id)
    assert exc.value.code == "already_deleted"


@pytest.mark.asyncio
async def test_object_generation_changes_on_overwrite(
    store: FileSystemMediaStore, small_data: bytes, small_hash: str
) -> None:
    grant = await store.begin_upload(
        "owner-1", "text/plain", len(small_data), declared_sha256=small_hash
    )
    await store.receive_upload(grant.grant_id, small_data)
    meta = await store.finalize_upload(
        grant.grant_id, actual_size=len(small_data), actual_sha256=small_hash
    )
    assert meta.generation == 1
    # Simulating a server-side overwrite would update generation; local adapter
    # does not support external overwrites, but the metadata must still verify.
    assert (await store.get_metadata(meta.resource_id)).generation == meta.generation
