"""Error types raised by the MeCentral SDK.

Every HTTP failure becomes a MeCentralError (or a subclass) carrying the
status code, the API's ``error`` message and the decoded body. Transport
failures (DNS, TLS, timeout) become ConnectionError with status 0.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


class MeCentralError(Exception):
    """Base class for every SDK error."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: Optional[str] = None,
        body: Any = None,
        retry_after: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: HTTP status code; 0 for transport failures.
        self.status = status
        #: Machine code from the API body (``code``), when one was sent.
        self.code = code
        #: Decoded response body, or the raw text when it was not JSON.
        self.body = body
        #: Seconds to wait before retrying, from Retry-After or the body.
        self.retry_after = retry_after
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.message} (HTTP {self.status})" if self.status else self.message

    @classmethod
    def from_response(cls, status: int, body: Any, headers: Mapping[str, str]) -> "MeCentralError":
        """Build the most specific error class for a response."""
        message = f"HTTP {status}"
        code = None
        retry_after = None
        if isinstance(body, dict):
            if isinstance(body.get("error"), str) and body["error"]:
                message = body["error"]
            elif isinstance(body.get("message"), str) and body["message"]:
                message = body["message"]
            if isinstance(body.get("code"), str):
                code = body["code"]
            if isinstance(body.get("retry_after"), int):
                retry_after = body["retry_after"]
        elif isinstance(body, str) and body.strip():
            message = body.strip()[:200]

        ra = _header(headers, "retry-after")
        if ra and ra.isdigit():
            retry_after = int(ra)
        request_id = _header(headers, "x-request-id")

        kwargs = dict(status=status, code=code, body=body, retry_after=retry_after, request_id=request_id)
        if status == 401:
            return AuthenticationError(message, **kwargs)
        if status == 403:
            return PermissionError_(message, **kwargs)
        if status == 404:
            return NotFoundError(message, **kwargs)
        if status in (400, 422):
            return ValidationError(message, **kwargs)
        if status == 429:
            return RateLimitError(message, **kwargs)
        if status >= 500:
            return ServerError(message, **kwargs)
        return MeCentralError(message, **kwargs)


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    want = name.lower()
    for k, v in headers.items():
        if k.lower() == want:
            return v
    return None


class AuthenticationError(MeCentralError):
    """401 — the key is missing, malformed, revoked, or expired."""


class PermissionError_(MeCentralError):
    """403 — the key is valid but lacks the scope, IP, or endpoint allowance.

    Named with a trailing underscore so it does not shadow the built-in
    ``PermissionError``. Exported as ``mecentral.PermissionDenied`` too.
    """


PermissionDenied = PermissionError_


class NotFoundError(MeCentralError):
    """404 — the resource does not exist for THIS integration.

    The API never distinguishes "never existed" from "belongs to someone else".
    """


class ValidationError(MeCentralError):
    """400 / 422 — the request was malformed; nothing was applied."""


class RateLimitError(MeCentralError):
    """429 — per-key rate limit. ``retry_after`` says how long to wait."""


class ServerError(MeCentralError):
    """5xx — the API failed. Safe to retry reads; check state before re-sending writes."""


class ConnectionError_(MeCentralError):
    """The request never produced an HTTP response (DNS, TLS, timeout)."""

    def __init__(self, message: str, cause: Optional[BaseException] = None) -> None:
        super().__init__(message, status=0, body=cause)
        self.__cause__ = cause


ConnectionFailed = ConnectionError_


class SignatureVerificationError(MeCentralError):
    """A webhook delivery failed signature or timestamp verification."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status=0)


class DepositTimeoutError(MeCentralError):
    """A deposit job did not complete within the polling window."""

    def __init__(self, job_id: str, last_status: Any) -> None:
        super().__init__(f"Deposit job {job_id} did not complete in time", status=0, body=last_status)
        self.job_id = job_id
        self.last_status = last_status
