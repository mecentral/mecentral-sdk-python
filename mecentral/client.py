"""MeCentral — the client.

    from mecentral import MeCentral
    mc = MeCentral(os.environ["MECENTRAL_API_KEY"])
    docs = mc.vault.list_documents(limit=20)["documents"]

Authentication is the X-API-Key header. Keys are mec_sbx_… (sandbox),
mec_prd_… (production) or mec_dev_… (legacy). The People Graph endpoints
additionally need a member connection token (mec_tok_…) obtained through
``connections.request`` + ``connections.verify``; pass it as
``connection_token`` or derive a bound client with ``with_connection(token)``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional, Sequence

from ._http import Transport
from .errors import ConnectionError_, MeCentralError
from .resources import Connections, Custody, Integrations, People, Vault, WebhookEndpoints

SDK_VERSION = "0.1.0"
DEFAULT_BASE_URL = "https://api.mecentral.org/v1"

_KEY_RE = re.compile(r"^mec_(sbx|prd|dev)_[0-9a-f]{32,64}$")


class MeCentral:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        connection_token: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        if not api_key or not isinstance(api_key, str):
            raise TypeError("MeCentral(api_key): an API key is required")
        if not _KEY_RE.match(api_key):
            raise TypeError("MeCentral(api_key): keys look like mec_sbx_… or mec_prd_… followed by 32–64 hex characters")

        self._api_key = api_key
        self._options: Dict[str, Any] = {
            "base_url": base_url,
            "connection_token": connection_token,
            "timeout": timeout,
            "max_retries": max_retries,
            "headers": dict(headers) if headers else None,
        }
        self.base_url = base_url.rstrip("/")

        hdrs: Dict[str, str] = {
            "X-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": f"mecentral-sdk-python/{SDK_VERSION}",
        }
        if headers:
            hdrs.update(headers)
        if connection_token:
            hdrs["Authorization"] = f"Bearer {connection_token}"

        transport = Transport(base_url=self.base_url, headers=hdrs, timeout=timeout, max_retries=max_retries)
        self.vault = Vault(transport)
        self.custody = Custody(transport)
        self.connections = Connections(transport)
        self.people = People(transport)
        self.webhooks = WebhookEndpoints(transport)
        self.integrations = Integrations(transport)

    def with_connection(self, connection_token: str) -> "MeCentral":
        """A client bound to one connected member (same key and options plus
        the member's mec_tok_… on every request). Use it for ``people.*``."""
        opts = dict(self._options)
        opts["connection_token"] = connection_token
        return MeCentral(self._api_key, **opts)

    @staticmethod
    def provision_sandbox(
        *,
        token: str,
        slug: str,
        name: Optional[str] = None,
        purpose: Optional[str] = None,
        scopes: Optional[Sequence[str]] = None,
        ttl_days: Optional[int] = None,
        rotate: Optional[bool] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Self-service SANDBOX provisioning for proof-of-concept builds.

        Authenticates with the operator token (INTEGRATION_PROVISION_TOKEN),
        not an API key. The raw key is in the response and nowhere else.
        """
        body: Dict[str, Any] = {"slug": slug}
        if name is not None:
            body["name"] = name
        if purpose is not None:
            body["purpose"] = purpose
        if scopes is not None:
            body["scopes"] = list(scopes)
        if ttl_days is not None:
            body["ttl_days"] = ttl_days
        if rotate is not None:
            body["rotate"] = rotate

        url = base_url.rstrip("/") + "/integrations/provision"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"mecentral-sdk-python/{SDK_VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, hdrs, payload = resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as e:
            status, hdrs, payload = e.code, dict(e.headers.items()) if e.headers else {}, e.read()
        except (urllib.error.URLError, OSError) as e:
            raise ConnectionError_(f"Connection failed: {getattr(e, 'reason', e)}", e) from e

        text = payload.decode("utf-8", errors="replace") if payload else ""
        try:
            decoded: Any = json.loads(text) if text else None
        except ValueError:
            decoded = text
        if not 200 <= status < 300:
            raise MeCentralError.from_response(status, decoded, hdrs)
        return decoded
