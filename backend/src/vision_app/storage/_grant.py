"""In-memory scoped grant lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from vision_app.storage._id import make_opaque_id
from vision_app.storage.errors import StorageError

if TYPE_CHECKING:
    from vision_app.contracts.ports import Clock


@dataclass
class GrantRecord:
    grant_id: str
    scope: Literal["upload", "read"]
    resource_id: str
    owner_id: str
    expires_at: datetime
    upload_url: str | None = None
    used: bool = False
    result_resource_id: str | None = None


class GrantManager:
    """Issues and validates scoped, time-bounded grants in process memory.

    Production cloud adapters should replace the in-memory store with a
    tamper-evident signed token or short-lived server-side session.
    """

    def __init__(self, clock: "Clock") -> None:
        self._clock = clock
        self._grants: dict[str, GrantRecord] = {}

    def issue(
        self,
        scope: Literal["upload", "read"],
        resource_id: str,
        owner_id: str,
        ttl_seconds: int,
        upload_url: str | None = None,
    ) -> GrantRecord:
        grant_id = make_opaque_id("grant")
        expires_at = self._clock.now() + timedelta(seconds=ttl_seconds)
        record = GrantRecord(
            grant_id=grant_id,
            scope=scope,
            resource_id=resource_id,
            owner_id=owner_id,
            expires_at=expires_at,
            upload_url=upload_url,
        )
        self._grants[grant_id] = record
        return record

    def consume(self, grant_id: str, expected_scope: str) -> GrantRecord:
        record = self._grants.get(grant_id)
        if record is None:
            raise StorageError("invalid_grant", "grant not found")
        if record.expires_at < self._clock.now():
            raise StorageError("grant_expired", "grant has expired")
        if record.scope != expected_scope:
            raise StorageError(
                "grant_scope_mismatch",
                f"grant scope {record.scope} cannot be used for {expected_scope}",
            )
        return record

    def get(self, grant_id: str) -> GrantRecord:
        record = self._grants.get(grant_id)
        if record is None:
            raise StorageError("invalid_grant")
        return record
