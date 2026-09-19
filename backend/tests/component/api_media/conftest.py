"""Fixtures for media API component tests (task A01)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vision_app.api.media import (
    MediaDependencies,
    add_media_exception_handlers,
    create_media_router,
)
from vision_app.contracts.models import (
    DecodedFrame,
    FrameRef,
    ResourceId,
    SourceAsset,
    SourceTimeMs,
    UtcTimestamp,
)
from vision_app.contracts.ports import MediaStore
from vision_app.media.types import MediaProbe
from vision_app.privacy.service import DeletionService, ResourceRecord
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity
from vision_app.storage.local import FileSystemMediaStore


class FixedClock:
    value: datetime

    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class MutableOwnershipResolver:
    def __init__(self) -> None:
        self._items: dict[tuple[ResourceFamily, str], ResourceOwnership] = {}

    def register(self, ownership: ResourceOwnership) -> None:
        self._items[(ownership.family, ownership.resource_id)] = ownership

    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None:
        return self._items.get((family, resource_id))


class MediaRecord:
    def __init__(self, asset: SourceAsset, revision: int = 0) -> None:
        self.asset = asset
        self.revision = revision


class InMemoryMediaRepository:
    """In-memory asset store that also satisfies the privacy service repository interface."""

    def __init__(self, resolver: MutableOwnershipResolver | None = None) -> None:
        self._records: dict[str, MediaRecord] = {}
        self._resolver = resolver

    async def save_asset(self, asset: SourceAsset) -> None:
        self._records[asset.id.root] = MediaRecord(asset)
        if self._resolver is not None:
            self._resolver.register(
                ResourceOwnership(
                    ResourceFamily.ASSET, asset.id.root, asset.workspace_id.root
                )
            )

    async def get_asset(self, asset_id: str, workspace_id: str) -> SourceAsset | None:
        record = self._records.get(asset_id)
        if record is None:
            return None
        if record.asset.workspace_id.root != workspace_id:
            return None
        return record.asset

    # Privacy service repository interface
    async def get_owned(
        self, kind: str, resource_id: str, principal: Any
    ) -> Any:
        if kind != "asset":
            return None
        record = self._records.get(resource_id)
        if record is None:
            return None
        if record.asset.workspace_id.root != principal:
            raise PermissionError(resource_id)
        return ResourceRecord(
            kind="asset",
            id=resource_id,
            workspace_id=record.asset.workspace_id.root,
            generation=record.asset.generation,
            revision=record.revision,
        )

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        if kind != "asset":
            return False
        record = self._records.get(resource_id)
        if record is None or record.revision != revision:
            return False
        if isinstance(value, ResourceRecord):
            asset = record.asset
            new_state = asset.state
            new_deleted_at = asset.deleted_at
            if value.hard_deleted:
                new_state = "deleted"
            elif value.deleted_at is not None:
                new_state = "deleting"
                new_deleted_at = UtcTimestamp(value.deleted_at)
            updated = asset.model_copy(
                update={
                    "state": new_state,
                    "generation": value.generation,
                    "deleted_at": new_deleted_at,
                }
            )
            self._records[resource_id] = MediaRecord(updated, value.revision)
        return True


class FakeVideoDecoder:
    """Scripted decoder that never touches FFmpeg or cloud storage."""

    def __init__(
        self,
        probe_result: MediaProbe | Exception | None = None,
        samples: list[FrameRef] | None = None,
    ) -> None:
        self._probe_result = probe_result
        self._samples = samples or []

    async def probe(self, resource_id: str) -> MediaProbe:
        if isinstance(self._probe_result, Exception):
            raise self._probe_result
        return self._probe_result or MediaProbe(
            codec="h264",
            container="mp4",
            coded_width=320,
            coded_height=240,
            display_width=320,
            display_height=240,
            duration_ms=5000,
            time_base_num=1,
            time_base_den=1000,
            rotation_degrees=0,
            frame_count=10,
            nominal_fps=2.0,
            byte_size=1234,
            sha256="a" * 64,
            pts_origin=0,
        )

    async def scene_samples(self, resource_id: str, *, count: int) -> list[DecodedFrame]:
        return [
            DecodedFrame(
                frame_ref=ref,
                rgb=b"\x00" * (ref.width * ref.height * 3),
                stride=ref.width * 3,
            )
            for ref in self._samples[:count]
        ]


class NoOpProviderAssetCleaner:
    async def delete(self, provider_ref: str) -> None:
        return None


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def resolver() -> MutableOwnershipResolver:
    return MutableOwnershipResolver()


@pytest.fixture
def repository(resolver: MutableOwnershipResolver) -> InMemoryMediaRepository:
    return InMemoryMediaRepository(resolver)


@pytest.fixture
def store(tmp_path: Any, clock: FixedClock) -> FileSystemMediaStore:
    return FileSystemMediaStore(data_dir=tmp_path, max_bytes=100_000, clock=clock)


@pytest.fixture
def decoder() -> FakeVideoDecoder:
    samples = [
        FrameRef(
            source_id=ResourceId("asset-1"),
            source_hash="a" * 64,
            pts=0,
            time_base_num=1,
            time_base_den=1000,
            source_time_ms=SourceTimeMs(1000),
            sequence=0,
            width=320,
            height=240,
            transform_id=ResourceId("t0"),
        ),
        FrameRef(
            source_id=ResourceId("asset-1"),
            source_hash="a" * 64,
            pts=2500,
            time_base_num=1,
            time_base_den=1000,
            source_time_ms=SourceTimeMs(2500),
            sequence=1,
            width=320,
            height=240,
            transform_id=ResourceId("t0"),
        ),
    ]
    return FakeVideoDecoder(samples=samples)


@pytest.fixture
def privacy_service(
    repository: InMemoryMediaRepository,
    store: MediaStore,
    clock: FixedClock,
) -> DeletionService:
    return DeletionService(repository, store, NoOpProviderAssetCleaner(), clock.now)


@pytest.fixture
def deps(
    resolver: MutableOwnershipResolver,
    repository: InMemoryMediaRepository,
    store: MediaStore,
    decoder: FakeVideoDecoder,
    privacy_service: DeletionService,
    clock: FixedClock,
) -> MediaDependencies:
    boundary = AuthorizationBoundary(resolver)
    identity = FakeIdentityVerifier(
        {
            "token-a": TestIdentity("user-a", None, frozenset({"workspace-a"})),
            "token-b": TestIdentity("user-b", None, frozenset({"workspace-b"})),
        },
        profile="test",
    )

    def request_id() -> str:
        return "req-1"

    return MediaDependencies(
        identity=identity,
        authorization=boundary,
        store=store,
        decoder=decoder,
        repository=repository,
        privacy=privacy_service,
        clock=clock,
        request_id=request_id,
    )


@pytest.fixture
def client(deps: MediaDependencies) -> TestClient:
    app = FastAPI()
    app.include_router(create_media_router(deps))
    add_media_exception_handlers(app)
    return TestClient(app)


AUTH_A = {"Authorization": "Bearer token-a"}
AUTH_B = {"Authorization": "Bearer token-b"}


def small_video_bytes() -> bytes:
    # The fake decoder ignores bytes; the local store still validates hashes and sizes.
    return b"fake video bytes for testing"


def small_video_hash(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


