"""Internal identity errors and their deliberately small public representation."""
from dataclasses import dataclass
from typing import Any


class IdentityError(Exception):
    def __init__(self, code: str = "invalid_token") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PublicSecurityError(Exception):
    status_code: int
    code: str
    message: str


def map_security_error(error: Exception, request_id: str) -> dict[str, Any]:
    """Map failures without exposing token, provider, repository, or resource details."""
    if isinstance(error, IdentityError):
        code, message = "invalid_identity", "Authentication is required."
    elif isinstance(error, PublicSecurityError):
        code, message = error.code, error.message
    else:
        code, message = "internal_error", "The request could not be completed."
    return {
        "code": code,
        "message": message,
        "field_errors": [],
        "request_id": request_id,
        "retryable": False,
    }
