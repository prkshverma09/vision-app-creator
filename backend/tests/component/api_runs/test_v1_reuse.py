from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from vision_app.bootstrap import _LocalJobExecutor, create_app
from vision_app.contracts.models import ResourceId, SourceAsset, SourceTimeMs, UtcTimestamp


SPEC = {
    "kind": "semantic_windows", "title": "Safety", "objective": "Find smoke",
    "conditions": [{"condition_id": "smoke", "prompt": "Smoke is visible"}],
    "window_ms": 5000, "stride_ms": 2500, "sample_fps": 1,
}


def test_provider_configuration_error_is_not_reported_as_unsupported_capability():
    from vision_app.api.v1.router import _build_turn_response
    from vision_app.contracts.models import BuildTurn

    turn = BuildTurn(
        id=ResourceId("turn-1"), app_id=ResourceId("app-1"), instruction="Find cars crossing on red",
        base_revision=0, status="unsupported", tool_progress=["unsupported:provider_model_unavailable"],
    )
    response = _build_turn_response(turn)
    assert response["outcome"]["code"] == "provider_model_unavailable"
    assert "GEMINI_MODEL" in response["reply"]
    assert "capability set" not in response["reply"]


async def seed_asset(app, asset_id: str, workspace: str = "workspace-local", state: str = "ready"):
    asset = SourceAsset(
        id=ResourceId(asset_id), workspace_id=ResourceId(workspace), byte_size=20,
        codec="h264", width=320, height=240, duration_ms=SourceTimeMs(1000),
        storage_ref=ResourceId(asset_id), sha256="a" * 64, state=state, generation=1,
        retention_until=UtcTimestamp(datetime.now(UTC) + timedelta(days=1)),
    )
    await app.state.v1_dependencies.media.repository.save_asset(asset)


@pytest.mark.asyncio
async def test_semantic_reuse_and_lineage(tmp_path: Path):
    app = create_app("local", {"data_dir": tmp_path})
    await seed_asset(app, "seed")
    await seed_asset(app, "second")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        app_id = (await client.post("/v1/apps", json={"name": "Safety"})).json()["id"]
        attached = await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "seed"})
        assert attached.status_code == 200
        assert attached.json()["seed_asset_id"] == "seed"
        accepted = await client.post(f"/v1/apps/{app_id}/versions", json={"spec": SPEC})
        assert accepted.status_code == 200, accepted.text
        version = accepted.json()["published_version_id"]
        assert version
        assert accepted.json()["requires_calibration"] is False
        first = await client.post(f"/v1/apps/{app_id}/runs", json={})
        assert first.status_code == 202, first.text
        app.state.v1_dependencies.app_calibrations[app_id] = "old-calibration"
        replaced = (await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "second"})).json()
        assert replaced["seed_asset_id"] == "seed"
        assert replaced["calibration_id"] is None
        assert replaced["published_version_id"] == version
        assert replaced["spec"] == accepted.json()["spec"]
        second = await client.post(f"/v1/apps/{app_id}/runs", json={"asset_id": "second", "version_id": version})
        assert second.status_code == 202
        await asyncio.sleep(0.02)
        detail = (await client.get(f"/v1/runs/{second.json()['run_id']}" )).json()["run"]
        assert detail["app_id"] == app_id
        assert detail["version_id"] == version
        assert detail["asset_id"] == "second"
        assert detail["is_seed_run"] is False
        assert detail["analysis_mode"] == "scripted"
        assert detail["status"] == "failed"
        assert detail["failure_reason"]
        runs = (await client.get(f"/v1/apps/{app_id}/runs")).json()["runs"]
        assert len(runs) == 2
        assert {run["is_seed_run"] for run in runs} == {True, False}


