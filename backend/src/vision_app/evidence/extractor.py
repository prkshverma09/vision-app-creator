"""Evidence manifest, thumbnail, and clip extraction (DESIGN.md section 9.3).

Default evidence request is three seconds before/after an event, clipped to
source boundaries. The manifest records requested/actual ranges, truncation
flags, and availability state. Artifacts are stored privately through the
MediaStore port and are named by attempt/source generation. Tombstones and
generations are rechecked before artifacts are registered; a stale extraction
cleans its own orphan artifacts rather than recreating visible media.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

import cv2
import numpy as np

from vision_app.contracts.models import (
    DecodedFrame,
    Event,
    EvidenceManifest,
    EvidencePolicy,
    ResourceId,
    StoredMetadata,
    TimeRange,
)
from vision_app.contracts.ports import EventSink, MediaStore
from vision_app.evidence.errors import EvidenceRangeError, EvidenceError, StaleSourceError
from vision_app.media.errors import MediaError
from vision_app.media.types import ClipResult, MediaProbe


ManifestState = Literal["pending", "available", "degraded", "failed"]


class EvidenceDecoder(Protocol):
    """Decoder surface required for evidence extraction."""

    def probe(self, source: str | os.PathLike[str]) -> MediaProbe: ...

    def sample(self, source: str | os.PathLike[str], times_ms: list[int]) -> list[DecodedFrame]: ...

    def extract_clip(
        self, source: str | os.PathLike[str], start_ms: int, end_ms: int
    ) -> ClipResult: ...


@dataclass(frozen=True)
class EvidenceRequest:
    """One bounded evidence extraction job for a single event/source."""

    owner_id: str
    source_id: ResourceId
    storage_ref: str  # MediaStore resource ID of the staged source object
    source_generation: int  # expected source generation; rechecked before registering
    source_sha256: str | None  # optional integrity pin checked against the probe
    source_path: str | os.PathLike[str]  # staged local file for the decoder
    event_range: TimeRange  # event's source interval in ms
    attempt_id: str  # run attempt; scopes artifact names
    policy: EvidencePolicy = field(default_factory=EvidencePolicy)


@dataclass(frozen=True)
class EvidenceArtifact:
    """A privately stored evidence artifact."""

    kind: Literal["thumbnail", "clip"]
    name: str  # attempt/source-generation scoped logical name
    resource_id: str  # opaque MediaStore resource ID (never a URL)


@dataclass(frozen=True)
class EvidenceResult:
    """Extraction output: a manifest plus its private artifact bindings."""

    manifest: EvidenceManifest
    artifacts: tuple[EvidenceArtifact, ...]
    fallback: Literal["none", "source_playback"]
    duration_ms: int


def select_thumbnail_times(start_ms: int, end_ms: int, event_time_ms: int) -> list[int]:
    """Pick representative sample times: event moment first, then range edges.

    All returned times lie in the half-open range ``[start_ms, end_ms)`` and
    are deduplicated while preserving priority order.
    """
    candidates = [
        min(max(event_time_ms, start_ms), end_ms - 1),
        start_ms,
        end_ms - 1,
    ]
    times: list[int] = []
    for candidate in candidates:
        if candidate not in times:
            times.append(candidate)
    return times


def _encode_jpeg(frame: DecodedFrame) -> bytes:
    width = frame.frame_ref.width
    height = frame.frame_ref.height
    rgb = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(height, width, 3)
    ok, encoded = cv2.imencode(
        ".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80]
    )
    if not ok:
        raise EvidenceError("thumbnail encoding failed")
    return encoded.tobytes()


class EvidenceExtractor:
    """Generates honest, privately stored evidence artifacts for events."""

    def __init__(self, decoder: EvidenceDecoder, store: MediaStore) -> None:
        self._decoder = decoder
        self._store = store

    async def _assert_source_fresh(self, request: EvidenceRequest) -> StoredMetadata:
        try:
            meta = cast(StoredMetadata, await self._store.get_metadata(request.storage_ref))
        except Exception as exc:
            raise StaleSourceError(
                f"source {request.storage_ref} is unavailable or deleted"
            ) from exc
        if meta.state != "ready":
            raise StaleSourceError(f"source {request.storage_ref} is not ready")
        if meta.generation != request.source_generation:
            raise StaleSourceError(
                f"source generation {meta.generation} does not match expected "
                f"{request.source_generation}"
            )
        return meta

    def _artifact_name(self, request: EvidenceRequest, kind: str) -> str:
        return (
            f"evidence/{request.attempt_id}/g{request.source_generation}"
            f"/{request.source_id.root}/{kind}"
        )

    async def build(self, request: EvidenceRequest) -> EvidenceResult:
        """Extract thumbnail/clip and produce a requested-vs-actual manifest."""
        # Fence 1: the source must exist at the expected generation before work.
        await self._assert_source_fresh(request)

        probe = self._decoder.probe(request.source_path)
        if request.source_sha256 is not None and probe.sha256 != request.source_sha256:
            raise StaleSourceError("staged source bytes do not match the declared hash")
        duration_ms = probe.duration_ms

        policy = request.policy
        requested_start = request.event_range.start_ms.root - policy.before_ms
        requested_end = request.event_range.end_ms.root + policy.after_ms
        clipped_start = requested_start < 0
        clipped_end = requested_end > duration_ms
        actual_start = max(0, requested_start)
        actual_end = min(duration_ms, requested_end)
        if actual_start >= actual_end:
            raise EvidenceRangeError(
                "requested evidence window lies outside the source media"
            )
        requested_range = TimeRange.model_validate(
            {"start_ms": actual_start, "end_ms": actual_end}
        )

        artifacts: list[EvidenceArtifact] = []
        try:
            thumbnail_ref = await self._extract_thumbnail(
                request, actual_start, actual_end, artifacts
            )
            clip_ref, actual_range, state, fallback = await self._extract_clip(
                request, actual_start, actual_end, requested_range, artifacts
            )
            if thumbnail_ref is None and state == "available":
                state = "degraded"
        except Exception:
            # Never leave registered artifacts behind on failure.
            await self._cleanup(artifacts)
            raise

        # Fence 2: recheck tombstone/generation before registering artifacts.
        try:
            await self._assert_source_fresh(request)
        except StaleSourceError:
            await self._cleanup(artifacts)
            raise

        manifest = EvidenceManifest(
            requested_range=requested_range,
            actual_range=actual_range,
            thumbnail_ref=thumbnail_ref,
            clip_ref=clip_ref,
            clipped_start=clipped_start,
            clipped_end=clipped_end,
            state=state,
        )
        return EvidenceResult(
            manifest=manifest,
            artifacts=tuple(artifacts),
            fallback=fallback,
            duration_ms=duration_ms,
        )

    async def publish(
        self, event: Event, result: EvidenceResult, sink: EventSink, fence: int
    ) -> Event:
        """Attach the manifest to the event and upsert it through the sink."""
        updated = event.model_copy(update={"evidence": result.manifest})
        await sink.upsert(updated, fence)
        return updated

    async def _extract_thumbnail(
        self,
        request: EvidenceRequest,
        actual_start: int,
        actual_end: int,
        artifacts: list[EvidenceArtifact],
    ) -> ResourceId | None:
        event_mid = (
            request.event_range.start_ms.root + request.event_range.end_ms.root
        ) // 2
        times = select_thumbnail_times(actual_start, actual_end, event_mid)
        try:
            frames = self._decoder.sample(request.source_path, times)
        except MediaError:
            return None
        if not frames:
            return None
        data = _encode_jpeg(frames[0])  # the event-time sample is first
        resource_id = await self._store.put_artifact(
            request.owner_id, data, "image/jpeg"
        )
        artifacts.append(
            EvidenceArtifact("thumbnail", self._artifact_name(request, "thumbnail"), resource_id)
        )
        return ResourceId(resource_id)

    async def _extract_clip(
        self,
        request: EvidenceRequest,
        actual_start: int,
        actual_end: int,
        requested_range: TimeRange,
        artifacts: list[EvidenceArtifact],
    ) -> tuple[ResourceId | None, TimeRange, ManifestState, Literal["none", "source_playback"]]:
        try:
            clip = self._decoder.extract_clip(request.source_path, actual_start, actual_end)
        except MediaError:
            # Degraded fallback: link the raw source range instead of pretending
            # an extracted clip exists.
            return None, requested_range, "degraded", "source_playback"
        resource_id = await self._store.put_artifact(
            request.owner_id, clip.data, "video/mp4"
        )
        artifacts.append(
            EvidenceArtifact("clip", self._artifact_name(request, "clip"), resource_id)
        )
        actual_range = TimeRange.model_validate(
            {"start_ms": clip.actual_start_ms, "end_ms": clip.actual_end_ms}
        )
        return ResourceId(resource_id), actual_range, "available", "none"

    async def _cleanup(self, artifacts: list[EvidenceArtifact]) -> None:
        for artifact in artifacts:
            try:
                await self._store.delete_artifact(artifact.resource_id)
            except Exception:
                pass  # best effort; orphans are reclaimed by later cleanup
        artifacts.clear()
