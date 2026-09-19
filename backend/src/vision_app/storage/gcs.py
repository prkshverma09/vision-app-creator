"""Google Cloud Storage MediaStore adapter (conditional import)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vision_app.contracts.models import ReadGrant, ResourceId, StoredMetadata, UploadGrant, UtcTimestamp
from vision_app.storage._grant import GrantManager
from vision_app.storage._id import make_opaque_id
from vision_app.storage.errors import StorageError

try:
    from google.cloud import storage as _gcs_storage_real
except Exception:  # pragma: no cover
    _gcs_storage_real = None

if TYPE_CHECKING:
    from vision_app.contracts.ports import Clock


def _gcs_storage_module(given: Any | None) -> Any:
    module = given if given is not None else _gcs_storage_real
    if module is None:
        raise StorageError(
            "gcs_unavailable",
            "google-cloud-storage is not installed; install the cloud optional group",
        )
    return module


class GCSMediaStore:
    """Production MediaStore backed by Google Cloud Storage.

    Cloud signing credentials are held server-side inside the Google Cloud
    client; only short-lived signed URLs are returned to callers. Import of
    ``google.cloud.storage`` is deferred/conditional so the module can be
    inspected without the optional cloud dependency installed.
    """

    def __init__(
        self,
        *,
        bucket_name: str,
        max_bytes: int,
        clock: "Clock",
        project: str | None = None,
        credentials: Any = None,
        grant_ttl_seconds: int = 3600,
        signed_url_expiration_seconds: int = 3600,
        _client: Any | None = None,
        _gcs_module: Any | None = None,
    ) -> None:
        self._gcs_module = _gcs_storage_module(_gcs_module)
        self._bucket_name = bucket_name
        self._max_bytes = max_bytes
        self._clock = clock
        self._grant_ttl_seconds = grant_ttl_seconds
        self._signed_url_expiration_seconds = signed_url_expiration_seconds
        self._grants = GrantManager(clock)
        self._client: Any = _client or self._gcs_module.Client(
            project=project, credentials=credentials
        )
        self._bucket = self._client.bucket(bucket_name)

    def _blob(self, resource_id: str) -> Any:
        return self._bucket.blob(resource_id)

    def _assert_size_allowed(self, size: int) -> None:
        if size <= 0 or size > self._max_bytes:
            raise StorageError("size_exceeded", f"size {size} exceeds policy limit")

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
        blob = self._blob(resource_id)
        metadata: dict[str, str] = {
            "owner": owner_id,
            "state": "uploading",
        }
        if declared_sha256:
            metadata["sha256"] = declared_sha256
        blob.metadata = metadata
        blob.patch()
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=self._signed_url_expiration_seconds),
            method="PUT",
            content_type=content_type,
        )
        record = self._grants.issue(
            "upload", resource_id, owner_id, self._grant_ttl_seconds, upload_url=url
        )
        return UploadGrant(
            grant_id=record.grant_id,
            resource_id=ResourceId(resource_id),
            upload_url=url,
            expires_at=UtcTimestamp(record.expires_at),
            max_bytes=self._max_bytes,
        )

    async def finalize_upload(
        self,
        grant_id: str,
        *,
        actual_size: int,
        actual_sha256: str,
    ) -> StoredMetadata:
        record = self._grants.consume(grant_id, "upload")

        if record.used and record.result_resource_id:
            return await self.get_metadata(record.result_resource_id)

        self._assert_size_allowed(actual_size)
        blob = self._blob(record.resource_id)
        blob.reload()
        if blob.size != actual_size:
            raise StorageError(
                "size_mismatch",
                f"expected size {actual_size}, blob reports {blob.size}",
            )

        data = blob.download_as_bytes()
        computed = hashlib.sha256(data).hexdigest()
        if computed != actual_sha256:
            raise StorageError(
                "hash_mismatch",
                "computed SHA-256 does not match the supplied value",
            )

        metadata = (blob.metadata or {}) | {
            "sha256": actual_sha256,
            "state": "ready",
            "generation": str(blob.generation),
        }
        blob.metadata = metadata
        blob.patch()
        record.used = True
        record.result_resource_id = record.resource_id
        return await self.get_metadata(record.resource_id)

    async def issue_read_grant(
        self,
        owner_id: str,
        resource_id: str,
        *,
        ttl_seconds: int = 3600,
    ) -> ReadGrant:
        blob = self._blob(resource_id)
        blob.reload()
        meta = blob.metadata or {}
        if meta.get("owner") != owner_id:
            raise StorageError("not_found")
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
        )
        record = self._grants.issue(
            "read", resource_id, owner_id, ttl_seconds, upload_url=url
        )
        return ReadGrant(
            grant_id=record.grant_id,
            resource_id=ResourceId(resource_id),
            expires_at=UtcTimestamp(record.expires_at),
        )

    async def read(self, grant_id: str) -> bytes:
        record = self._grants.consume(grant_id, "read")
        blob = self._blob(record.resource_id)
        data: bytes = blob.download_as_bytes()
        return data

    async def put_artifact(self, owner_id: str, data: bytes, content_type: str) -> str:
        self._assert_size_allowed(len(data))
        resource_id = make_opaque_id("media")
        sha256 = hashlib.sha256(data).hexdigest()
        blob = self._blob(resource_id)
        blob.metadata = {
            "owner": owner_id,
            "state": "ready",
            "sha256": sha256,
            "generation": "1",
        }
        blob.upload_from_string(data, content_type=content_type)
        return resource_id

    async def read_artifact(self, resource_id: str, grant_id: str) -> bytes:
        record = self._grants.consume(grant_id, "read")
        if record.resource_id != resource_id:
            raise StorageError(
                "grant_scope_mismatch",
                "read grant is for a different resource",
            )
        return await self.read(grant_id)

    async def delete_artifact(
        self, resource_id: str, generation: int | None = None
    ) -> None:
        blob = self._blob(resource_id)
        blob.reload()
        if generation is not None and blob.generation != generation:
            raise StorageError(
                "generation_mismatch",
                f"expected generation {generation}, found {blob.generation}",
            )
        blob.delete()

    async def get_metadata(self, resource_id: str) -> StoredMetadata:
        blob = self._blob(resource_id)
        blob.reload()
        meta = blob.metadata or {}
        generation = blob.generation
        if isinstance(generation, str):
            generation = int(generation)
        return StoredMetadata(
            resource_id=ResourceId(resource_id),
            owner_id=meta.get("owner", ""),
            content_type=blob.content_type or "application/octet-stream",
            size=blob.size or 0,
            sha256=meta.get("sha256", ""),
            generation=generation or 1,
            state=meta.get("state", "unknown"),
        )

    def local_path(self, resource_id: str) -> Path | None:
        """GCS objects are not served from local disk."""
        return None
