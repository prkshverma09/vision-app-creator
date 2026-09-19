"""Typed action permission, eligibility, destination, and delivery state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Permission:
    id: str
    version: int
    workspace_id: str
    destination_ref: str
    enabled: bool
    preapproved: bool = False


@dataclass(frozen=True)
class ActionContext:
    workspace_id: str
    event_id: str
    event_revision: int
    machine_decision: str
    human_review: str
    selected_finalized: bool
    run_mode: str
    action_ref: str
    explicitly_enabled: bool
    deleted: bool
    cancelled: bool
    budget_available: bool


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...] = ()


class DeliveryState(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    SUPPRESSED = "suppressed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class DeliveryRecord:
    id: str
    event_id: str
    event_revision: int
    destination_ref: str
    permission_id: str
    permission_version: int
    state: DeliveryState = DeliveryState.PENDING
    attempts: int = 0
    last_error: str | None = None
    response_status: int | None = None


@dataclass(frozen=True)
class Destination:
    id: str
    url: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("webhook destination must use HTTPS with a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credentials are forbidden in webhook URLs")
        if parsed.fragment:
            raise ValueError("fragments are forbidden in webhook URLs")
