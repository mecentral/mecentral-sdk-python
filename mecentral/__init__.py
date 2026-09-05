"""Official MeCentral API client.

    from mecentral import MeCentral, Webhooks
"""

from .client import DEFAULT_BASE_URL, SDK_VERSION, MeCentral
from .errors import (
    AuthenticationError,
    ConnectionError_,
    ConnectionFailed,
    DepositTimeoutError,
    MeCentralError,
    NotFoundError,
    PermissionDenied,
    PermissionError_,
    RateLimitError,
    ServerError,
    SignatureVerificationError,
    ValidationError,
)
from .resources import Connections, Custody, Integrations, People, Vault, WebhookEndpoints
from .webhooks import WebhookEvent, Webhooks

__version__ = SDK_VERSION

__all__ = [
    "MeCentral",
    "Webhooks",
    "WebhookEvent",
    "SDK_VERSION",
    "DEFAULT_BASE_URL",
    "MeCentralError",
    "AuthenticationError",
    "PermissionDenied",
    "PermissionError_",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
    "ConnectionFailed",
    "ConnectionError_",
    "SignatureVerificationError",
    "DepositTimeoutError",
    "Vault",
    "Custody",
    "Connections",
    "People",
    "WebhookEndpoints",
    "Integrations",
]
