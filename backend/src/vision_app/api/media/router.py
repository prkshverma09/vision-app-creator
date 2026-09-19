"""FastAPI router factory for media upload, metadata, read, sample, and deletion routes."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import tempfile
from dataclasses import dataclass
from typing import cast
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from vision_app.contracts.models import (
    DecodedFrame,
    FrameRef,
    ResourceId,
    SourceAsset,
    SourceTimeMs,
    UploadGrant,
    UtcTimestamp,
)
from vision_app.contracts.ports import IdentityVerifier, MediaStore
from vision_app.media.errors import DecodeError, DecodeTimeoutError, DecoderUnavailableError, MediaError
from vision_app.media.types import MediaProbe
from vision_app.privacy.service import CleanupGraph, DeletionService, PrivacyError
from vision_app.security.authorization.boundary import AuthorizationBoundary
from vision_app.security.identity.errors import IdentityError, PublicSecurityError
from vision_app.security.identity.models import Principal
from vision_app.storage.errors import StorageError


class _Clock(Protocol):
    def now(self) -> Any: ...


class _Decoder(Protocol):
    def probe(self, resource_id: str) -> Any: ...
    def scene_samples(self, resource_id: str, *, count: int) -> Any: ...


class MediaRepository(Protocol):
    async def save_asset(self, asset: SourceAsset) -> None: ...
    async def get_asset(self, asset_id: str, workspace_id: str) -> SourceAsset | None: ...


@dataclass(frozen=True)
class MediaDependencies:
    identity: IdentityVerifier
    authorization: AuthorizationBoundary
    store: MediaStore
    decoder: _Decoder
    repository: MediaRepository
    privacy: DeletionService
    clock: _Clock
    request_id: Callable[[], str]


class _InitiateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_size: int = Field(gt=0)
    content_type: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class _FinalizeUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual_size: int = Field(gt=0)
    actual_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MediaService:
    """Lifecycle operations for uploaded source assets."""

    def __init__(
        self,
        deps: MediaDependencies,
        retention: timedelta | None = None,
    ) -> None:
        self._deps = deps
        self._retention = retention or timedelta(hours=24)
        self._previews = tempfile.TemporaryDirectory(prefix="vision-previews-")
        self._preview_lock = asyncio.Lock()

    async def initiate_upload(
        self,
        principal: Principal,
        workspace: str,
        content_type: str,
        file_size: int,
        sha256: str | None,
    ) -> UploadGrant:
        _require_workspace(principal, workspace)
        grant = await self._deps.store.begin_upload(
            principal.user_id,
            content_type,
            file_size,
            declared_sha256=sha256,
        )
        return cast(UploadGrant, grant)

    async def finalize_upload(
        self,
        principal: Principal,
        workspace: str,
        grant_id: str,
        actual_size: int,
        actual_sha256: str,
    ) -> SourceAsset:
        _require_workspace(principal, workspace)
        meta = await self._deps.store.finalize_upload(
            grant_id,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
        )
        staged = await self._stage_bytes(principal.user_id, meta.resource_id.root)
        try:
            probe_result = await _maybe_await(
                self._deps.decoder.probe(str(staged))
            )
        finally:
            staged.unlink(missing_ok=True)

        if not isinstance(probe_result, MediaProbe):
            raise TypeError("decoder probe must return a MediaProbe")
        asset = SourceAsset(
            id=ResourceId(meta.resource_id.root),
            workspace_id=ResourceId(workspace),
            byte_size=meta.size,
            codec=probe_result.codec,
            width=probe_result.display_width,
            height=probe_result.display_height,
            duration_ms=SourceTimeMs(probe_result.duration_ms),
            storage_ref=ResourceId(meta.resource_id.root),
            sha256=meta.sha256,
            state="ready",
            generation=meta.generation,
            retention_until=UtcTimestamp(self._deps.clock.now() + self._retention),
            deleted_at=None,
        )
        await self._deps.repository.save_asset(asset)
        return asset

    async def get_asset(self, principal: Principal, workspace: str, asset_id: str) -> SourceAsset:
        _require_workspace(principal, workspace)
        await self._deps.authorization.asset(principal, asset_id)
        asset = await self._deps.repository.get_asset(asset_id, workspace)
        if asset is None:
            raise _not_found()
        return asset

    async def read_media(self, principal: Principal, workspace: str, asset_id: str) -> Response:
        _require_workspace(principal, workspace)
        await self._deps.authorization.asset(principal, asset_id)
        asset = await self._deps.repository.get_asset(asset_id, workspace)
        if asset is None or asset.state in {"deleting", "deleted"}:
            raise _not_found()
        media_type = _CONTENT_TYPE.get(asset.codec, "application/octet-stream")
        # Serve directly from disk when possible so browsers get byte-range support.
        local_path = self._deps.store.local_path(asset.storage_ref.root)
        if local_path is not None and local_path.exists():
            # Still issue a grant to keep authorization accounting consistent.
            await self._deps.store.issue_read_grant(
                principal.user_id,
                asset.storage_ref.root,
                ttl_seconds=3600,
            )
            return FileResponse(
                str(local_path),
                media_type=media_type,
                filename=None,
            )
        grant = await self._deps.store.issue_read_grant(
            principal.user_id,
            asset.storage_ref.root,
            ttl_seconds=3600,
        )
        data = await self._deps.store.read(grant.grant_id)
        return Response(content=data, media_type=media_type)

    async def read_preview(self, principal: Principal, workspace: str, asset_id: str) -> Response:
        asset = await self.get_asset(principal, workspace, asset_id)
        if asset.state != "ready":
            raise _not_found()
        await self._deps.store.issue_read_grant(principal.user_id, asset.storage_ref.root)
        key = hashlib.sha256(f"{workspace}:{asset_id}:{asset.sha256}:{asset.generation}".encode()).hexdigest()
        target = Path(self._previews.name) / f"{key}.webm"
        async with self._preview_lock:
            if not target.exists():
                staged = await self._stage_bytes(principal.user_id, asset.storage_ref.root)
                partial = target.with_suffix(".partial.webm")
                try:
                    try:
                        process = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                            "-protocol_whitelist", "file,pipe", "-i", str(staged),
                            "-map", "0:v:0", "-an", "-vf", "scale=w='min(1280,iw)':h=-2",
                            "-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8",
                            "-b:v", "1500k", "-pix_fmt", "yuv420p", "-threads", "2",
                            "-map_metadata", "-1", str(partial),
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        )
                    except FileNotFoundError as exc:
                        raise DecoderUnavailableError("FFmpeg is required for browser previews.") from exc
                    try:
                        await asyncio.wait_for(process.wait(), timeout=120)
                    except (TimeoutError, asyncio.CancelledError) as exc:
                        if process.returncode is None:
                            process.kill()
                        await process.wait()
                        if isinstance(exc, asyncio.CancelledError):
                            raise
                        raise DecodeTimeoutError("Browser preview conversion timed out.") from exc
                    if process.returncode != 0:
                        raise DecodeError("Could not convert the uploaded video to a WebM preview.")
                    partial.replace(target)
                finally:
                    staged.unlink(missing_ok=True)
                    partial.unlink(missing_ok=True)
        return FileResponse(target, media_type="video/webm", headers={"Cache-Control": "private, no-store"})

    async def samples(
        self,
        principal: Principal,
        workspace: str,
        asset_id: str,
        count: int,
    ) -> list[FrameRef]:
        _require_workspace(principal, workspace)
        await self._deps.authorization.asset(principal, asset_id)
        asset = await self._deps.repository.get_asset(asset_id, workspace)
        if asset is None or asset.state != "ready":
            raise _not_found()
        if count < 1 or count > 32:
            raise ValueError("sample count must be between 1 and 32")
        staged = await self._stage_bytes(principal.user_id, asset.storage_ref.root)
        try:
            decoded = await _maybe_await(
                self._deps.decoder.scene_samples(str(staged), count=count)
            )
        finally:
            staged.unlink(missing_ok=True)
        return [frame.frame_ref for frame in decoded if isinstance(frame, DecodedFrame)]

    async def delete(
        self, principal: Principal, workspace: str, asset_id: str
    ) -> dict[str, Any]:
        _require_workspace(principal, workspace)
        await self._deps.authorization.asset(principal, asset_id)
        asset = await self._deps.repository.get_asset(asset_id, workspace)
        if asset is None:
            raise _not_found()
        if asset.state in {"deleting", "deleted"}:
            raise PublicSecurityError(410, "resource_gone", "Asset has already been deleted.")

        graph = CleanupGraph(
            resources=(("asset", asset_id),),
            local_artifacts=((asset.storage_ref.root, asset.generation),),
        )
        job = await self._deps.privacy.tombstone(
            workspace, graph, requested_by=principal.user_id
        )
        job = await self._deps.privacy.hard_delete(job)
        return _deletion_job_body(job)

    async def _stage_bytes(self, owner_id: str, resource_id: str) -> Path:
        """Read an object from storage into a temporary local file for decoding."""
        grant = await self._deps.store.issue_read_grant(owner_id, resource_id, ttl_seconds=3600)
        data = await self._deps.store.read(grant.grant_id)
        suffix = ".mp4" if "mp4" in (await self._deps.store.get_metadata(resource_id)).content_type else ".bin"
        handle, path_str = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(handle, "wb") as target:
                target.write(data)
        except Exception:
            os.close(handle)
            raise
        return Path(path_str)


def create_media_router(deps: MediaDependencies) -> APIRouter:
    router = APIRouter(tags=["media"])
    service = MediaService(deps)

    async def _require_principal(authorization: str | None = Header(None)) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise IdentityError("missing_token")
        token = authorization[len("Bearer "):]
        try:
            principal = await deps.identity.verify(token)
        except IdentityError:
            raise
        except Exception as exc:  # pragma: no cover
            raise IdentityError(str(exc)) from exc
        if not isinstance(principal, Principal):
            raise IdentityError()
        return principal

    @router.post("/workspaces/{workspace}/uploads/initiate", status_code=201)
    async def initiate_upload(
        workspace: str,
        body: _InitiateUploadRequest,
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        grant = await service.initiate_upload(
            principal,
            workspace,
            body.content_type,
            body.file_size,
            body.sha256,
        )
        return grant.model_dump(mode="json")

    @router.post("/workspaces/{workspace}/uploads/{upload}/finalize", status_code=201)
    async def finalize_upload(
        workspace: str,
        upload: str,
        body: _FinalizeUploadRequest,
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        asset = await service.finalize_upload(
            principal,
            workspace,
            upload,
            body.actual_size,
            body.actual_sha256,
        )
        return asset.model_dump(mode="json")

    @router.get("/workspaces/{workspace}/assets/{asset}")
    async def get_asset(
        workspace: str,
        asset: str,
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        item = await service.get_asset(principal, workspace, asset)
        return item.model_dump(mode="json")

    @router.get("/workspaces/{workspace}/assets/{asset}/media")
    async def read_media(
        workspace: str,
        asset: str,
        principal: Principal = Depends(_require_principal),
    ) -> Response:
        return await service.read_media(principal, workspace, asset)

    @router.get("/workspaces/{workspace}/assets/{asset}/samples")
    async def samples(
        workspace: str,
        asset: str,
        principal: Principal = Depends(_require_principal),
        count: int = Query(default=5, ge=1, le=32),
    ) -> Any:
        refs = await service.samples(principal, workspace, asset, count)
        return [ref.model_dump(mode="json") for ref in refs]

    @router.delete("/workspaces/{workspace}/assets/{asset}", status_code=202)
    async def delete_asset(
        workspace: str,
        asset: str,
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        return await service.delete(principal, workspace, asset)

    return router


def add_media_exception_handlers(app: Any) -> None:
    async def _identity_handler(_request: Request, exc: IdentityError) -> JSONResponse:
        return _error_response(
            401, "invalid_identity", "Authentication is required.", "identity"
        )

    async def _security_handler(_request: Request, exc: PublicSecurityError) -> JSONResponse:
        return _error_response(
            exc.status_code,
            exc.code,
            exc.message,
            "security",
            retryable=exc.status_code == 429,
        )

    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors: dict[str, str] = {}
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", []))
            field_errors[loc] = error.get("msg", "invalid value")
        return _error_response(
            422,
            "invalid_request",
            "Request body failed validation.",
            "validation",
            field_errors=field_errors,
        )

    async def _storage_handler(_request: Request, exc: StorageError) -> JSONResponse:
        status, code = _storage_status_and_code(exc.code)
        return _error_response(status, code, str(exc) or exc.code, "storage")

    async def _media_handler(_request: Request, exc: MediaError) -> JSONResponse:
        status = 413 if isinstance(exc, type) and exc.code == "oversized_media" else 422
        # Note: some media errors can also be oversized; map explicitly by code below.
        status, code = _media_status_and_code(exc.code)
        return _error_response(status, code, str(exc) or exc.code, "media")

    async def _privacy_handler(_request: Request, exc: PrivacyError) -> JSONResponse:
        return _error_response(409, "deletion_conflict", str(exc) or "deletion failed", "privacy")

    async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(422, "invalid_request", str(exc), "value-error")

    app.add_exception_handler(IdentityError, _identity_handler)
    app.add_exception_handler(PublicSecurityError, _security_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StorageError, _storage_handler)
    app.add_exception_handler(MediaError, _media_handler)
    app.add_exception_handler(PrivacyError, _privacy_handler)
    app.add_exception_handler(ValueError, _value_error_handler)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    field_errors: dict[str, str] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        code=code,
        message=message,
        field_errors=field_errors or {},
        request_id=request_id,
        retryable=retryable,
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _storage_status_and_code(code: str) -> tuple[int, str]:
    if code == "size_exceeded":
        return 413, "oversized_media"
    if code in {"invalid_grant", "grant_scope_mismatch", "upload_already_used"}:
        return 400, code
    if code == "not_found":
        return 404, "resource_not_found"
    if code == "already_deleted":
        return 410, "resource_gone"
    if code in {"hash_mismatch", "size_mismatch"}:
        return 422, "invalid_media"
    if code == "grant_expired":
        return 410, "grant_expired"
    return 400, code


def _media_status_and_code(code: str) -> tuple[int, str]:
    if code == "oversized_media":
        return 413, "oversized_media"
    if code in {"invalid_media", "unsupported_media"}:
        return 422, code
    if code == "decoder_unavailable":
        return 503, "decoder_unavailable"
    if code == "decode_timeout":
        return 504, "decode_timeout"
    if code == "end_of_media":
        return 422, "end_of_media"
    return 422, "media_error"


def _deletion_job_body(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "state": job.state.value,
        "requested_by": job.requested_by,
        "requested_at": job.requested_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "errors": list(job.errors),
    }


def _require_workspace(principal: Principal, workspace: str) -> None:
    if not principal.is_member(workspace):
        raise _not_found()


def _not_found() -> PublicSecurityError:
    return PublicSecurityError(404, "resource_not_found", "Resource not found.")


_CONTENT_TYPE: dict[str, str] = {
    "h264": "video/mp4",
    "mpeg4": "video/mp4",
    "h265": "video/mp4",
    "vp9": "video/webm",
}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


# Import here to avoid circular import issues at module load time.
from vision_app.contracts.models import ErrorEnvelope  # noqa: E402