@pytest.mark.asyncio
async def test_run_result_context_keeps_the_definition_used_for_that_run(tmp_path: Path):
    app = create_app("local", {"data_dir": tmp_path})
    await seed_asset(app, "seed")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        app_id = (await client.post("/v1/apps", json={"name": "Safety"})).json()["id"]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "seed"})
        original = (await client.post(f"/v1/apps/{app_id}/versions", json={"spec": SPEC})).json()
        started = await client.post(f"/v1/apps/{app_id}/runs", json={})
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        replacement = {**SPEC, "title": "New definition", "objective": "Find water"}
        accepted = await client.post(f"/v1/apps/{app_id}/versions", json={"spec": replacement})
        assert accepted.status_code == 200
        await asyncio.sleep(0.02)
        detail = (await client.get(f"/v1/runs/{run_id}")).json()["run"]
        assert detail["spec"] == original["spec"]
        assert detail["version_id"] == original["published_version_id"]
        assert detail["spec"]["title"] != accepted.json()["spec"]["title"]
        assert detail["status"] == "failed"
        assert detail["analysis_complete"] is False


@pytest.mark.asyncio
async def test_live_configuration_and_consent(tmp_path: Path):
    app = create_app("live", {"data_dir": tmp_path})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        runtime = (await client.get("/v1/runtime")).json()
        assert runtime["analysis_mode"] == "gemini"
        assert runtime["configured"] is False
        assert runtime["external_processing"] is True
        assert runtime["model"] == "gemini-3.6-flash"
        assert runtime["limits"] == {"max_duration_ms": 60000, "max_bytes": 14000000}
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        response = await client.post(f"/v1/apps/{app_id}/turns", json={"message": "Find smoke", "confirm_external_processing": True})
        assert response.status_code == 409
        response = await client.post(f"/v1/apps/{app_id}/runs", json={"confirm_external_processing": True})
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_executor_does_not_wait_for_worker():
    started, release = asyncio.Event(), asyncio.Event()

    async def worker(cancelled):
        started.set()
        await release.wait()

    executor = _LocalJobExecutor(lambda run_id: worker)
    try:
        invocation = await asyncio.wait_for(executor.submit("run-1"), timeout=0.1)
        await asyncio.wait_for(started.wait(), timeout=0.1)
        assert (await executor.query(invocation))["state"] == "running"
    finally:
        release.set()
    await asyncio.gather(*executor._tasks.values())


@pytest.mark.asyncio
async def test_run_validation_and_tracked_source_calibration(tmp_path: Path):
    app = create_app("local", {"data_dir": tmp_path})
    await seed_asset(app, "seed")
    await seed_asset(app, "second")
    await seed_asset(app, "foreign", "workspace-other")
    await seed_asset(app, "invalid", state="invalid")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        other_id = (await client.post("/v1/apps", json={})).json()["id"]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "seed"})
        assert (await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "foreign"})).status_code == 404
        assert (await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "invalid"})).status_code == 409
        proposal = (await client.post(f"/v1/apps/{app_id}/turns", json={"message": "Find crossings"})).json()["outcome"]["version"]
        accepted = (await client.post(f"/v1/apps/{app_id}/versions", json={"spec": proposal})).json()
        assert accepted["requires_calibration"] is True
        assert accepted["published_version_id"] is None
        assert (await client.post(f"/v1/apps/{app_id}/runs")).status_code == 409
        calibrated = await client.post(f"/v1/apps/{app_id}/calibrations", json={"geometries": []})
        assert calibrated.status_code == 200
        calibration_id = calibrated.json()["calibration_id"]
        version_id = (await client.get(f"/v1/apps/{app_id}")).json()["published_version_id"]
        other_version = (await client.post(f"/v1/apps/{other_id}/versions", json={"spec": SPEC})).json()["published_version_id"]
        for body, expected in [
            ({"asset_id": "second", "calibration_id": calibration_id}, 409),
            ({"asset_id": "foreign"}, 404),
            ({"asset_id": "invalid"}, 409),
            ({"version_id": other_version}, 409),
            ({"calibration_id": None}, 409),
        ]:
            response = await client.post(f"/v1/apps/{app_id}/runs", json=body)
            assert response.status_code == expected, response.text
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "second"})
        detail = (await client.get(f"/v1/apps/{app_id}")).json()
        assert detail["published_version_id"] == version_id
        assert detail["calibration_id"] is None
        assert (await client.post(f"/v1/apps/{app_id}/runs")).status_code == 409
        assert (await client.get(f"/v1/apps/{other_id}/runs")).json() == {"runs": []}


