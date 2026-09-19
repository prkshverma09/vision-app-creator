"""Explicit test-only identity verifier; tokens are registered, never interpreted."""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from .errors import IdentityError
from .models import Principal


@dataclass(frozen=True, slots=True)
class TestIdentity:
    __test__: ClassVar[bool] = False
    user_id: str
    email: str | None
    workspace_ids: frozenset[str]


class FakeIdentityVerifier:
    """A deterministic verifier allowed only in explicitly non-production profiles."""

    def __init__(self, identities: Mapping[str, TestIdentity], profile: str) -> None:
        if profile not in {"test", "cpu", "emulator", "local"}:
            raise ValueError("test identity verifier is forbidden in this profile")
        self._identities = dict(identities)

    async def verify(self, token: str) -> Principal:
        identity = self._identities.get(token)
        if identity is None:
            raise IdentityError()
        return Principal(identity.user_id, identity.email, identity.workspace_ids)
