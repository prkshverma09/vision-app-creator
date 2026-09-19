"""CT-REPOSITORY: concurrent quota reservations cannot oversubscribe."""
import asyncio

import pytest

from vision_app.contracts.models import MoneyMicrousd, ResourceId, RunProgress
from vision_app.persistence.memory import InMemoryRepository


def _run(run_id: str) -> RunProgress:
    return RunProgress(
        run_id=ResourceId(run_id),
        attempt_id=ResourceId("attempt-001"),
        phase="queued",
        processed_ranges=[],
        requested_samples=10,
        processed_samples=0,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=0,
    )


@pytest.mark.asyncio
async def test_only_one_concurrent_reservation_succeeds_when_one_slot_left(
    repository: InMemoryRepository, workspace_id, principal
):
    repository._seed_budget(workspace_id, 1000)

    async def reserve(run_id: str):
        return await repository.reserve_quota_and_create_run(
            workspace_id=workspace_id,
            owner_id=run_id,
            microusd=1000,
            reservation_id=f"res-{run_id}",
            run=_run(run_id),
            principal=principal,
            idempotency_key=f"idem-{run_id}",
        )

    results = await asyncio.gather(
        reserve("run-a"), reserve("run-b"), return_exceptions=True
    )
    successes = [r for r in results if not isinstance(r, Exception) and r[0]]
    failures = [r for r in results if isinstance(r, Exception) or not r[0]]
    assert len(successes) == 1, f"expected exactly one success, got {results}"
    assert len(failures) == 1


@pytest.mark.asyncio
async def test_reservation_with_available_budget_succeeds(
    repository: InMemoryRepository, workspace_id, principal
):
    repository._seed_budget(workspace_id, 1000)

    ok1, run1 = await repository.reserve_quota_and_create_run(
        workspace_id=workspace_id,
        owner_id="run-001",
        microusd=500,
        reservation_id="res-001",
        run=_run("run-001"),
        principal=principal,
        idempotency_key="idem-001",
    )
    assert ok1
    assert run1 is not None

    ok2, _ = await repository.reserve_quota_and_create_run(
        workspace_id=workspace_id,
        owner_id="run-002",
        microusd=500,
        reservation_id="res-002",
        run=_run("run-002"),
        principal=principal,
        idempotency_key="idem-002",
    )
    assert ok2

    ok3, _ = await repository.reserve_quota_and_create_run(
        workspace_id=workspace_id,
        owner_id="run-003",
        microusd=1,
        reservation_id="res-003",
        run=_run("run-003"),
        principal=principal,
        idempotency_key="idem-003",
    )
    assert not ok3


@pytest.mark.asyncio
async def test_reservation_and_run_creation_is_idempotent(
    repository: InMemoryRepository, workspace_id, principal
):
    repository._seed_budget(workspace_id, 1000)

    ok1, run1 = await repository.reserve_quota_and_create_run(
        workspace_id=workspace_id,
        owner_id="run-001",
        microusd=500,
        reservation_id="res-001",
        run=_run("run-001"),
        principal=principal,
        idempotency_key="idem-same",
    )
    assert ok1

    ok2, run2 = await repository.reserve_quota_and_create_run(
        workspace_id=workspace_id,
        owner_id="run-001-copy",
        microusd=500,
        reservation_id="res-001-copy",
        run=_run("run-001-copy"),
        principal=principal,
        idempotency_key="idem-same",
    )
    assert ok2
    assert run2 is not None
    # Idempotent replay returns the original run document.
    assert run2.run_id.root == run1.run_id.root
