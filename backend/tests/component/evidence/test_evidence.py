"""CT-EVIDENCE: clipping, truncation, linkage, fallback, grants, stale generations."""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from vision_app.contracts.models import (
    Event,
    EvidenceManifest,
    EvidencePolicy,
    ResourceId,
    TimeRange,
)
from vision_app.evidence.errors import EvidenceRangeError, StaleSourceError
from vision_app.evidence.extractor import (
    EvidenceExtractor,
    EvidenceRequest,
    select_thumbnail_times,
)
from vision_app.jobs.sinks import InMemoryEventSink
from vision_app.media.decoder import LocalVideoDecoder
from vision_app.media.errors import DecodeError
from vision_app.media.types import ClipResult
from vision_app.storage.errors import StorageError
from vision_app.storage.local import FileSystemMediaStore


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
pytestmark = [
    pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg is required for CT-EVIDENCE"),
    pytest.mark.asyncio,
]

VIDEO = Path(__file__).parents[4] / "fixtures/synthetic/video/moving_dot.mp4"  # 5 s h264
DURATION_MS = 5000
OWNER = "owner-1"


@pytest.fixture
def store(tmp_path: Path, clock: Any) -> FileSystemMediaStore:
    return FileSystemMediaStore(data_dir=tmp_path, max_bytes=250_000_000, clock=clock)


