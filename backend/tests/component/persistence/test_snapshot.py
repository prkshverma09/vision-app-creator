"""Durable local domain-state snapshots and failure-safe recovery."""
from __future__ import annotations

import asyncio
import itertools
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from vision_app.api.runs.router import RunRecord
from vision_app.contracts.models import (
    BoxN,
    Calibration,
    Event,
    EvidenceManifest,
    FrameRef,
    MoneyMicrousd,
    PointN,
    ResourceId,
    RunProgress,
    SemanticCondition,
    SemanticWindowsSpec,
    SourceAsset,
    SourceTimeMs,
    TimeRange,
    UtcTimestamp,
)
from vision_app.jobs.service import JobDispatchService
from vision_app.persistence.memory import InMemoryRepository
from vision_app.persistence.snapshot import LocalStateSnapshot, SnapshotError


def components():
    core = InMemoryRepository()
    media = SimpleNamespace(_assets={}, _revisions={}, _store=object())
    deps = SimpleNamespace(
        app_sources={}, app_calibrations={}, app_seed_assets={},
        upload_resources={"grant": "ephemeral-upload"},
        gemini_api_key="never-write-this-provider-key", test_token="never-write-this-token",
    )
    jobs = SimpleNamespace(_jobs={}, _lock=asyncio.Lock())
    ids = SimpleNamespace(_counter=itertools.count(1))
    return core, media, deps, jobs, ids


def event():
    source_range = TimeRange(start_ms=SourceTimeMs(100), end_ms=SourceTimeMs(300))
    return Event(
        id=ResourceId("event-1"), run_id=ResourceId("run-1"),
        attempt_id=ResourceId("attempt-1"), spec_version_id=ResourceId("version-001"),
        calibration_id=ResourceId("calibration-1"), source_range=source_range,
        rule_id=ResourceId("rule-001"), track_refs=["track-1"],
        facts={"count": 3, "confidence": 0.92, "nested": [True, None, {"label": "person"}]},
        evidence=EvidenceManifest(requested_range=source_range, actual_range=source_range,
                                  state="available", clip_ref=ResourceId("clip-1")),
        machine_decision="supported", human_review="unreviewed", revision=0,
    )


