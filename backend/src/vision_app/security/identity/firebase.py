"""Firebase Admin ID-token verifier with explicit profile and claim validation."""
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from importlib import import_module
from typing import Any

from .errors import IdentityError
from .models import Principal

Claims = Mapping[str, Any]
Decoder = Callable[[str], Claims]


class FirebaseIdentityVerifier:
    """Verify Firebase ID tokens and resolve membership from verified claims only.

    ``decoder`` is an injection seam for component tests. Production composition should omit
    it, which uses ``firebase_admin.auth.verify_id_token`` and performs signature/revocation
    checks according to the configured Admin application.
    """

    def __init__(
        self,
        project_id: str,
        profile: str,
        decoder: Decoder | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id is required")
        self._project_id = project_id
        self._profile = profile
        self._decoder = decoder
        self._now = now or (lambda: datetime.now(UTC))

    def _firebase_decode(self, token: str) -> Claims:
        try:
            auth = import_module("firebase_admin.auth")
            decoded = auth.verify_id_token(token, check_revoked=True)
        except Exception as error:
            raise IdentityError() from error
        if not isinstance(decoded, Mapping):
            raise IdentityError()
        return decoded

    async def verify(self, token: str) -> Principal:
        if not token or token.strip() != token:
            raise IdentityError()
        try:
            verified = (self._decoder or self._firebase_decode)(token)
            return self._principal(verified)
        except IdentityError:
            raise
        except Exception as error:
            raise IdentityError() from error

    def _principal(self, claims: Claims) -> Principal:
        now = int(self._now().timestamp())
        exp = claims.get("exp")
        if not isinstance(exp, int) or exp <= now:
            raise IdentityError("expired_token")
        issued = claims.get("iat")
        if not isinstance(issued, int) or issued > now + 60:
            raise IdentityError()
        issuer = f"https://securetoken.google.com/{self._project_id}"
        if claims.get("aud") != self._project_id or claims.get("iss") != issuer:
            raise IdentityError()
        if self._profile in {"production", "prod", "cloud"} and _is_emulator(claims):
            raise IdentityError()
        user_id = claims.get("sub") or claims.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise IdentityError()
        memberships = claims.get("workspaces")
        if not isinstance(memberships, list | tuple) or not all(
            isinstance(value, str) and value for value in memberships
        ):
            raise IdentityError()
        email = claims.get("email")
        if email is not None and not isinstance(email, str):
            raise IdentityError()
        return Principal(user_id, email, frozenset(memberships))


def _is_emulator(claims: Claims) -> bool:
    firebase = claims.get("firebase")
    return bool(
        claims.get("emulator") is True
        or (isinstance(firebase, Mapping) and firebase.get("emulator") is True)
    )
