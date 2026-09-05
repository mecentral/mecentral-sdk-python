"""Webhook delivery verification.

Every delivery carries::

    X-MeCentral-Event:     deposit.completed
    X-MeCentral-Timestamp: 1785000000
    X-MeCentral-Signature: sha256=<hex>

where the signature is HMAC-SHA256 over ``"<timestamp>.<raw body>"`` keyed
with the endpoint secret returned once at registration. The timestamp is
inside the signed string so a captured delivery cannot be replayed later.

Use the RAW request body. Re-serialising parsed JSON changes bytes and
breaks the signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Union

from .errors import SignatureVerificationError

_SIG_RE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


@dataclass
class WebhookEvent:
    #: From X-MeCentral-Event
    type: str
    #: Unix seconds, from X-MeCentral-Timestamp
    timestamp: int
    #: Decoded JSON body
    data: Dict[str, Any]
    #: The raw body as delivered
    raw: str


def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    want = name.lower()
    # Django / WSGI style: HTTP_X_MECENTRAL_SIGNATURE
    wsgi = "HTTP_" + name.upper().replace("-", "_")
    for k, v in headers.items():
        if k.lower() == want or k == wsgi:
            if isinstance(v, (list, tuple)):
                return str(v[0]) if v else None
            return str(v)
    return None


def _as_text(body: Union[str, bytes, bytearray]) -> str:
    if isinstance(body, str):
        return body
    return bytes(body).decode("utf-8")


class Webhooks:
    @staticmethod
    def construct_event(
        raw_body: Union[str, bytes, bytearray],
        headers: Mapping[str, Any],
        secret: str,
        *,
        tolerance: int = 300,
        now: Callable[[], int] = lambda: int(time.time()),
    ) -> WebhookEvent:
        """Verify a delivery and return the parsed event.

        Raises SignatureVerificationError on any failure (missing header, bad
        signature, stale timestamp, unparseable body).
        """
        if not secret:
            raise SignatureVerificationError("Webhook secret is empty")

        sig = _header(headers, "X-MeCentral-Signature")
        ts_raw = _header(headers, "X-MeCentral-Timestamp")
        event_type = _header(headers, "X-MeCentral-Event")
        if not sig:
            raise SignatureVerificationError("Missing X-MeCentral-Signature header")
        if not ts_raw or not ts_raw.isdigit():
            raise SignatureVerificationError("Missing or malformed X-MeCentral-Timestamp header")
        if not event_type:
            raise SignatureVerificationError("Missing X-MeCentral-Event header")

        m = _SIG_RE.match(sig.strip())
        if not m:
            raise SignatureVerificationError("Malformed X-MeCentral-Signature header")

        ts = int(ts_raw)
        drift = abs(now() - ts)
        if drift > tolerance:
            raise SignatureVerificationError(f"Timestamp outside tolerance ({drift}s > {tolerance}s)")

        raw = _as_text(raw_body)
        expected = hmac.new(secret.encode("utf-8"), f"{ts}.{raw}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, m.group(1).lower()):
            raise SignatureVerificationError("Signature mismatch")

        try:
            data = json.loads(raw)
        except ValueError:
            raise SignatureVerificationError("Body is not valid JSON") from None
        if not isinstance(data, dict):
            raise SignatureVerificationError("Body is not a JSON object")
        return WebhookEvent(type=event_type, timestamp=ts, data=data, raw=raw)

    @staticmethod
    def verify(raw_body: Union[str, bytes, bytearray], headers: Mapping[str, Any], secret: str, *, tolerance: int = 300) -> bool:
        """Boolean form of construct_event for callers that do not want exceptions."""
        try:
            Webhooks.construct_event(raw_body, headers, secret, tolerance=tolerance)
            return True
        except SignatureVerificationError:
            return False

    @staticmethod
    def sign(raw_body: str, secret: str, *, event: str = "deposit.completed", timestamp: Optional[int] = None) -> Dict[str, str]:
        """Produce the headers MeCentral would send for a body — for tests and
        for simulating deliveries against your own receiver."""
        ts = int(time.time()) if timestamp is None else timestamp
        mac = hmac.new(secret.encode("utf-8"), f"{ts}.{raw_body}".encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "X-MeCentral-Event": event,
            "X-MeCentral-Timestamp": str(ts),
            "X-MeCentral-Signature": f"sha256={mac}",
        }