@pytest.mark.asyncio
async def test_roundtrip_domain_models_bindings_reviews_ownership_and_ids(
    tmp_path, vision_app, app_version, now, principal,
):
    original = components()
    core, media, deps, jobs, ids = original
    await core.add_immutable("apps", vision_app.id.root, vision_app)
    assert (await core.create_version(vision_app.id.root, 1, app_version, principal))[0]
    assert await core.publish_version(vision_app.id.root, app_version.id.root, 2, principal)
    semantic = app_version.model_copy(update={
        "id": ResourceId("semantic-version"),
        "spec": SemanticWindowsSpec(
            kind="semantic_windows", title="Door", objective="Watch door",
            conditions=[SemanticCondition(condition_id=ResourceId("door"), prompt="Door open")],
            window_ms=2000, stride_ms=1000, sample_fps=2,
        ),
    })
    await core.add_immutable("versions", semantic.id.root, semantic)
    other = vision_app.model_copy(update={
        "id": ResourceId("other-app"), "workspace_id": ResourceId("other-workspace"),
    })
    await core.add_immutable("apps", other.id.root, other)
    calibration = Calibration(
        id=ResourceId("calibration-1"), source_id=ResourceId("source-1"),
        workspace_id=vision_app.workspace_id, camera_binding="camera-1", revision=1,
        reference_frame=FrameRef(
            source_id=ResourceId("source-1"), source_hash="a" * 64, pts=100,
            time_base_num=1, time_base_den=1000, source_time_ms=SourceTimeMs(100),
            sequence=0, width=640, height=480, transform_id=ResourceId("transform-1"),
        ),
        lanes={}, lines={"line-1": [PointN(x=0.1, y=0.2), PointN(x=0.8, y=0.9)]},
        rois={"roi-1": BoxN(x1=0.1, y1=0.2, x2=0.8, y2=0.9)}, governing_signals={},
        scene_fingerprint="scene-1", confirmed_by=ResourceId("user-001"),
        confirmed_at=UtcTimestamp(now),
    )
    await core.add_immutable("calibration", calibration.id.root, calibration)
    asset = SourceAsset(
        id=ResourceId("source-1"), workspace_id=vision_app.workspace_id,
        byte_size=4000, codec="h264", width=640, height=480, duration_ms=SourceTimeMs(1000),
        storage_ref=ResourceId("source-1"), sha256="a" * 64, state="ready", generation=2,
        retention_until=UtcTimestamp(now),
    )
    media._assets[asset.id.root] = asset
    media._revisions[asset.id.root] = 4
    deps.app_sources[vision_app.id.root] = asset.id.root
    deps.app_seed_assets[vision_app.id.root] = asset.id.root
    deps.app_calibrations[vision_app.id.root] = calibration.id.root
    run = RunRecord("run-1", "ws-001", app_version.id.root, asset.id.root, calibration.id.root)
    core._seed_budget("ws-001", 1000)
    budget_account = {
        "workspace_id": "ws-001", "revision": 0, "limit_microusd": 1000,
        "reservations": {"reservation-1": {"estimate": 30}},
        "updated_at": now, "coordinates": (1, 2),
    }
    await core.compare_and_swap("budget_account", "ws-001", 0, budget_account)
    assert (await core.reserve_quota_and_create_run(
        "ws-001", "user-001", 30, "reservation-1", run, principal, "create-once",
    ))[0]
    assert await core.claim_attempt(run.id, "attempt-1", "worker-1", 1)
    assert await core.commit_event(run.id, "attempt-1", 1, event())
    reviewed = await core.review_event(run.id, "event-1", 0, "confirmed_by_user", principal)
    assert await core.finalize_run(run.id, "attempt-1", "completed")
    job = JobDispatchService._initial(run.id)
    job.update(state="completed", attempt_id="attempt-1", fence=1)
    jobs._jobs[run.id] = job
    for _ in range(17):
        next(ids._counter)
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(*original)
    restored = components()
    assert snapshot.restore(*restored)
    new_core, new_media, new_deps, new_jobs, new_ids = restored
    app = await new_core.get_owned("apps", vision_app.id.root, principal)
    assert app.draft_version_id == app_version.id
    assert app.published_version_id == app_version.id
    assert app.revision == 3
    assert await new_core.get_owned("versions", app_version.id.root, principal) == app_version
    assert await new_core.get_owned("versions", semantic.id.root, principal) == semantic
    assert await new_core.get_owned("calibration", calibration.id.root, principal) == calibration
    assert await new_core.get_owned("events", "event-1", principal) == reviewed
    assert await new_core.get_owned("budget_account", "ws-001", principal) == budget_account
    assert await new_core.get_owned("apps", "other-app", principal) is None
    assert await new_core.get_owned("apps", vision_app.id.root, "other-workspace") is None
    assert await new_core.resolve_workspace("apps", "other-app") == "other-workspace"
    assert new_media._assets == media._assets
    assert new_media._revisions == media._revisions
    assert new_deps.app_sources == deps.app_sources
    assert new_deps.app_calibrations == deps.app_calibrations
    assert new_deps.app_seed_assets == deps.app_seed_assets
    assert new_jobs._jobs[run.id]["state"] == "completed"
    assert next(new_ids._counter) == next(ids._counter) == 18
    assert await new_core.release_reservation("reservation-1")
    assert new_core._budgets["ws-001"] == 1000
    created, existing = await new_core.reserve_quota_and_create_run(
        "ws-001", "user-001", 30, "reservation-2", run, principal, "create-once",
    )
    assert created and existing.id == run.id
    text = snapshot.path.read_text()
    assert "never-write" not in text
    assert "upload_resources" not in text
    assert "ephemeral-upload" not in text
    assert "api_key" not in text
    assert os.stat(snapshot.path).st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "dispatching", "dispatched", "running"])
