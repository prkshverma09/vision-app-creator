"""Live REST boundary tests use local MP4s and MockTransport, never external calls."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from vision_app.contracts.models import ExecutionLimits, ResourceId, SemanticWindowsSpec
from vision_app.evidence.extractor import EvidenceExtractor
from vision_app.media.decoder import LocalVideoDecoder
from vision_app.media.types import ClipResult
from vision_app.providers.gemini.config import GeminiConfig
from vision_app.providers.gemini.live import (
    MAX_INLINE_BYTES,
    GeminiVideoCompiler,
    GeminiVideoTransport,
    VideoProviderError,
)
from vision_app.runtime.context import RunContext
from vision_app.runtime.engine import EngineRuntimeError
from vision_app.runtime.semantic_engine import GeminiSemanticEngine
from vision_app.storage.local import FileSystemMediaStore

VIDEO = Path(__file__).parents[4] / "fixtures/synthetic/video/moving_dot.mp4"
OTHER_VIDEO = VIDEO.with_name("empty_scene.mp4")
CONFIG = GeminiConfig(api_key="fake-private-test-key", max_retries=0, retry_base_ms=0)
DRAFT = {
    "supported": True, "title": "Moving object", "objective": "Look for visible motion",
    "conditions": ["Is an object visibly moving? Return uncertain if visibility is poor."],
}
pytestmark = pytest.mark.asyncio


def envelope(content):
    return {
        "candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(content)}]},
        }],
        "usageMetadata": {"promptTokenCount": 25, "candidatesTokenCount": 10},
    }


def assessment(decision="absent", condition_id="condition-1", start=100, end=500):
    return {"conditions": [{
        "condition_id": condition_id, "decision": decision, "reason": "Visual assessment",
        "events": [] if decision == "absent" else [{
            "start_ms": start, "end_ms": end,
            "description": "Object motion is visible" if decision == "present" else "View obscured",
            "reason": "Visible displacement" if decision == "present" else "Poor visibility",
        }],
    }]}


class Sink:
    def __init__(self):
        self.events = []
        self.updates = []

    async def upsert(self, event, fence):
        assert fence == 7
        self.events.append(event)

    async def progress(self, update, fence):
        assert fence == 7
        self.updates.append(update)


def spec(**updates):
    return SemanticWindowsSpec.model_validate({
        "kind": "semantic_windows", "title": "Motion", "objective": "Look for motion",
        "conditions": [{"condition_id": "condition-1", "prompt": DRAFT["conditions"][0]}],
        "window_ms": 30000, "stride_ms": 30000, "sample_fps": 2,
        "limits": {"max_duration_ms": 60000, "max_model_calls": 6}, **updates,
    })


def context(**updates):
    ctx = RunContext(
        run_id=ResourceId("run-a"), attempt_id=ResourceId("attempt-a"),
        workspace_id=ResourceId("workspace-a"), owner_id="owner-a",
        source_id=ResourceId("new-video"), source_path=OTHER_VIDEO,
        storage_ref="source-storage", source_generation=1, source_sha256=None,
        spec_version_id=ResourceId("saved-version"), spec=spec(),
    )
    return replace(ctx, **updates)


async def test_compiler_uses_actual_seed_and_reusable_generated_spec(clock, id_factory):
    requests = []
    loaded = []
    seed = VIDEO.read_bytes()

    async def loader(source_id, workspace_id):
        loaded.append((source_id, workspace_id))
        return seed

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        assert base64.b64decode(parts[0]["inlineData"]["data"]) == seed
        assert parts[0]["inlineData"]["mimeType"] == "video/mp4"
        assert parts[0]["videoMetadata"]["fps"] == 1
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
        return httpx.Response(200, json=envelope(DRAFT))

    compiler = GeminiVideoCompiler(CONFIG, clock, id_factory, loader, httpx.MockTransport(handler))
    result = await compiler.compile("Notice moving objects", {
        "source_id": "seed", "workspace_id": "workspace-a", "app_id": "app-a",
    })
    assert result.outcome.kind == "proposed_version"
    generated = result.outcome.version.spec
    assert isinstance(generated, SemanticWindowsSpec)
    assert generated.conditions[0].prompt == DRAFT["conditions"][0]
    assert generated.limits == ExecutionLimits(max_duration_ms=60000, max_model_calls=6)
    assert generated.window_ms == generated.stride_ms == 30000
    assert generated.approved_action_refs == []
    assert result.usage.adapter_mode == "video"
    assert loaded == [("seed", "workspace-a")]
    assert str(requests[0].url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    )
    assert requests[0].headers["x-goog-api-key"] == CONFIG.api_key
    assert CONFIG.api_key not in str(requests[0].url)
    assert CONFIG.api_key not in repr(CONFIG)


async def test_prompt_only_compiler_never_invents_seed(clock, id_factory):
    async def loader(*args):
        pytest.fail("No seed should be loaded")

    def handler(request):
        parts = json.loads(request.content)["contents"][0]["parts"]
        assert all("inlineData" not in part for part in parts)
        return httpx.Response(200, json=envelope(DRAFT))

    result = await GeminiVideoCompiler(
        CONFIG, clock, id_factory, loader, httpx.MockTransport(handler),
    ).compile("Find motion", {"workspace_id": "workspace-a"})
    assert result.outcome.kind == "proposed_version"
    assert result.usage.adapter_mode == "structured"


@pytest.mark.parametrize(("status", "code"), [
    (400, "provider_invalid_request"), (401, "provider_auth"), (403, "provider_auth"),
    (404, "provider_model_unavailable"), (413, "provider_payload_too_large"),
    (429, "provider_quota"), (500, "provider_unavailable"), (418, "provider_http"),
])
async def test_http_errors_redact_provider_body_and_key(status, code):
    transport = GeminiVideoTransport(CONFIG, httpx.MockTransport(lambda _: httpx.Response(
        status, text=f"secret {CONFIG.api_key} private provider internals",
    )))
    with pytest.raises(VideoProviderError) as error:
        await transport.generate("check", {})
    assert CONFIG.api_key not in str(error.value)
    assert "internals" not in str(error.value)
    assert error.value.code == code
    assert error.value.status_code == status
    assert error.value.retryable == (status in {429, 500})


async def test_compiler_preserves_model_unavailable_code_without_retry(clock, id_factory):
    calls = []

    async def loader(*args):
        pytest.fail("prompt-only compilation should not load media")

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"error": {
            "status": "NOT_FOUND",
            "message": f"Model no longer available; private diagnostic: {CONFIG.api_key}",
        }})

    compiler = GeminiVideoCompiler(
        replace(CONFIG, model="gemini-2.5-flash", max_retries=2), clock, id_factory, loader,
        httpx.MockTransport(handler),
    )
    result = await compiler.compile("Find motion", {"workspace_id": "workspace-a"})
    assert result.outcome.kind == "unsupported_request"
    assert result.outcome.code == "provider_model_unavailable"
    assert "GEMINI_MODEL" in result.outcome.reason
    assert CONFIG.api_key not in result.outcome.reason
    assert "private diagnostic" not in result.outcome.reason
    assert len(calls) == 1
    assert "gemini-2.5-flash:generateContent" in str(calls[0].url)


@pytest.mark.parametrize("payload", [
    {}, {"candidates": []}, {"candidates": [{"finishReason": "SAFETY"}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "oops"}]}}]},
    envelope({}), envelope([]), [],
])
async def test_malformed_transport_result_fails(payload):
    transport = GeminiVideoTransport(CONFIG, httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload),
    ))
    with pytest.raises(VideoProviderError, match="invalid or incomplete"):
        await transport.generate("check", {})


async def test_retry_is_bounded_and_success_reports_attempts():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, text="private provider details")
        return httpx.Response(200, json=envelope(DRAFT))

    transport = GeminiVideoTransport(
        replace(CONFIG, max_retries=99), httpx.MockTransport(handler),
    )
    result = await transport.generate("check", {})
    assert len(calls) == 3
    assert result.retries == 2


async def test_network_exception_does_not_expose_http_exception_or_key():
    def handler(request):
        raise httpx.ConnectError(f"private {CONFIG.api_key}", request=request)

    transport = GeminiVideoTransport(CONFIG, httpx.MockTransport(handler))
    with pytest.raises(VideoProviderError) as error:
        await transport.generate("check", {})
    assert CONFIG.api_key not in str(error.value)
    assert error.value.__cause__ is None


async def test_total_deadline_is_enforced():
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=envelope(DRAFT))

    transport = GeminiVideoTransport(
        replace(CONFIG, timeout_ms=100), httpx.MockTransport(handler),
    )
    with pytest.raises(VideoProviderError, match="bounded request deadline"):
        await transport.generate("check", {})


async def test_invalid_compiler_output_is_safe_not_a_fallback(clock, id_factory):
    async def loader(*args):
        pytest.fail("prompt-only compilation should not load media")

    compiler = GeminiVideoCompiler(
        CONFIG, clock, id_factory, loader,
        httpx.MockTransport(lambda _: httpx.Response(
            200, json=envelope({"title": CONFIG.api_key}),
        )),
    )
    result = await compiler.compile("Find motion", {"workspace_id": "workspace-a"})
    assert result.outcome.kind == "unsupported_request"
    assert CONFIG.api_key not in result.outcome.reason
    assert result.outcome.code == "invalid_response"


async def test_rejects_invalid_model_before_any_network():
    with pytest.raises(VideoProviderError):
        GeminiVideoTransport(replace(CONFIG, model="gemini-x/../../other?key=oops"))


@pytest.mark.parametrize("data", [b"not an mp4", b"\0\0\0\x18ftyp" + b"0" * MAX_INLINE_BYTES])
async def test_bad_seed_fails_without_provider_call(data, clock, id_factory):
    async def loader(*args):
        return data

    result = await GeminiVideoCompiler(
        CONFIG, clock, id_factory, loader,
        httpx.MockTransport(lambda _: pytest.fail("must reject seed before HTTP")),
    ).compile("Motion", {"source_id": "seed", "workspace_id": "workspace-a"})
    assert result.outcome.kind == "unsupported_request"


class FakeDecoder:
    def __init__(self, duration=60000):
        self.duration = duration
        self.clips = []

    def probe(self, source):
        return SimpleNamespace(duration_ms=self.duration, byte_size=100, sha256="a" * 64)

    def extract_clip(self, source, start, end):
        data = b"\0\0\0\x18ftypmp42" + str(start).encode()
        self.clips.append((start, end, data))
        return ClipResult(data, start, end, start, end, False, False, "reencode")


async def test_negative_windows_complete_without_fabricated_events(id_factory):
    decoder, sink = FakeDecoder(), Sink()
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=envelope(assessment()))

    engine = GeminiSemanticEngine(
        CONFIG, decoder, None, sink, id_factory, httpx.MockTransport(handler),
    )
    result = await engine.run(context(), 7)
    assert result.phase == "completed"
    assert not result.events and not sink.events
    assert result.progress.processed_samples == result.progress.requested_samples == 2
    assert [(r.start_ms.root, r.end_ms.root) for r in result.progress.processed_ranges] == [
        (0, 30000), (30000, 60000),
    ]
    for request, clip in zip(requests, decoder.clips, strict=True):
        parts = request["contents"][0]["parts"]
        assert base64.b64decode(parts[0]["inlineData"]["data"]) == clip[2]
        assert parts[0]["videoMetadata"]["fps"] == 2
        assert DRAFT["conditions"][0] in parts[1]["text"]
        assert f"Source offset: {clip[0]}ms" in parts[1]["text"]
    assert [p.phase for p in sink.updates] == ["running", "running", "running", "completed"]


@pytest.mark.parametrize("bad", [
    {}, {"conditions": []}, assessment(condition_id="unknown"),
    assessment("present", start=100, end=31000), assessment("present", start=500, end=100),
    {"conditions": [{**assessment()["conditions"][0], "decision": "uncertain"}]},
    {"conditions": [assessment()["conditions"][0]] * 2},
])
async def test_invalid_assessment_fails_not_zero_success(bad, id_factory):
    sink = Sink()
    engine = GeminiSemanticEngine(
        CONFIG, FakeDecoder(), None, sink, id_factory,
        httpx.MockTransport(lambda _: httpx.Response(200, json=envelope(bad))),
    )
    with pytest.raises(EngineRuntimeError, match="Semantic video analysis failed"):
        await engine.run(context(), 7)
    assert sink.updates[-1].phase == "failed"
    assert sink.updates[-1].processed_ranges == []
    assert not sink.events


@pytest.mark.parametrize("decision", ["present", "uncertain"])
async def test_real_video_evidence_and_source_timestamps(decision, tmp_path, clock, id_factory):
    data = OTHER_VIDEO.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    store = FileSystemMediaStore(data_dir=tmp_path, max_bytes=250000000, clock=clock)
    grant = await store.begin_upload("owner-a", "video/mp4", len(data), declared_sha256=sha)
    await store.receive_upload(grant.grant_id, data)
    meta = await store.finalize_upload(grant.grant_id, actual_size=len(data), actual_sha256=sha)
    decoder, sink = LocalVideoDecoder(), Sink()
    expected_clip = decoder.extract_clip(OTHER_VIDEO, 2000, 4000).data
    requests = []

    def handler(request):
        parts = json.loads(request.content)["contents"][0]["parts"]
        video = base64.b64decode(parts[0]["inlineData"]["data"])
        requests.append(video)
        # First window absent, second independently classified, remaining windows absent.
        content = assessment(decision) if len(requests) == 2 else assessment()
        return httpx.Response(200, json=envelope(content))

    engine = GeminiSemanticEngine(
        CONFIG, decoder, EvidenceExtractor(decoder, store), sink, id_factory,
        httpx.MockTransport(handler),
    )
    result = await engine.run(context(
        spec=spec(window_ms=2000, stride_ms=2000),
        storage_ref=meta.resource_id.root, source_generation=meta.generation, source_sha256=sha,
    ), 7)
    assert result.phase == "completed"
    assert requests[1] == expected_clip
    assert requests[1] != VIDEO.read_bytes()  # never reused the build's seed
    assert len(result.events) == 1
    event = next(iter(result.events.values()))
    assert event.source_range.start_ms.root == 2100
    assert event.source_range.end_ms.root == 2500
    assert event.facts["source_time_ms"] == 2100
    assert event.facts["description"] and event.facts["reason"]
    assert event.facts["provider"] == "gemini" and event.facts["adapter_mode"] == "video"
    assert event.spec_version_id.root == "saved-version"
    assert event.track_refs == []
    assert event.machine_decision == ("inconclusive" if decision == "uncertain" else "candidate")
    assert event.evidence.state == "available"
    for ref, mime in [(event.evidence.thumbnail_ref, "image/jpeg"),
                      (event.evidence.clip_ref, "video/mp4")]:
        assert ref is not None
        metadata = await store.get_metadata(ref.root)
        assert metadata.content_type == mime and metadata.size > 0
        read_grant = await store.issue_read_grant("owner-a", ref.root)
        artifact = await store.read_artifact(ref.root, read_grant.grant_id)
        if mime == "image/jpeg":
            assert artifact.startswith(b"\xff\xd8")
        else:
            assert artifact[4:8] == b"ftyp"


async def test_cancellation_has_no_provider_calls_or_false_coverage(id_factory):
    sink = Sink()
    engine = GeminiSemanticEngine(
        CONFIG, FakeDecoder(), None, sink, id_factory,
        httpx.MockTransport(lambda _: pytest.fail("cancelled request must not reach provider")),
    )
    result = await engine.run(context(), 7, lambda: True)
    assert result.phase == "cancelled"
    assert result.progress.processed_ranges == []


async def test_duration_and_retry_call_limits_fail_honestly(id_factory):
    sink = Sink()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text=CONFIG.api_key)

    engine = GeminiSemanticEngine(
        replace(CONFIG, max_retries=2), FakeDecoder(), None, sink, id_factory,
        httpx.MockTransport(handler),
    )
    with pytest.raises(EngineRuntimeError):
        limited = spec(limits={"max_duration_ms": 60000, "max_model_calls": 2})
        await engine.run(context(spec=limited), 7)
    assert len(calls) == 2
    assert sink.updates[-1].phase == "failed"
    assert CONFIG.api_key not in repr(sink.updates)
    engine = GeminiSemanticEngine(
        CONFIG, FakeDecoder(duration=60001), None, Sink(), id_factory,
        httpx.MockTransport(lambda _: pytest.fail("overlong source must not reach provider")),
    )
    with pytest.raises(EngineRuntimeError):
        await engine.run(context(), 7)
