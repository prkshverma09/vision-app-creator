"""Local filesystem media-store adapter for tests and development."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from vision_app.contracts.models import ReadGrant, ResourceId, StoredMetadata, UploadGrant, UtcTimestamp
from vision_app.storage._grant import GrantManager
from vision_app.storage._id import make_opaque_id
from vision_app.storage.errors import StorageError

if TYPE_CHECKING:
    from vision_app.contracts.ports import Clock


def _as_str(resource_id: str | object) -> str:
    """Accept a plain string or a C0 ResourceId RootModel and return the string value."""
    if isinstance(resource_id, str):
        return resource_id
    return getattr(resource_id, "root", str(resource_id))


class FileSystemMediaStore:
    """File-system backed MediaStore with grant-based authorization.

    All bytes are written under ``data_dir``; resource IDs are opaque and never
    used directly as paths. Metadata (size, SHA-256, generation, owner, state) is
    stored alongside objects in JSON files so that size/hash/generation checks
    can be enforced without trusting the object file alone.
    """

    def __init__(
        self,
        data_dir: Path,
        max_bytes: int,
        clock: "Clock",
        *,
        grant_ttl_seconds: int = 3600,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._objects_dir = self._data_dir / "objects"
        self._meta_dir = self._data_dir / "meta"
        self._objects_dir.mkdir(parents=True, exist_ok=True)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._clock = clock
        self._grant_ttl_seconds = grant_ttl_seconds
        self._grants = GrantManager(clock)

    def _object_path(self, resource_id: str) -> Path:
        return self._objects_dir / resource_id

    def local_path(self, resource_id: str) -> Path | None:
        """Return the on-disk path for direct range-aware serving, if available."""
        return self._object_path(_as_str(resource_id))

    def _meta_path(self, resource_id: str) -> Path:
        return self._meta_dir / f"{resource_id}.json"

    def _assert_size_allowed(self, size: int) -> None:
        if size <= 0 or size > self._max_bytes:
            raise StorageError("size_exceeded", f"size {size} exceeds policy limit")

    def _write_meta(
        self,
        resource_id: str,
        owner_id: str,
        content_type: str,
        size: int,
        sha256: str,
        generation: int,
        state: str,
    ) -> None:
        record = {
            "resource_id": resource_id,
            "owner_id": owner_id,
            "content_type": content_type,
            "size": size,
            "sha256": sha256,
            "generation": generation,
            "state": state,
        }
        self._meta_path(resource_id).write_text(json.dumps(record), encoding="utf-8")

    def _read_meta(self, resource_id: str) -> StoredMetadata:
        path = self._meta_path(resource_id)
        if not path.exists():
            raise StorageError("not_found", f"resource {resource_id} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        return StoredMetadata.model_validate(data)

    async def begin_upload(
        self,
        owner_id: str,
        content_type: str,
        declared_size: int,
        *,
        declared_sha256: str | None = None,
        idempotency_key: str | None = None,
    ) -> UploadGrant:
        self._assert_size_allowed(declared_size)
        if idempotency_key is not None and not idempotency_key:
            raise StorageError("invalid_idempotency_key")
        resource_id = make_opaque_id("media")
        # Reserve the resource identity; object does not exist yet.
        self._write_meta(
            resource_id,
            owner_id,
            content_type,
            declared_size,
            declared_sha256 or "0" * 64,
            1,
            "uploading",
        )
        record = self._grants.issue(
            "upload", resource_id, owner_id, self._grant_ttl_seconds
        )
        return UploadGrant(
            grant_id=record.grant_id,
            resource_id=ResourceId(resource_id),
            upload_url=None,  # local adapter accepts bytes directly via receive_upload
            expires_at=UtcTimestamp(record.expires_at),
            max_bytes=self._max_bytes,
        )

    async def receive_upload(self, grant_id: str, data: bytes) -> None:
        """Local-only helper: write the raw upload bytes identified by the grant."""
        record = self._grants.consume(grant_id, "upload")
        if record.used:
            raise StorageError("upload_already_used", "upload grant already consumed")
        self._assert_size_allowed(len(data))
        path = self._object_path(_as_str(record.resource_id))
        path.write_bytes(data)
        record.used = True

    async def finalize_upload(
        self,
        grant_id: str,
        *,
        actual_size: int,
        actual_sha256: str,
    ) -> StoredMetadata:
        record = self._grants.consume(grant_id, "upload")

        # Idempotent finalize: return the previously stored metadata.
        if record.used and record.result_resource_id:
            return self._read_meta(_as_str(record.result_resource_id))

        resource_id = _as_str(record.resource_id)
        meta = self._read_meta(resource_id)
        if meta.state != "uploading":
            # Already finalized via a different code path; treat as idempotent.
            return meta

        path = self._object_path(resource_id)
        if not path.exists():
            raise StorageError("upload_not_found", "no bytes were uploaded for the grant")

        self._assert_size_allowed(actual_size)
        if actual_size != meta.size or actual_size != path.stat().st_size:
            raise StorageError(
                "size_mismatch",
                f"declared size {meta.size} does not match actual {actual_size}",
            )

        computed = hashlib.sha256(path.read_bytes()).hexdigest()
        if computed != actual_sha256:
            raise StorageError(
                "hash_mismatch",
                "computed SHA-256 does not match the supplied value",
            )
        if meta.sha256 != "0" * 64 and meta.sha256 != actual_sha256:
            raise StorageError(
                "hash_mismatch",
                "computed SHA-256 does not match the declared value",
            )

        self._write_meta(
            resource_id,
            meta.owner_id,
            meta.content_type,
            actual_size,
            actual_sha256,
            meta.generation,
            "ready",
        )
        record.result_resource_id = resource_id
        return self._read_meta(resource_id)

    async def issue_read_grant(
        self,
        owner_id: str,
        resource_id: str,
        *,
        ttl_seconds: int = 3600,
    ) -> ReadGrant:
        resource_id = _as_str(resource_id)
        meta = self._read_meta(resource_id)
        if meta.owner_id != owner_id:
            # Do not leak existence across owners.
            raise StorageError("not_found")
        record = self._grants.issue(
            "read", resource_id, owner_id, ttl_seconds
        )
        return ReadGrant(
            grant_id=record.grant_id,
            resource_id=ResourceId(resource_id),
            expires_at=UtcTimestamp(record.expires_at),
        )

    async def read(self, grant_id: str) -> bytes:
        record = self._grants.consume(grant_id, "read")
        meta = self._read_meta(record.resource_id)
        if meta.state == "deleted":
            raise StorageError("already_deleted")
        if meta.state != "ready":
            raise StorageError("not_found", "resource is not ready")
        return self._object_path(record.resource_id).read_bytes()

    async def put_artifact(self, owner_id: str, data: bytes, content_type: str) -> str:
        self._assert_size_allowed(len(data))
        resource_id = make_opaque_id("media")
        sha256 = hashlib.sha256(data).hexdigest()
        self._object_path(resource_id).write_bytes(data)
        self._write_meta(
            resource_id,
            owner_id,
            content_type,
            len(data),
            sha256,
            1,
            "ready",
        )
        return resource_id

    async def read_artifact(self, resource_id: str, grant_id: str) -> bytes:
        resource_id = _as_str(resource_id)
        record = self._grants.consume(grant_id, "read")
        if _as_str(record.resource_id) != resource_id:
            raise StorageError(
                "grant_scope_mismatch",
                "read grant is for a different resource",
            )
        return await self.read(grant_id)

    async def delete_artifact(
        self, resource_id: str, generation: int | None = None
    ) -> None:
        resource_id = _as_str(resource_id)
        meta = self._read_meta(resource_id)
        if meta.state == "deleted":
            raise StorageError("already_deleted")
        if generation is not None and meta.generation != generation:
            raise StorageError(
                "generation_mismatch",
                f"expected generation {generation}, found {meta.generation}",
            )
        self._object_path(resource_id).unlink(missing_ok=True)
        self._write_meta(
            resource_id,
            meta.owner_id,
            meta.content_type,
            meta.size,
            meta.sha256,
            meta.generation,
            "deleted",
        )

    async def get_metadata(self, resource_id: str) -> StoredMetadata:
        resource_id = _as_str(resource_id)
        meta = self._read_meta(resource_id)
        if meta.state == "deleted":
            raise StorageError("already_deleted", f"resource {resource_id} is deleted")
        return meta