async def test_restore_marks_interrupted_jobs_failed(tmp_path, state):
    original = components()
    core, _, _, jobs, _ = original
    run = RunRecord("run-1", "ws-001", "version-1", "source-1", None)
    await core.create_run(run, "ws-001", "key", "reservation")
    await core.claim_attempt("run-1", "attempt-1", "worker-1", 3)
    progress = RunProgress(
        run_id=ResourceId("run-1"), attempt_id=ResourceId("attempt-1"), phase="running",
        processed_ranges=[], requested_samples=10, processed_samples=4,
        review_backlog=1, cancel_requested=False, usage=MoneyMicrousd(30), sequence=2,
    )
    await core.commit_progress("run-1", "attempt-1", 3, progress)
    job = JobDispatchService._initial("run-1")
    job.update(state=state, attempt_id="attempt-1", fence=3,
               heartbeat_at=datetime.now(UTC), lease_expires_at=datetime.now(UTC))
    jobs._jobs["run-1"] = job
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(*original)
    restored = components()
    snapshot.restore(*restored)
    new_core, _, _, new_jobs, _ = restored
    recovered = new_jobs._jobs["run-1"]
    assert recovered["state"] == "failed"
    assert recovered["failure_reason"] == "interrupted_by_restart"
    assert recovered["lease_expires_at"] is None
    assert recovered["fence"] == 4
    assert new_core._run_active_attempts == {}
    assert not await new_core.commit_progress("run-1", "attempt-1", 3, progress)
    final = new_core._store["ws-001"]["run_progress"]["run-1:attempt-1:3"].value
    assert final.phase == "failed" and final.processed_samples == 4
    assert (await new_core.get_owned("run", "run-1", "ws-001")).selected_attempt_id == "attempt-1"
    await snapshot.save(*restored)
    second_restore = components()
    snapshot.restore(*second_restore)
    assert second_restore[3]._jobs["run-1"]["revision"] == recovered["revision"]


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["truncated", "type", "ownership", "version", "duplicate"])
async def test_corrupt_snapshot_aborts_without_changing_memory(
    tmp_path, vision_app, corruption,
):
    original = components()
    await original[0].add_immutable("apps", vision_app.id.root, vision_app)
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(*original)
    payload = json.loads(snapshot.path.read_text())
    if corruption == "type":
        payload["core"]["documents"][0]["value"]["type"] = "os.system"
    elif corruption == "ownership":
        payload["core"]["documents"][0]["workspace"] = "attacker"
    elif corruption == "version":
        payload["format_version"] = 99
    elif corruption == "duplicate":
        payload["core"]["documents"].append(payload["core"]["documents"][0])
    snapshot.path.write_text("{" if corruption == "truncated" else json.dumps(payload))
    before = snapshot.path.read_bytes()
    restored = components()
    restored[0]._seed_budget("untouched", 42)
    restored[2].app_sources["untouched"] = "source"
    with pytest.raises(SnapshotError, match="refusing to start with empty state"):
        snapshot.restore(*restored)
    assert restored[0]._budgets == {"untouched": 42}
    assert restored[2].app_sources == {"untouched": "source"}
    assert snapshot.path.read_bytes() == before


