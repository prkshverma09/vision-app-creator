"""IT02 storage integration tests: mock GCS client to verify signing/metadata plumbing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

from vision_app.storage.errors import StorageError


def _make_fixed_clock() -> Any:
    from datetime import datetime, timezone

    class _Clock:
        value = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def now(self) -> datetime:
            return self.value

    return _Clock()


@pytest.fixture
def clock() -> Any:
    return _make_fixed_clock()


@pytest.fixture
def fake_gcs_module() -> ModuleType:
    """Return a minimal google.cloud.storage stand-in so GCS tests need no SDK."""
    module = ModuleType("google.cloud.storage")
    module.Client = MagicMock  # type: ignore[attr-defined]
    return module


@pytest.mark.integration
def test_gcs_adapter_requires_cloud_dependency(clock: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Conditional import path: module loads, but instantiation fails without the SDK."""
    import vision_app.storage.gcs as gcs_module

    monkeypatch.setattr(gcs_module, "_gcs_storage_real", None)
    from vision_app.storage.gcs import GCSMediaStore

    with pytest.raises(StorageError) as exc:
        GCSMediaStore(bucket_name="test", max_bytes=10_000_000, clock=clock)
    assert exc.value.code == "gcs_unavailable"


@pytest.mark.integration
class TestGCSMediaStoreMocked:
    """Mock the GCS Client to exercise signing, metadata, and generation plumbing."""

    @pytest.fixture
    def mock_blob(self) -> MagicMock:
        blob = MagicMock()
        blob.metadata = {}
        blob.generation = 123456789
        blob.size = 0
        blob.content_type = "video/mp4"
        blob.generate_signed_url.return_value = "https://signed.example/upload"
        return blob

    @pytest.fixture
    def mock_bucket(self, mock_blob: MagicMock) -> MagicMock:
        bucket = MagicMock()
        bucket.blob.return_value = mock_blob
        return bucket

    @pytest.fixture
    def store(self, mock_bucket: MagicMock, clock: Any, fake_gcs_module: ModuleType) -> Any:
        from vision_app.storage.gcs import GCSMediaStore

        client = MagicMock()
        client.bucket.return_value = mock_bucket
        return GCSMediaStore(
            bucket_name="test-bucket",
            max_bytes=10_000_000,
            clock=clock,
            _client=client,
            _gcs_module=fake_gcs_module,
        )

    @pytest.mark.asyncio
    async def test_begin_upload_generates_signed_put_url(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        grant = await store.begin_upload("owner-1", "video/mp4", 1024)
        assert grant.scope == "upload"
        assert grant.resource_id
        assert "/" not in grant.resource_id
        assert grant.upload_url == "https://signed.example/upload"
        mock_blob.generate_signed_url.assert_called_once()
        method_kw = mock_blob.generate_signed_url.call_args.kwargs
        assert method_kw.get("method") == "PUT"
        assert method_kw.get("version") == "v4"

    @pytest.mark.asyncio
    async def test_begin_upload_sets_declared_metadata(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        await store.begin_upload(
            "owner-1", "video/mp4", 1024, declared_sha256="b" * 64
        )
        assert mock_blob.metadata == {
            "sha256": "b" * 64,
            "owner": "owner-1",
            "state": "uploading",
        }
        mock_blob.patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_upload_verifies_generation_and_metadata(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        data = b"mock video bytes"
        sha = hashlib.sha256(data).hexdigest()
        mock_blob.size = len(data)
        mock_blob.download_as_bytes.return_value = data

        grant = await store.begin_upload("owner-1", "video/mp4", len(data))
        meta = await store.finalize_upload(
            grant.grant_id, actual_size=len(data), actual_sha256=sha
        )

        assert meta.generation == 123456789
        assert meta.size == len(data)
        assert meta.sha256 == sha
        assert meta.state == "ready"
        mock_blob.reload.assert_called()
        mock_blob.download_as_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_upload_rejects_hash_mismatch(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        data = b"mock video bytes"
        mock_blob.size = len(data)
        mock_blob.download_as_bytes.return_value = data

        grant = await store.begin_upload("owner-1", "video/mp4", len(data))
        with pytest.raises(StorageError) as exc:
            await store.finalize_upload(
                grant.grant_id,
                actual_size=len(data),
                actual_sha256="0" * 64,
            )
        assert exc.value.code == "hash_mismatch"

    @pytest.mark.asyncio
    async def test_finalize_upload_is_idempotent(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        data = b"mock video bytes"
        sha = hashlib.sha256(data).hexdigest()
        mock_blob.size = len(data)
        mock_blob.download_as_bytes.return_value = data

        grant = await store.begin_upload("owner-1", "video/mp4", len(data))
        meta1 = await store.finalize_upload(
            grant.grant_id, actual_size=len(data), actual_sha256=sha
        )
        meta2 = await store.finalize_upload(
            grant.grant_id, actual_size=len(data), actual_sha256=sha
        )
        # The second finalize should reuse metadata without re-downloading.
        assert meta1.resource_id == meta2.resource_id
        assert mock_blob.download_as_bytes.call_count == 1

    @pytest.mark.asyncio
    async def test_issue_read_grant_generates_signed_get_url(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        mock_blob.metadata = {
            "sha256": "c" * 64,
            "owner": "owner-1",
            "state": "ready",
            "generation": "123",
        }
        mock_blob.size = 42
        mock_blob.content_type = "image/png"

        read_grant = await store.issue_read_grant("owner-1", "media_abc")
        assert read_grant.scope == "read"
        assert read_grant.resource_id.root == "media_abc"
        assert read_grant.expires_at.root > datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_blob.generate_signed_url.assert_called()
        method_kw = mock_blob.generate_signed_url.call_args.kwargs
        assert method_kw.get("method") == "GET"

    @pytest.mark.asyncio
    async def test_issue_read_grant_enforces_ownership(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        mock_blob.metadata = {"owner": "owner-2", "state": "ready"}
        with pytest.raises(StorageError) as exc:
            await store.issue_read_grant("owner-1", "media_abc")
        assert exc.value.code == "not_found"

    @pytest.mark.asyncio
    async def test_delete_artifact_checks_generation(
        self, store: Any, mock_blob: MagicMock
    ) -> None:
        mock_blob.generation = 555
        await store.delete_artifact("media_abc", generation=555)
        mock_blob.delete.assert_called_once()

        with pytest.raises(StorageError) as exc:
            await store.delete_artifact("media_abc", generation=123)
        assert exc.value.code == "generation_mismatch"