@pytest.mark.asyncio
async def test_seed_is_sent_to_compiler_after_replacing_current_source(tmp_path: Path, monkeypatch):
    app = create_app("local", {"data_dir": tmp_path})
    await seed_asset(app, "seed")
    await seed_asset(app, "second")
    compiler = app.state.v1_dependencies.builder_agent._compiler
    original = compiler.compile
    seen = []

    async def compile(instruction, context):
        seen.append(context["source_id"])
        return await original(instruction, context)

    monkeypatch.setattr(compiler, "compile", compile)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "seed"})
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": "second"})
        await client.post(f"/v1/apps/{app_id}/turns", json={"message": "Find smoke"})
        await client.post(f"/v1/apps/{app_id}/clarifications", json={"answers": ["Smoke"]})
    assert seen == ["seed", "seed"]


@pytest.mark.asyncio
async def test_configured_live_needs_explicit_consent_and_never_uses_fixtures(tmp_path: Path):
    from vision_app.providers.gemini.live import GeminiVideoCompiler

    app = create_app("local", {"data_dir": tmp_path, "analysis_mode": "gemini", "gemini_api_key": "test-secret-not-to-expose"})
    assert isinstance(app.state.v1_dependencies.builder_agent._compiler, GeminiVideoCompiler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        runtime = await client.get("/v1/runtime")
        assert runtime.json()["configured"] is True
        assert "test-secret" not in runtime.text
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        for path, body in [("turns", {"message": "Find smoke"}), ("clarifications", {"answers": ["Smoke"]}), ("runs", {})]:
            response = await client.post(f"/v1/apps/{app_id}/{path}", json=body)
            assert response.status_code == 409
            assert response.json()["code"] == "external_processing_confirmation_required"
        legacy = await client.post("/workspaces/workspace-local/builds/build-1/turns", json={"instruction": "Find smoke"})
        assert legacy.status_code == 409
        oversized = await client.post("/v1/uploads", json={"content_type": "video/mp4", "size_bytes": 14000001})
        assert oversized.status_code in {409, 413, 422}


@pytest.mark.asyncio
async def test_live_compiles_seed_and_reuses_version_for_independent_videos(tmp_path: Path, monkeypatch):
    import json
    from vision_app.providers.gemini.live import GeminiVideoTransport, VideoResponse

    seen = []

    async def generate(self, prompt, schema, *, video=None, sample_fps=None, before_attempt=None):
        assert video and video[4:8] == b"ftyp"
        seen.append(video)
        if before_attempt:
            before_attempt()
        if "supported" in schema["properties"]:
            return VideoResponse({"supported": True, "title": "Safety", "objective": "Find smoke", "conditions": ["Smoke is visible"]})
        conditions = json.loads(prompt.split("Saved conditions: ")[1])
        present = len(seen) == 2
        return VideoResponse({"conditions": [{
            "condition_id": conditions[0]["condition_id"],
            "decision": "present" if present else "absent", "reason": "Visible evidence assessed",
            "events": [{"start_ms": 100, "end_ms": 500, "description": "Visible smoke", "reason": "Smoke appears"}] if present else [],
        }]})

    monkeypatch.setattr(GeminiVideoTransport, "generate", generate)
    app = create_app("live", {"data_dir": tmp_path, "gemini_api_key": "test-key"})
    fixtures = Path(__file__).resolve().parents[4] / "fixtures" / "synthetic" / "video"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def upload(name):
            data = (fixtures / name).read_bytes()
            grant = (await client.post("/v1/uploads", json={"content_type": "video/mp4", "size_bytes": len(data)})).json()
            assert (await client.put(grant["upload_url"], content=data)).status_code == 204
            response = await client.post(f"/v1/uploads/{grant['upload_id']}/complete")
            assert response.status_code == 200, response.text
            return response.json()["asset_id"], data

        seed, seed_data = await upload("red_light_violation.mp4")
        second, _ = await upload("empty_scene.mp4")
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": seed})
        proposal = await client.post(f"/v1/apps/{app_id}/turns", json={"message": "Find smoke", "confirm_external_processing": True})
        assert proposal.json()["outcome"]["kind"] == "proposed_version", proposal.text
        accepted = (await client.post(f"/v1/apps/{app_id}/versions", json={"spec": proposal.json()["outcome"]["version"]})).json()
        version = accepted["published_version_id"]
        assert seen == [seed_data]
        for asset, expected_events in [(seed, 1), (second, 0)]:
            started = await client.post(f"/v1/apps/{app_id}/runs", json={"asset_id": asset, "version_id": version, "confirm_external_processing": True})
            assert started.status_code == 202, started.text
            for _ in range(300):
                result = (await client.get(f"/v1/runs/{started.json()['run_id']}")).json()
                if result["run"]["status"] in {"succeeded", "failed"}:
                    break
                await asyncio.sleep(0.02)
            assert result["run"]["status"] == "succeeded", result
            assert result["run"]["analysis_complete"] is True
            assert result["run"]["spec"] == accepted["spec"]
            assert result["run"]["version_id"] == version
            assert result["run"]["analysis_mode"] == "gemini"
            assert len(result["events"]) == expected_events
            if expected_events:
                event_id = result["events"][0]["id"]
                reviewed = await client.post(f"/v1/events/{event_id}/review", json={"human_review": "confirmed_by_user"})
                assert reviewed.status_code == 200
        assert len(seen) == 3
        assert seen[1] != seen[2]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": second})
        original_runs = (await client.get(f"/v1/apps/{app_id}/runs")).json()["runs"]
        assert len(original_runs) == 2
    await asyncio.gather(*app.state.executor._tasks.values())
    from vision_app.api.runs.router import RunCreate
    deps = app.state.v1_dependencies
    async with app.state.snapshot.transaction():
        interrupted = await deps.runs.create("workspace-local", RunCreate(version_id=version, asset_id=second), "interrupted")
        await deps.jobs.create(interrupted.id)
        lease = await deps.jobs.claim(interrupted.id)
        await deps.core_repo.claim_attempt(interrupted.id, lease.attempt_id, "test-worker", lease.fence)
        await app.state.checkpoint()
    raw = (tmp_path / "local-state.json").read_text()
    assert "test-key" not in raw
    assert "gemini_api_key" not in raw
    restarted = create_app("local", {"data_dir": tmp_path})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as client:
        detail = (await client.get(f"/v1/apps/{app_id}")).json()
        assert detail["published_version_id"] == version
        assert detail["seed_asset_id"] == seed
        assert detail["source"]["asset_id"] == second
        runs = (await client.get(f"/v1/apps/{app_id}/runs")).json()["runs"]
        assert len(runs) == 3
        assert all(run["analysis_mode"] == "gemini" for run in runs)
        first = next(run for run in runs if run["asset_id"] == seed)
        events = (await client.get(f"/v1/runs/{first['id']}")).json()["events"]
        assert events[0]["human_review"] == "confirmed_by_user"
        failed = (await client.get(f"/v1/runs/{interrupted.id}")).json()["run"]
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == "interrupted_by_restart"
        assert failed["progress"][-1]["phase"] == "failed"
        restarted.state.job_repository._jobs.pop(interrupted.id)
        fallback = (await client.get(f"/v1/runs/{interrupted.id}")).json()["run"]
        assert fallback["status"] == "failed"
        assert fallback["failure_reason"]
        next_app = (await client.post("/v1/apps", json={})).json()["id"]
        assert next_app != app_id
        assert (await client.get(f"/api/v1/media/{seed}")).status_code == 200
        assert (await client.get(f"/api/v1/media/{second}")).status_code == 200
        reused = await client.post(f"/v1/apps/{app_id}/runs", json={"asset_id": seed})
        assert reused.status_code == 202
    await asyncio.gather(*restarted.state.executor._tasks.values())


@pytest.mark.asyncio
async def test_snapshot_gate_does_not_block_compile_run_or_cancellation(tmp_path: Path, monkeypatch):
    import json
    from vision_app.providers.gemini.live import GeminiVideoTransport, VideoResponse

    compiling, running = asyncio.Event(), asyncio.Event()
    release_compile, release_run = asyncio.Event(), asyncio.Event()

    async def generate(self, prompt, schema, *, video=None, sample_fps=None, before_attempt=None):
        assert self.config.timeout_ms == 120000
        assert self.config.sample_fps == 5.0
        if before_attempt:
            before_attempt()
        if "supported" in schema["properties"]:
            compiling.set()
            await release_compile.wait()
            return VideoResponse({"supported": True, "title": "Safety", "objective": "Smoke", "conditions": ["Smoke is visible"]})
        running.set()
        await release_run.wait()
        conditions = json.loads(prompt.split("Saved conditions: ")[1])
        return VideoResponse({"conditions": [{"condition_id": conditions[0]["condition_id"], "decision": "absent", "reason": "No smoke", "events": []}]})

    monkeypatch.setattr(GeminiVideoTransport, "generate", generate)
    app = create_app("live", {"data_dir": tmp_path, "gemini_api_key": "test-secret"})
    agent = app.state.v1_dependencies.builder_agent
    original_build = agent.build

    async def build(request):
        assert request.timeout_seconds == 150
        return await original_build(request)

    monkeypatch.setattr(agent, "build", build)
    fixture = Path(__file__).resolve().parents[4] / "fixtures/synthetic/video/empty_scene.mp4"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        data = fixture.read_bytes()
        grant = (await client.post("/v1/uploads", json={"content_type": "video/mp4", "size_bytes": len(data)})).json()
        await client.put(grant["upload_url"], content=data)
        asset = (await client.post(f"/v1/uploads/{grant['upload_id']}/complete")).json()["asset_id"]
        app_id = (await client.post("/v1/apps", json={})).json()["id"]
        await client.post(f"/v1/apps/{app_id}/source", json={"asset_id": asset})
        compile_task = asyncio.create_task(client.post(f"/v1/apps/{app_id}/turns", json={"message": "Find smoke", "confirm_external_processing": True}))
        try:
            await asyncio.wait_for(compiling.wait(), 5)
            independent = await asyncio.wait_for(client.post("/v1/apps", json={"name": "Concurrent"}), 1)
            assert independent.status_code == 201
            release_compile.set()
            proposal = (await compile_task).json()["outcome"]["version"]
            await client.post(f"/v1/apps/{app_id}/versions", json={"spec": proposal})
            started = await asyncio.wait_for(client.post(f"/v1/apps/{app_id}/runs", json={"confirm_external_processing": True}), 1)
            assert started.status_code == 202
            run_id = started.json()["run_id"]
            await asyncio.wait_for(running.wait(), 5)
            cancelled = await asyncio.wait_for(client.post(f"/workspaces/workspace-local/runs/{run_id}/cancel", headers={"Authorization": "Bearer token-local"}), 1)
            assert cancelled.status_code == 202
            assert cancelled.json()["state"] == "cancelled"
        finally:
            release_compile.set()
            release_run.set()
            await compile_task
            await asyncio.gather(*app.state.executor._tasks.values())
        assert (await client.get(f"/v1/runs/{run_id}")).json()["run"]["status"] == "cancelled"
    restored = create_app("local", {"data_dir": tmp_path})
    assert (await restored.state.v1_dependencies.jobs.get(run_id)).state.value == "cancelled"
