"""CT-API-RUNS: authorized durable run, progress, event and cancellation routes."""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vision_app.api.runs import InMemoryRunRepository, RunDependencies, create_runs_router
from vision_app.contracts.models import (
    EvidenceManifest,
    Event,
    MoneyMicrousd,
    ResourceId,
    RunProgress,
    SourceTimeMs,
    TimeRange,
)
from vision_app.jobs import InMemoryEventSink, InMemoryJobExecutor, JobDispatchService
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    InMemoryOwnershipResolver,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity


class JobRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}

    async def get_owned(self, kind: str, resource_id: str, principal: object) -> object:
        del principal
        return self.values.get((kind, resource_id))

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: object
    ) -> bool:
        current = self.values.get((kind, resource_id))
        current_revision = 0 if current is None else int(current["revision"])  # type: ignore[index]
        if current_revision != revision:
            return False
        self.values[(kind, resource_id)] = value
        return True


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


@pytest.fixture
def harness() -> tuple[TestClient, InMemoryRunRepository, InMemoryJobExecutor, JobDispatchService]:
    ownership = [
        ResourceOwnership(ResourceFamily.VERSION, "version-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.ASSET, "asset-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.CALIBRATION, "calibration-a", "workspace-a"),
    ]
    resolver = InMemoryOwnershipResolver(ownership)
    boundary = AuthorizationBoundary(resolver)
    identity = FakeIdentityVerifier(
        {
            "token-a": TestIdentity("user-a", None, frozenset({"workspace-a"})),
            "token-b": TestIdentity("user-b", None, frozenset({"workspace-b"})),
        },
        profile="test",
    )
    executor = InMemoryJobExecutor()
    jobs = JobDispatchService(JobRepository(), executor, InMemoryEventSink(), Clock(), Ids())
    runs = InMemoryRunRepository(resolver=resolver)
    app = FastAPI()
    app.include_router(create_runs_router(RunDependencies(identity, boundary, runs, jobs)))
    return TestClient(app), runs, executor, jobs


def auth(token: str = "token-a") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_run(client: TestClient, key: str = "request-1") -> str:
    response = client.post(
        "/workspaces/workspace-a/runs",
        headers={**auth(), "Idempotency-Key": key},
        json={
            "version_id": "version-a",
            "asset_id": "asset-a",
            "calibration_id": "calibration-a",
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def test_unauthorized_resource_access_is_safe_404(harness: tuple[object, ...]) -> None:
    client = harness[0]
    response = client.post(
        "/workspaces/workspace-a/runs",
        headers={**auth("token-b"), "Idempotency-Key": "hidden"},
        json={"version_id": "version-a", "asset_id": "asset-a"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert "workspace-a" not in response.text and "version-a" not in response.text


def test_duplicate_create_is_one_durable_run(harness: tuple[object, ...]) -> None:
    client, _, executor, _ = harness
    first = create_run(client)
    second = create_run(client)
    assert first == second
    assert executor.submission_count == 1


def test_progress_is_ordered_and_reconnect_cursor_is_exclusive(harness: tuple[object, ...]) -> None:
    client, runs, _, _ = harness
    run_id = create_run(client)
    runs.select_attempt(run_id, "attempt-current")
    runs.add_progress(progress(run_id, "attempt-old", 9))
    runs.add_progress(progress(run_id, "attempt-current", 2))
    runs.add_progress(progress(run_id, "attempt-current", 0))
    runs.add_progress(progress(run_id, "attempt-current", 1))

    first = client.get(
        f"/workspaces/workspace-a/runs/{run_id}/progress?after=-1&limit=2", headers=auth()
    )
    assert [item["sequence"] for item in first.json()["items"]] == [0, 1]
    second = client.get(
        f"/workspaces/workspace-a/runs/{run_id}/progress?after={first.json()['next_cursor']}",
        headers=auth(),
    )
    assert [item["sequence"] for item in second.json()["items"]] == [2]


def test_event_pagination_is_stable_and_excludes_stale_attempt(harness: tuple[object, ...]) -> None:
    client, runs, _, _ = harness
    run_id = create_run(client)
    runs.select_attempt(run_id, "attempt-current")
    runs.add_event(event(run_id, "attempt-old", "stale", 1))
    for event_id, source_time in [("event-c", 20), ("event-b", 10), ("event-a", 10)]:
        runs.add_event(event(run_id, "attempt-current", event_id, source_time))

    page1 = client.get(
        f"/workspaces/workspace-a/runs/{run_id}/events?limit=2", headers=auth()
    ).json()
    assert [item["id"] for item in page1["items"]] == ["event-a", "event-b"]
    runs.add_event(event(run_id, "attempt-current", "event-z", 5))
    page2 = client.get(
        f"/workspaces/workspace-a/runs/{run_id}/events?limit=2&cursor={page1['next_cursor']}",
        headers=auth(),
    ).json()
    assert [item["id"] for item in page2["items"]] == ["event-c"]
    detail = client.get(
        f"/workspaces/workspace-a/runs/{run_id}/events/event-c", headers=auth()
    )
    assert detail.status_code == 200 and detail.json()["source_range"]["start_ms"] == 20


def test_cancel_replay_propagates_once_to_job_executor(harness: tuple[object, ...]) -> None:
    client, _, executor, _ = harness
    run_id = create_run(client)
    first = client.post(f"/workspaces/workspace-a/runs/{run_id}/cancel", headers=auth())
    replay = client.post(f"/workspaces/workspace-a/runs/{run_id}/cancel", headers=auth())
    assert first.status_code == replay.status_code == 202
    assert first.json()["state"] == replay.json()["state"] == "cancelled"
    assert executor.cancelled_invocations == ["invocation-1"]


def progress(run_id: str, attempt_id: str, sequence: int) -> RunProgress:
    return RunProgress(
        run_id=ResourceId(run_id), attempt_id=ResourceId(attempt_id), phase="running",
        processed_ranges=[TimeRange(start_ms=SourceTimeMs(sequence), end_ms=SourceTimeMs(sequence + 1))],
        requested_samples=3, processed_samples=sequence, review_backlog=0,
        cancel_requested=False, usage=MoneyMicrousd(0), sequence=sequence,
    )


def event(run_id: str, attempt_id: str, event_id: str, source_time: int) -> Event:
    source_range = TimeRange(start_ms=SourceTimeMs(source_time), end_ms=SourceTimeMs(source_time + 1))
    return Event(
        id=ResourceId(event_id), run_id=ResourceId(run_id), attempt_id=ResourceId(attempt_id),
        spec_version_id=ResourceId("version-a"), calibration_id=ResourceId("calibration-a"),
        source_range=source_range, rule_id=ResourceId("rule-1"), track_refs=[], facts={"origin": "runtime"},
        evidence=EvidenceManifest(requested_range=source_range, actual_range=None, state="pending"),
        machine_decision="supported", human_review="unreviewed", revision=0,
    )
