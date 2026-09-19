"""Safe, explicitly authorized external action delivery."""
from .eligibility import eligibility
from .models import (
    ActionContext,
    DeliveryRecord,
    DeliveryState,
    Destination,
    EligibilityResult,
    Permission,
)
from .outbox import (
    ActionNotEligible,
    ActionService,
    InMemoryDeliveryStore,
    RetryBudgetExhausted,
)
from .transport import (
    DeliveryRateLimited,
    DestinationSafetyError,
    InMemoryWebhookSink,
    SafeWebhookTransport,
    StaticResolver,
    SystemResolver,
    TransportResponse,
)

__all__ = [
    "ActionContext",
    "ActionNotEligible",
    "ActionService",
    "DeliveryRateLimited",
    "DeliveryRecord",
    "DeliveryState",
    "Destination",
    "DestinationSafetyError",
    "EligibilityResult",
    "InMemoryDeliveryStore",
    "InMemoryWebhookSink",
    "Permission",
    "RetryBudgetExhausted",
    "SafeWebhookTransport",
    "StaticResolver",
    "SystemResolver",
    "TransportResponse",
    "eligibility",
]
