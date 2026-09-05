"""HTTP transport on the standard library (no third-party dependencies).

Retry policy (see README "Retries"):
  - 429 is retried for every method, honouring Retry-After.
  - 503 is retried for every method (the edge refused before processing).
  - 502 / 504 and transport failures are retried for GET and DELETE only.
    A POST that timed out may have been processed; the caller decides.
"""

from __future__ import annotations

import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Union

from .errors import ConnectionError_, MeCentralError

_IDEMPOTENT = frozenset({"GET", "DELETE"})
_MAX_BACKOFF = 8.0

Query = Mapping[str, Union[str, int, bool, None]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: a JSON API that answers 3xx is misconfigured,
    and a followed 301 silently turns a POST into a GET. The 3xx surfaces as
    an HTTPError and becomes a MeCentralError below."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class Transport:
    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        timeout: float,
        max_retries: int,
        sleep: Callable[[float], None] = time.sleep,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._sleep = sleep
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    # ------------------------------------------------------------------ api

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Query] = None,
        body: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        raw: bool = False,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Any:
        url = self._url(path, query)
        hdrs: Dict[str, str] = dict(self.headers)
        if headers:
            hdrs.update(headers)
        data: Optional[bytes] = None
        if body is not None:
            hdrs["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")

        retries = self.max_retries if max_retries is None else max(0, max_retries)
        tmo = self.timeout if timeout is None else timeout
        idempotent = method in _IDEMPOTENT

        attempt = 0
        while True:
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with self._opener.open(req, timeout=tmo) as resp:
                    status = resp.status
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    payload = resp.read()
            except urllib.error.HTTPError as e:
                status = e.code
                resp_headers = {k: v for k, v in e.headers.items()} if e.headers else {}
                payload = e.read() if hasattr(e, "read") else b""
            except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as e:
                if idempotent and attempt < retries:
                    self._sleep(_backoff(attempt, None))
                    attempt += 1
                    continue
                reason = getattr(e, "reason", None) or e
                raise ConnectionError_(f"Connection failed: {reason}", e) from e

            if 200 <= status < 300:
                if raw:
                    return payload
                return _decode(payload, resp_headers)

            if 300 <= status < 400:
                location = next((v for k, v in resp_headers.items() if k.lower() == "location"), None)
                raise MeCentralError(
                    f"Unexpected redirect from {url}" + (f" to {location}" if location else "") + "; the SDK never follows redirects",
                    status=status,
                )

            decoded = _decode(payload, resp_headers)
            error = MeCentralError.from_response(status, decoded, resp_headers)
            retryable = status in (429, 503) or (idempotent and status in (502, 504))
            if retryable and attempt < retries:
                self._sleep(_backoff(attempt, error.retry_after))
                attempt += 1
                continue
            raise error

    # -------------------------------------------------------------- helpers

    def _url(self, path: str, query: Optional[Query]) -> str:
        rel = path if path.startswith("/") else "/" + path
        url = self.base_url + rel
        if query:
            params = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in query.items() if v is not None}
            if params:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return url


def _decode(payload: bytes, headers: Mapping[str, str]) -> Any:
    if not payload:
        return None
    text = payload.decode("utf-8", errors="replace")
    ct = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            ct = v
            break
    if "json" in ct or text[:1] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def _backoff(attempt: int, retry_after: Optional[int]) -> float:
    if retry_after is not None and retry_after >= 0:
        return min(float(retry_after), 60.0)
    base = 0.4 * (2**attempt)
    return min(base + random.random() * 0.2, _MAX_BACKOFF)
