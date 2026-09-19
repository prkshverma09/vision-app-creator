"""Application, immutable version, and source-calibration lifecycle services."""
from __future__ import annotations

from typing import Any, Protocol, cast

from vision_app.contracts.models import (
    AppSpec,
    AppVersion,
    BoxN,
    Calibration,
    FrameRef,
    PointN,
    ResourceId,
    TrackedRulesSpec,
    UtcTimestamp,
    VisionApp,
)
from vision_app.contracts.ports import Clock, IdFactory, Repository
from vision_app.validation.validator import ValidationOutcome

_APP = "vision_app"
_VERSION = "app_version"
_CALIBRATION = "calibration"


class ApplicationRepository(Repository, Protocol):
    async def list_owned(self, kind: str, principal: Any) -> list[Any]: ...
    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool: ...


class Validator(Protocol):
    def __call__(self, spec: AppSpec, *, calibration: Calibration | None = None,
                 approved_action_refs: frozenset[str] = frozenset(),
                 publication: bool = False) -> ValidationOutcome: ...


class ApplicationError(RuntimeError):
    pass


class AppNotFound(ApplicationError):
    pass


class AppConflict(ApplicationError):
    pass


class InvalidProposal(ApplicationError):
    def __init__(self, outcome: ValidationOutcome) -> None:
        self.outcome = outcome
        super().__init__("proposal validation failed")


class PublicationBlocked(ApplicationError):
    def __init__(self, outcome: ValidationOutcome) -> None:
        self.outcome = outcome
        super().__init__(f"version is not publication ready: {outcome.state}")


class VersionService:
    def __init__(self, repository: ApplicationRepository, validator: Validator,
                 clock: Clock, ids: IdFactory) -> None:
        self._repository = repository
        self._validator = validator
        self._clock = clock
        self._ids = ids

    async def create(self, principal: Any, app_id: str, parent_id: str | None,
                     spec: AppSpec) -> AppVersion:
        outcome = self._validator(spec)
        if outcome.state == "invalid":
            raise InvalidProposal(outcome)
        app = await self._repository.get_owned(_APP, app_id, principal)
        if app is None:
            raise AppNotFound(app_id)
        app = cast(VisionApp, app)
        version = AppVersion(
            id=ResourceId(self._ids.new("version")), app_id=ResourceId(app_id),
            workspace_id=app.workspace_id,
            parent_id=ResourceId(parent_id) if parent_id else None, spec=spec,
            capability_manifest=dict(outcome.capability_manifest),
            model_manifest=dict(outcome.model_manifest),
            validation_report=[issue.code for issue in outcome.issues],
            created_by=ResourceId(str(principal)), created_at=UtcTimestamp(self._clock.now()),
        )
        if not await self._repository.add_immutable(_VERSION, version.id.root, version):
            raise AppConflict("version identifier already exists")
        return version

    async def read(self, principal: Any, version_id: str) -> AppVersion:
        version = await self._repository.get_owned(_VERSION, version_id, principal)
        if version is None:
            raise AppNotFound(version_id)
        return cast(AppVersion, version)


class AppService:
    def __init__(self, repository: ApplicationRepository, versions: VersionService,
                 validator: Validator, ids: IdFactory) -> None:
        self._repository = repository
        self._versions = versions
        self._validator = validator
        self._ids = ids

    async def create(self, principal: Any, title: str) -> VisionApp:
        app = VisionApp(id=ResourceId(self._ids.new("app")), workspace_id=ResourceId(str(principal)),
                        title=title, revision=0)
        if not await self._repository.compare_and_swap(_APP, app.id.root, 0, app):
            raise AppConflict("application identifier already exists")
        return app

    async def list(self, principal: Any) -> list[VisionApp]:
        apps = await self._repository.list_owned(_APP, principal)
        return sorted(apps, key=lambda app: (app.title, app.id.root))

    async def read(self, principal: Any, app_id: str) -> VisionApp:
        app = await self._repository.get_owned(_APP, app_id, principal)
        if app is None:
            raise AppNotFound(app_id)
        return cast(VisionApp, app)

    async def revise(self, principal: Any, app_id: str, expected_revision: int,
                     base_version_id: str | None, spec: AppSpec) -> AppVersion:
        app = await self.read(principal, app_id)
        current_draft = app.draft_version_id.root if app.draft_version_id else None
        if app.revision != expected_revision or current_draft != base_version_id:
            raise AppConflict("stale application revision or base version")
        version = await self._versions.create(principal, app_id, base_version_id, spec)
        updated = app.model_copy(update={"draft_version_id": version.id,
                                         "revision": app.revision + 1})
        if not await self._repository.compare_and_swap(_APP, app_id, expected_revision, updated):
            raise AppConflict("application changed while revision was created")
        return version

    async def publish(self, principal: Any, app_id: str, expected_revision: int,
                      version_id: str, calibration: Calibration | None = None,
                      approved_action_refs: frozenset[str] = frozenset()) -> VisionApp:
        app = await self.read(principal, app_id)
        if app.revision != expected_revision or app.draft_version_id is None or app.draft_version_id.root != version_id:
            raise AppConflict("stale application revision or version is not current draft")
        version = await self._versions.read(principal, version_id)
        outcome = self._validator(version.spec, calibration=calibration,
                                  approved_action_refs=approved_action_refs, publication=True)
        if outcome.state != "publication_ready":
            raise PublicationBlocked(outcome)
        updated = app.model_copy(update={"published_version_id": version.id,
                                         "revision": app.revision + 1})
        if not await self._repository.compare_and_swap(_APP, app_id, expected_revision, updated):
            raise AppConflict("application changed while publishing")
        return updated

    async def readiness(self, principal: Any, version_id: str,
                        calibration: Calibration | None = None,
                        approved_action_refs: frozenset[str] = frozenset()) -> ValidationOutcome:
        version = await self._versions.read(principal, version_id)
        return self._validator(version.spec, calibration=calibration,
                               approved_action_refs=approved_action_refs, publication=True)


