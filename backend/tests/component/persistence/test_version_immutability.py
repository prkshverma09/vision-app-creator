"""CT-REPOSITORY: immutable versions and expected-revision conflict."""
import pytest

from vision_app.contracts.models import AppVersion, VisionApp
from vision_app.persistence.errors import ConflictError
from vision_app.persistence.memory import InMemoryRepository


@pytest.mark.asyncio
async def test_create_version_requires_matching_app_revision(
    repository: InMemoryRepository,
    principal,
    vision_app: VisionApp,
    app_version: AppVersion,
):
    await repository.add_immutable("apps", vision_app.id.root, vision_app)

    ok, app = await repository.create_version(vision_app.id.root, 1, app_version, principal)
    assert ok
    assert app is not None
    assert app.draft_version_id.root == app_version.id.root
    assert app.revision == 2

    # Same version cannot be attached again because revision moved.
    ok2, app2 = await repository.create_version(vision_app.id.root, 1, app_version, principal)
    assert not ok2


@pytest.mark.asyncio
async def test_version_is_immutable_after_create(
    repository: InMemoryRepository,
    principal,
    vision_app: VisionApp,
    app_version: AppVersion,
):
    await repository.add_immutable("apps", vision_app.id.root, vision_app)
    await repository.create_version(vision_app.id.root, 1, app_version, principal)

    # Attempting to mutate the stored version via compare_and_swap should be rejected
    # because versions are append-only.
    mutated = app_version.model_copy(update={"validation_report": ["tampered"]})
    with pytest.raises(ConflictError):
        await repository.compare_and_swap("versions", app_version.id.root, 0, mutated)


@pytest.mark.asyncio
async def test_stale_app_revision_rejected(
    repository: InMemoryRepository,
    principal,
    vision_app: VisionApp,
    app_version: AppVersion,
):
    await repository.add_immutable("apps", vision_app.id.root, vision_app)
    await repository.create_version(vision_app.id.root, 1, app_version, principal)

    second_version = app_version.model_copy(update={"id": "version-002", "validation_report": ["ok2"]})
    ok, app = await repository.create_version(vision_app.id.root, 1, second_version, principal)
    assert not ok


@pytest.mark.asyncio
async def test_publish_version_requires_existing_draft(
    repository: InMemoryRepository,
    principal,
    vision_app: VisionApp,
    app_version: AppVersion,
):
    await repository.add_immutable("apps", vision_app.id.root, vision_app)
    await repository.create_version(vision_app.id.root, 1, app_version, principal)

    ok = await repository.publish_version(
        vision_app.id.root, app_version.id.root, expected_revision=2, principal=principal
    )
    assert ok

    published = await repository.get_owned("apps", vision_app.id.root, principal)
    assert published.published_version_id.root == app_version.id.root
    assert published.revision == 3

    # Stale publish fails.
    ok2 = await repository.publish_version(
        vision_app.id.root, app_version.id.root, expected_revision=2, principal=principal
    )
    assert not ok2
