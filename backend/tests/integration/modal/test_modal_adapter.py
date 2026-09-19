from __future__ import annotations

import asyncio

import pytest

from vision_app.adapters.modal.executor import ModalExecutor
from vision_app.adapters.modal.fake import FakeModalClient
from vision_app.adapters.modal.models import ModalRunInput
from vision_app.contracts.models import (
    EvidencePolicy,
    ResourceId,
    TrackedRule,
    TrackedRulesSpec,
)
from vision_app.jobs.sinks import InMemoryEventSink
from vision_app.runtime.context import RunContext


def context() -> RunContext:
    return RunContext(
        run_id=ResourceId("run-1"),
        attempt_id=ResourceId("attempt-1"),
        workspace_id=ResourceId("workspace-1"),
        owner_id="owner-1",
        source_id=ResourceId("source-1"),
        source_path="/private/local/source.mp4",
        storage_ref="media/source-1/generation/7",
        source_generation=7,
        source_sha256="a" * 64,
        spec_version_id=ResourceId("version-1"),
        spec=TrackedRulesSpec(
            kind="tracked_rules",
            title="Counter",
            objective="Count crossings",
            rules=[
                TrackedRule(
                    rule_id=ResourceId("rule-1"),
                    capability_id="tracked.line_crossing",
                    object_classes=["car"],
                )
            ],
        ),
        evidence_policy=EvidencePolicy(before_ms=100, after_ms=200),
    )


def test_run_input_is_json_serializable_and_excludes_local_paths_and_secrets() -> None:
    payload = ModalRunInput.from_context(context(), fence=9)
    encoded = payload.model_dump_json()

    assert payload.fence == 9
    assert payload.storage_ref == "media/source-1/generation/7"
    assert payload.source_generation == 7
    assert payload.spec["kind"] == "tracked_rules"
    assert "/private/local" not in encoded
    assert "token" not in encoded.lower()


@pytest.mark.asyncio
async def test_fake_executes_minimal_run_and_streams_progress_to_sink() -> None:
    sink = InMemoryEventSink()
    client = FakeModalClient(step_delay=0)
    executor = ModalExecutor(client, lambda run_id: context(), sink, fence=4)

    invocation = await executor.submit("run-1")
    await executor.wait(invocation)

    assert [item.phase for item in sink.progress_updates] == ["preparing", "running", "completed"]
    assert all(item.run_id == ResourceId("run-1") for item in sink.progress_updates)
    assert (await executor.query(invocation)).state == "completed"
    assert client.submitted_inputs[0].attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_cancellation_propagates_to_remote_and_terminal_progress() -> None:
    sink = InMemoryEventSink()
    client = FakeModalClient(step_delay=0.05)
    executor = ModalExecutor(client, lambda run_id: context(), sink, fence=5)

    invocation = await executor.submit("run-1")
    await asyncio.sleep(0)
    await executor.cancel(invocation)
    await executor.wait(invocation)

    assert client.was_cancelled(invocation)
    assert sink.progress_updates[-1].phase == "cancelled"
    assert sink.progress_updates[-1].cancel_requested is True


@pytest.mark.asyncio
async def test_duplicate_submit_is_idempotent() -> None:
    sink = InMemoryEventSink()
    client = FakeModalClient(step_delay=0)
    executor = ModalExecutor(client, lambda run_id: context(), sink, fence=1)

    first = await executor.submit("run-1")
    second = await executor.submit("run-1")
    await executor.wait(first)

    assert first == second
    assert len(client.submitted_inputs) == 1