class CalibrationService:
    def __init__(self, repository: ApplicationRepository, clock: Clock, ids: IdFactory) -> None:
        self._repository = repository
        self._clock = clock
        self._ids = ids

    async def create(self, principal: Any, source_id: str, camera_binding: str,
                     reference_frame: FrameRef, lanes: dict[str, list[PointN]],
                     lines: dict[str, list[PointN]], rois: dict[str, BoxN],
                     governing_signals: dict[str, str], scene_fingerprint: str) -> Calibration:
        calibration = Calibration(id=ResourceId(self._ids.new("calibration")),
            source_id=ResourceId(source_id), workspace_id=ResourceId(str(principal)),
            camera_binding=camera_binding, revision=1,
            reference_frame=reference_frame, lanes=lanes, lines=lines, rois=rois,
            governing_signals=governing_signals, scene_fingerprint=scene_fingerprint)
        if not await self._repository.compare_and_swap(_CALIBRATION, calibration.id.root, 0, calibration):
            raise AppConflict("calibration identifier already exists")
        return calibration

    async def read(self, principal: Any, calibration_id: str) -> Calibration:
        value = await self._repository.get_owned(_CALIBRATION, calibration_id, principal)
        if value is None:
            raise AppNotFound(calibration_id)
        return cast(Calibration, value)

    async def confirm(self, principal: Any, calibration_id: str, expected_revision: int,
                      confirmed_by: str) -> Calibration:
        return await self._update(principal, calibration_id, expected_revision,
            {"confirmed_by": ResourceId(confirmed_by), "confirmed_at": UtcTimestamp(self._clock.now())})

    async def bind_source(self, principal: Any, calibration_id: str, expected_revision: int,
                          source_id: str, reference_frame: FrameRef,
                          scene_fingerprint: str) -> Calibration:
        current = await self.read(principal, calibration_id)
        changes: dict[str, Any] = {"source_id": ResourceId(source_id),
                                  "reference_frame": reference_frame,
                                  "scene_fingerprint": scene_fingerprint}
        if current.scene_fingerprint != scene_fingerprint:
            changes.update(confirmed_by=None, confirmed_at=None)
        return await self._update(principal, calibration_id, expected_revision, changes)

    async def revise_geometry(self, principal: Any, calibration_id: str, expected_revision: int,
                              *, lanes: dict[str, list[PointN]], lines: dict[str, list[PointN]],
                              rois: dict[str, BoxN], governing_signals: dict[str, str]) -> Calibration:
        return await self._update(principal, calibration_id, expected_revision,
            {"lanes": lanes, "lines": lines, "rois": rois,
             "governing_signals": governing_signals, "confirmed_by": None, "confirmed_at": None})

    async def _update(self, principal: Any, calibration_id: str, expected_revision: int,
                      changes: dict[str, Any]) -> Calibration:
        current = await self.read(principal, calibration_id)
        if current.revision != expected_revision:
            raise AppConflict("stale calibration revision")
        updated = current.model_copy(update={**changes, "revision": expected_revision + 1})
        if not await self._repository.compare_and_swap(_CALIBRATION, calibration_id,
                                                        expected_revision, updated):
            raise AppConflict("calibration changed concurrently")
        return updated


class CacheReuseService:
    """Decides whether sealed perception observations survive a policy edit."""
    @staticmethod
    def can_reuse(previous: AppSpec, proposed: AppSpec,
                  previous_model_manifest: dict[str, str],
                  proposed_model_manifest: dict[str, str]) -> bool:
        if previous_model_manifest != proposed_model_manifest:
            return False
        if not isinstance(previous, TrackedRulesSpec) or not isinstance(proposed, TrackedRulesSpec):
            return False
        def perception(spec: TrackedRulesSpec) -> set[tuple[str, tuple[str, ...]]]:
            return {(rule.capability_id, tuple(sorted(rule.object_classes))) for rule in spec.rules}
        return perception(previous) == perception(proposed)