@pytest.mark.asyncio
async def test_failed_atomic_replace_keeps_previous_snapshot(tmp_path, vision_app, monkeypatch):
    original = components()
    core = original[0]
    await core.add_immutable("apps", vision_app.id.root, vision_app)
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(*original)
    before = snapshot.path.read_bytes()
    await core.compare_and_swap("apps", vision_app.id.root, 1,
                                vision_app.model_copy(update={"title": "new title"}))

    def fail_replace(source, destination):
        assert snapshot.path.read_bytes() == before
        with open(source) as stream:
            assert json.load(stream)["format_version"] == 1
        raise OSError("disk failure")

    monkeypatch.setattr("vision_app.persistence.snapshot.os.replace", fail_replace)
    with pytest.raises(SnapshotError, match="Cannot save local state"):
        await snapshot.save(*original)
    assert snapshot.path.read_bytes() == before
    assert list(tmp_path.glob(".local-state-*")) == []
    restored = components()
    snapshot.restore(*restored)
    restored_app = await restored[0].get_owned("apps", vision_app.id.root, "ws-001")
    assert restored_app.title == vision_app.title


@pytest.mark.asyncio
async def test_credentials_and_unlisted_objects_are_rejected(tmp_path):
    original = components()
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(*original)
    before = snapshot.path.read_bytes()
    for forbidden in ({"api_key": "secret-value"}, {"token": "secret-value"}, object()):
        original[0]._store.clear()
        await original[0].add_immutable("custom", "record", {
            "workspace_id": "ws-001", "id": "record", "nested": forbidden,
        })
        with pytest.raises(SnapshotError):
            await snapshot.save(*original)
        assert snapshot.path.read_bytes() == before
        assert "secret-value" not in snapshot.path.read_text()


@pytest.mark.asyncio
async def test_transactions_gate_interleaving_and_reentrant_save(tmp_path, vision_app):
    original = components()
    core = original[0]
    snapshot = LocalStateSnapshot(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def mutation():
        async with snapshot.transaction():
            await core.add_immutable("apps", vision_app.id.root, vision_app)
            entered.set()
            await release.wait()
            original[2].app_sources[vision_app.id.root] = "source-1"
            await snapshot.save(*original)

    task = asyncio.create_task(mutation())
    await entered.wait()
    save = asyncio.create_task(snapshot.save(*original))
    await asyncio.sleep(0)
    assert not save.done()
    assert not snapshot.path.exists()
    release.set()
    await asyncio.wait_for(asyncio.gather(task, save), timeout=2)
    restored = components()
    snapshot.restore(*restored)
    assert restored[2].app_sources == {vision_app.id.root: "source-1"}
    assert await restored[0].get_owned("apps", vision_app.id.root, "ws-001") is not None


@pytest.mark.asyncio
async def test_active_run_without_job_summary_is_interrupted(tmp_path):
    original = components()
    core, media, deps, _, ids = original
    run = RunRecord("run-1", "ws-001", "version-1", "source-1", None)
    await core.create_run(run, "ws-001", "key", "reservation")
    await core.claim_attempt("run-1", "attempt-1", "worker-1", 1)
    snapshot = LocalStateSnapshot(tmp_path)
    await snapshot.save(core, media, deps, id_factory=ids)
    restored = components()
    snapshot.restore(*restored)
    assert restored[3]._jobs["run-1"]["state"] == "failed"
    assert restored[3]._jobs["run-1"]["failure_reason"] == "interrupted_by_restart"
    assert restored[0]._run_active_attempts == {}
    progress = restored[0]._store["ws-001"]["run_progress"]
    assert next(iter(progress.values())).value.phase == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_index", [0, 3])
async def test_save_waits_for_repository_locks(tmp_path, lock_index):
    original = components()
    snapshot = LocalStateSnapshot(tmp_path)
    async with original[lock_index]._lock:
        task = asyncio.create_task(snapshot.save(*original))
        await asyncio.sleep(0)
        assert not task.done()
        assert not snapshot.path.exists()
        original[0]._seed_budget("ws-001", 10)
    await asyncio.wait_for(task, timeout=2)
    restored = components()
    snapshot.restore(*restored)
    assert restored[0]._budgets == {"ws-001": 10}


def test_absent_snapshot_is_the_only_empty_start(tmp_path):
    snapshot = LocalStateSnapshot(tmp_path)
    assert snapshot.restore(*components()) is False
    assert not snapshot.path.exists()
