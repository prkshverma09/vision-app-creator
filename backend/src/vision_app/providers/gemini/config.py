"""Gemini adapter configuration and profile-safe transport selection."""

from dataclasses import dataclass, field


class GeminiProfileError(ValueError):
    """Raised when a fake/scripted transport is requested in production profile."""


@dataclass(frozen=True)
class GeminiConfig:
    """Trusted configuration supplied by the composition root.

    profile comes from a centrally validated source (not an HTTP query parameter or
    untrusted environment value).  fake/scripted transports are prohibited when the
    production profile is active.
    """

    api_key: str | None = field(default=None, repr=False)
    model: str = "gemini-3.6-flash"
    profile: str = "cpu"
    timeout_ms: int = 30_000
    max_retries: int = 3
    retry_base_ms: int = 500
    retry_max_ms: int = 10_000
    provider_name: str = "gemini"
    revision: str = "unverified"
    sample_fps: float = 1.0

    def is_production(self) -> bool:
        return self.profile == "production"
