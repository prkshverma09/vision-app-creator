from datetime import UTC, datetime, timedelta

import pytest
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    InMemoryOwnershipResolver,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.errors import (
    IdentityError,
    PublicSecurityError,
    map_security_error,
)
from vision_app.security.identity.firebase import FirebaseIdentityVerifier
from vision_app.security.identity.models import Principal
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def claims(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "sub": "user-a",
        "email": "a@example.test",
        "aud": "production-project",
        "iss": "https://securetoken.google.com/production-project",
        "iat": int((NOW - timedelta(minutes=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=5)).timestamp()),
        "workspaces": ["workspace-a"],
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"exp": int((NOW - timedelta(seconds=1)).timestamp())}, "expired_token"),
        ({"aud": "other-project"}, "invalid_token"),
        ({"iss": "https://securetoken.google.com/other-project"}, "invalid_token"),
        ({"firebase": {"sign_in_provider": "custom", "emulator": True}}, "invalid_token"),
    ],
)
async def test_production_rejects_expired_wrong_project_and_emulator_tokens(
    changed: dict[str, object], code: str
) -> None:
    verifier = FirebaseIdentityVerifier(
        project_id="production-project",
        profile="production",
        decoder=lambda _token: claims(**changed),
        now=lambda: NOW,
    )
    with pytest.raises(IdentityError) as raised:
        await verifier.verify("opaque-token")
    assert raised.value.code == code


@pytest.mark.asyncio
async def test_verified_memberships_are_resolved_without_caller_workspace() -> None:
    verifier = FirebaseIdentityVerifier(
        project_id="production-project",
        profile="production",
        decoder=lambda _token: claims(workspaces=["workspace-a", "workspace-shared"]),
        now=lambda: NOW,
    )
    principal = await verifier.verify("opaque-token")
    assert principal.user_id == "user-a"
    assert principal.email == "a@example.test"
    assert principal.workspace_ids == frozenset({"workspace-a", "workspace-shared"})


@pytest.mark.asyncio
async def test_fake_identity_is_explicit_and_never_enabled_in_production() -> None:
    identity = TestIdentity("user-a", "a@example.test", frozenset({"workspace-a"}))
    with pytest.raises(ValueError):
        FakeIdentityVerifier({"test-token": identity}, profile="production")
    fake = FakeIdentityVerifier({"test-token": identity}, profile="test")
    assert (await fake.verify("test-token")).user_id == "user-a"
    with pytest.raises(IdentityError):
        await fake.verify("user-a")


@pytest.fixture

def boundary() -> AuthorizationBoundary:
    ownership = [
        ResourceOwnership(family, f"{family.value}-a", "workspace-a")
        for family in ResourceFamily
    ]
    return AuthorizationBoundary(InMemoryOwnershipResolver(ownership))


@pytest.mark.asyncio
@pytest.mark.parametrize("family", list(ResourceFamily))
async def test_every_resource_family_checks_workspace_ownership(
    boundary: AuthorizationBoundary, family: ResourceFamily
) -> None:
    user_a = Principal("user-a", "a@example.test", frozenset({"workspace-a"}))
    user_b = Principal("user-b", "b@example.test", frozenset({"workspace-b"}))
    owned = await boundary.require(user_a, family, f"{family.value}-a")
    assert owned.workspace_id == "workspace-a"
    with pytest.raises(PublicSecurityError) as raised:
        await boundary.require(
            user_b, family, f"{family.value}-a", caller_workspace_id="workspace-a"
        )
    assert raised.value.status_code == 404
    assert raised.value.code == "resource_not_found"
    assert "workspace-a" not in raised.value.message


@pytest.mark.asyncio
async def test_user_b_cannot_obtain_user_a_evidence_by_id_substitution(
    boundary: AuthorizationBoundary,
) -> None:
    user_b = Principal("user-b", "b@example.test", frozenset({"workspace-b"}))
    with pytest.raises(PublicSecurityError) as raised:
        await boundary.evidence(user_b, "evidence-a")
    assert raised.value.status_code == 404


def test_security_errors_are_safely_mapped() -> None:
    public = map_security_error(
        RuntimeError("secret database path /internal/a"), request_id="req-1"
    )
    assert public == {
        "code": "internal_error",
        "message": "The request could not be completed.",
        "field_errors": [],
        "request_id": "req-1",
        "retryable": False,
    }