async def stage_source(store: FileSystemMediaStore, path: Path = VIDEO) -> tuple[str, str, int]:
    """Upload the fixture video; return (storage_ref, sha256, generation)."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    grant = await store.begin_upload(
        OWNER, "video/mp4", len(data), declared_sha256=sha, idempotency_key="src-1"
    )
    await store.receive_upload(grant.grant_id, data)
    meta = await store.finalize_upload(grant.grant_id, actual_size=len(data), actual_sha256=sha)
    return meta.resource_id.root, sha, meta.generation


def request(
    storage_ref: str,
    sha: str,
    generation: int,
    event_start: int,
    event_end: int,
    *,
    before_ms: int = 3000,
    after_ms: int = 3000,
    attempt_id: str = "attempt-1",
    source_path: Path = VIDEO,
) -> EvidenceRequest:
    return EvidenceRequest(
        owner_id=OWNER,
        source_id=ResourceId("source-1"),
        storage_ref=storage_ref,
        source_generation=generation,
        source_sha256=sha,
        source_path=source_path,
        event_range=TimeRange.model_validate({"start_ms": event_start, "end_ms": event_end}),
        attempt_id=attempt_id,
        policy=EvidencePolicy(before_ms=before_ms, after_ms=after_ms),
    )


def object_ids(store: FileSystemMediaStore) -> set[str]:
    return {p.name for p in (store._data_dir / "objects").iterdir()}  # noqa: SLF001


class TombstoningStore:
    """Store proxy: the source tombstone lands between extraction and registration."""

    def __init__(self, inner: FileSystemMediaStore, storage_ref: str) -> None:
        self._inner = inner
        self._ref = storage_ref
        self._checks = 0

    async def get_metadata(self, resource_id: str) -> Any:
        if str(resource_id) == self._ref:
            self._checks += 1
            if self._checks >= 2:
                raise StorageError("already_deleted", "source was deleted mid-extraction")
        return await self._inner.get_metadata(resource_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class FailingDecoder(LocalVideoDecoder):
    """Clip extraction always fails; probe/sample still work."""

    def extract_clip(self, source: str | os.PathLike[str], start_ms: int, end_ms: int) -> ClipResult:
        raise DecodeError("simulated clip extraction failure")


async def test_manifest_records_requested_vs_actual_ranges(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)

    result = await extractor.build(request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500))

    manifest = result.manifest
    assert manifest.state == "available"
    assert (manifest.requested_range.start_ms.root, manifest.requested_range.end_ms.root) == (1500, 3000)
    assert manifest.actual_range is not None
    assert (manifest.actual_range.start_ms.root, manifest.actual_range.end_ms.root) == (1500, 3000)
    assert manifest.clipped_start is False
    assert manifest.clipped_end is False
    assert manifest.clip_ref is not None
    assert manifest.thumbnail_ref is not None
    assert result.fallback == "none"
    kinds = {artifact.kind for artifact in result.artifacts}
    assert kinds == {"thumbnail", "clip"}
    # Artifact names are attempt/source-generation scoped.
    for artifact in result.artifacts:
        assert "attempt-1" in artifact.name
        assert f"g{gen}" in artifact.name
        assert "source-1" in artifact.name
    # Stored artifacts are readable through the store via scoped grants.
    clip_id = manifest.clip_ref.root
    grant = await store.issue_read_grant(OWNER, clip_id)
    assert (await store.read_artifact(clip_id, grant.grant_id)).startswith(b"\x00\x00\x00")


async def test_event_at_source_start_is_truncated(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)

    result = await extractor.build(request(ref, sha, gen, 0, 400))

    manifest = result.manifest
    assert manifest.clipped_start is True
    assert manifest.clipped_end is False
    assert manifest.requested_range.start_ms.root == 0
    assert manifest.requested_range.end_ms.root == 3400
    assert manifest.actual_range is not None
    assert manifest.actual_range.start_ms.root == 0
    # No nonexistent pre-event footage is claimed.
    assert manifest.actual_range.start_ms.root >= 0


async def test_event_at_source_end_is_truncated(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)

    result = await extractor.build(request(ref, sha, gen, 4600, 4900))

    manifest = result.manifest
    assert manifest.clipped_start is False
    assert manifest.clipped_end is True
    assert manifest.requested_range.end_ms.root == DURATION_MS
    assert manifest.actual_range is not None
    assert manifest.actual_range.end_ms.root <= DURATION_MS


async def test_event_range_outside_media_is_rejected(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)

    with pytest.raises(EvidenceRangeError):
        await extractor.build(request(ref, sha, gen, 9000, 9500))


async def test_stale_source_generation_is_rejected(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)
    before = object_ids(store)

    with pytest.raises(StaleSourceError):
        await extractor.build(request(ref, sha, gen + 5, 2000, 2500))

    assert object_ids(store) == before  # no evidence artifacts registered


async def test_deleted_source_is_rejected(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    await store.delete_artifact(ref)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)

    with pytest.raises(StaleSourceError):
        await extractor.build(request(ref, sha, gen, 2000, 2500))


async def test_source_deleted_mid_extraction_cleans_orphans(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), TombstoningStore(store, ref))

    with pytest.raises(StaleSourceError):
        await extractor.build(request(ref, sha, gen, 2000, 2500))

    # The thumbnail written before the tombstone landed must not remain visible.
    assert object_ids(store) == {ref}


async def test_clip_extraction_failure_falls_back_to_source_playback(
    store: FileSystemMediaStore,
) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(FailingDecoder(), store)

    result = await extractor.build(request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500))

    manifest = result.manifest
    assert result.fallback == "source_playback"
    assert manifest.state == "degraded"
    assert manifest.clip_ref is None
    assert manifest.actual_range is not None  # honest degraded link to the raw source range
    assert (manifest.actual_range.start_ms.root, manifest.actual_range.end_ms.root) == (1500, 3000)


async def test_select_thumbnail_times_prefers_event_then_edges() -> None:
    times = select_thumbnail_times(1000, 4000, event_time_ms=2500)
    assert times[0] == 2500
    assert all(1000 <= t < 4000 for t in times)
    assert len(times) == len(set(times)) <= 3


async def test_select_thumbnail_times_dedupes_at_edges() -> None:
    times = select_thumbnail_times(0, 100, event_time_ms=0)
    assert times[0] == 0
    assert len(times) == len(set(times))


async def test_source_hash_mismatch_is_rejected(store: FileSystemMediaStore) -> None:
    ref, _sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)
    bad = "0" * 64

    with pytest.raises(StaleSourceError):
        await extractor.build(request(ref, bad, gen, 2000, 2500))


async def test_expired_read_grant_cannot_read_evidence(
    store: FileSystemMediaStore, clock: Any
) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)
    result = await extractor.build(request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500))
    assert result.manifest.clip_ref is not None

    grant = await store.issue_read_grant(OWNER, result.manifest.clip_ref.root, ttl_seconds=1)
    clock.value += timedelta(seconds=2)
    with pytest.raises(StorageError) as exc:
        await store.read_artifact(result.manifest.clip_ref.root, grant.grant_id)
    assert exc.value.code == "grant_expired"


async def test_no_public_urls_and_no_cross_source_linkage(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)
    result = await extractor.build(request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500))

    payload = result.manifest.model_dump_json()
    assert "http" not in payload  # no public object URLs
    own_ids = {artifact.resource_id for artifact in result.artifacts}
    for ref_field in (result.manifest.clip_ref, result.manifest.thumbnail_ref):
        assert ref_field is not None
        assert ref_field.root in own_ids  # linkage only to this request's artifacts

    other = await extractor.build(
        request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500, attempt_id="attempt-2")
    )
    assert other.manifest.clip_ref is not None
    assert other.manifest.clip_ref.root != result.manifest.clip_ref.root


async def test_publish_attaches_manifest_through_event_sink(store: FileSystemMediaStore) -> None:
    ref, sha, gen = await stage_source(store)
    extractor = EvidenceExtractor(LocalVideoDecoder(), store)
    result = await extractor.build(request(ref, sha, gen, 2000, 2500, before_ms=500, after_ms=500))
    sink = InMemoryEventSink()

    pending = EvidenceManifest(
        requested_range=result.manifest.requested_range, actual_range=None, state="pending"
    )
    event = Event(
        id=ResourceId("event-1"), run_id=ResourceId("run-1"), attempt_id=ResourceId("attempt-1"),
        spec_version_id=ResourceId("version-1"), calibration_id=None,
        source_range=result.manifest.requested_range, rule_id=ResourceId("rule-1"),
        track_refs=[], facts={}, evidence=pending, machine_decision="candidate",
        human_review="unreviewed", revision=0,
    )
    updated = await extractor.publish(event, result, sink, fence=3)
    assert updated.evidence.clip_ref == result.manifest.clip_ref
    assert sink.events["event-1"].evidence.state == "available"

    # A stale fence must not overwrite the stored event.
    await sink.upsert(event, fence=2)
    assert sink.events["event-1"].evidence.state == "available"
