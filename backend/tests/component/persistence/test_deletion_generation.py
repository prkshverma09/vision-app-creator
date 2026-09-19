"""CT-REPOSITORY: deletion generation tracking."""
import pytest

from vision_app.contracts.models import SourceAsset, SourceTimeMs
from vision_app.persistence.errors import NotFoundError
from vision_app.persistence.memory import InMemoryRepository


@pytest.fixture
def asset(principal):
    workspace = next(iter(principal.workspace_ids))
    return SourceAsset(
        id="source-001",
        workspace_id=workspace,
        byte_size=1024,
        codec="h264",
        width=1920,
        height=1080,
        duration_ms=SourceTimeMs(30000),
        storage_ref="storage-001",
        sha256="a" * 64,
        state="ready",
        generation=3,
    )


@pytest.mark.asyncio
async def test_request_deletion_requires_expected_generation(
    repository: InMemoryRepository, principal, asset
):
    await repository.add_immutable("assets", asset.id.root, asset)

    # Wrong expected generation is rejected.
    assert not await repository.request_deletion("assets", asset.id.root, expected_generation=2, principal=principal)

    # Correct expected generation succeeds.
    assert await repository.request_deletion("assets", asset.id.root, expected_generation=3, principal=principal)

    # A later stale request fails because generation has advanced.
    assert not await repository.request_deletion("assets", asset.id.root, expected_generation=3, principal=principal)


@pytest.mark.asyncio
async def test_bump_deletion_generation_increments_atomically(
    repository: InMemoryRepository, principal
):
    workspace = next(iter(principal.workspace_ids))
    asset = SourceAsset(
        id="source-002",
        workspace_id=workspace,
        byte_size=1024,
        codec="h264",
        width=1920,
        height=1080,
        duration_ms=SourceTimeMs(30000),
        storage_ref="storage-002",
        sha256="b" * 64,
        state="ready",
        generation=1,
    )
    await repository.add_immutable("assets", asset.id.root, asset)

    gen1 = await repository.bump_deletion_generation("assets", asset.id.root, principal)
    gen2 = await repository.bump_deletion_generation("assets", asset.id.root, principal)
    assert gen2 == gen1 + 1

    stored = await repository.get_owned("assets", asset.id.root, principal)
    assert stored.generation == gen2


@pytest.mark.asyncio
async def test_bump_missing_resource_raises_not_found(
    repository: InMemoryRepository, principal
):
    with pytest.raises(NotFoundError):
        await repository.bump_deletion_generation("assets", "missing", principal)
