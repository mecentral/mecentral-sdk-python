"""Resource groups. Each wraps one family of /v1 endpoints and does nothing
but shape the call: paths, methods, query strings, and a couple of
conveniences (bytes -> base64, poll until a deposit settles).

Parameter names are the REST API's own (snake_case). Anything passed as
``**extra`` is sent through untouched, so a new API field never needs a
new SDK release.
"""

from __future__ import annotations

import base64
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Sequence

from ._http import Transport
from .errors import DepositTimeoutError

JSON = Dict[str, Any]


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _clean(params: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None-valued keys so 'omitted' and 'null' stay distinct on the wire."""
    return {k: v for k, v in params.items() if v is not None}


# ------------------------------------------------------------------ vault


class Vault:
    def __init__(self, t: Transport) -> None:
        self._t = t

    def list_documents(self, *, limit: Optional[int] = None, offset: Optional[int] = None) -> JSON:
        """GET /vault/documents — documents this integration's account owns. Scope: vault.read"""
        return self._t.request("GET", "/vault/documents", query={"limit": limit, "offset": offset})

    def get_document(self, document_id: str) -> JSON:
        """GET /vault/documents/{id} — metadata and custody facts. Scope: vault.read"""
        return self._t.request("GET", f"/vault/documents/{_enc(document_id)}")

    def download_document(self, document_id: str) -> bytes:
        """GET /vault/documents/{id}/stream — the bytes. Scopes: vault.read + custody.read"""
        return self._t.request("GET", f"/vault/documents/{_enc(document_id)}/stream", raw=True, headers={"Accept": "*/*"})

    def deposit_on_behalf(
        self,
        *,
        filename: str,
        mime_type: str,
        content: Optional[bytes] = None,
        content_base64: Optional[str] = None,
        subject_email: Optional[str] = None,
        subject_binding_token: Optional[str] = None,
        subject_identity: Optional[JSON] = None,
        subject_external_id: Optional[str] = None,
        subject_role: Optional[str] = None,
        display_name: Optional[str] = None,
        hold_expires_at: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        grants: Optional[Sequence[JSON]] = None,
        release: Optional[JSON] = None,
        collections: Optional[Sequence[Any]] = None,
        proof_challenge: Optional[JSON] = None,
        content_credential: Optional[JSON] = None,
        **extra: Any,
    ) -> JSON:
        """POST /vault/deposit-on-behalf — file a document into its subject's vault.

        Pass ``content`` (bytes) or ``content_base64``. Returns 202 with a
        ``job_id``; use ``wait_for_deposit`` or ``deposit_status`` for the outcome.
        Scopes: vault.deposit_on_behalf, plus custody.grant when ``grants`` is non-empty.
        """
        if content_base64 is None:
            if content is None:
                raise TypeError("deposit_on_behalf needs `content` (bytes) or `content_base64`")
            content_base64 = base64.b64encode(content).decode("ascii")
        body = _clean(
            {
                "filename": filename,
                "mime_type": mime_type,
                "content_base64": content_base64,
                "subject_email": subject_email,
                "subject_binding_token": subject_binding_token,
                "subject_identity": subject_identity,
                "subject_external_id": subject_external_id,
                "subject_role": subject_role,
                "display_name": display_name,
                "hold_expires_at": hold_expires_at,
                "tags": list(tags) if tags is not None else None,
                "grants": list(grants) if grants is not None else None,
                "release": release,
                "collections": list(collections) if collections is not None else None,
                "proof_challenge": proof_challenge,
                "content_credential": content_credential,
            }
        )
        body.update(extra)
        return self._t.request("POST", "/vault/deposit-on-behalf", body=body)

    def deposit_status(self, job_id: str) -> JSON:
        """GET /vault/deposit-status — the source of truth for a deposit. Scope: vault.deposit_on_behalf"""
        return self._t.request("GET", "/vault/deposit-status", query={"job_id": job_id})

    def wait_for_deposit(self, job_id: str, *, interval: float = 2.0, timeout: float = 120.0) -> JSON:
        """Poll until the job is completed or failed and return the final status.

        A failed job is returned, not raised (check ``status``), so callers can
        read ``grant_errors`` and ``provenance`` either way.
        """
        interval = max(0.5, interval)
        deadline = time.monotonic() + timeout
        while True:
            last = self.deposit_status(job_id)
            if last.get("status") in ("completed", "failed"):
                return last
            if time.monotonic() + interval > deadline:
                raise DepositTimeoutError(job_id, last)
            time.sleep(interval)

    def recall_deposit(self, job_id: str, *, reason: Optional[str] = None) -> JSON:
        """POST /vault/recall — cancel, un-hold, or contain a deposit. Idempotent."""
        return self._t.request("POST", "/vault/recall", body=_clean({"job_id": job_id, "reason": reason}))

    def update_subject(
        self,
        *,
        date_of_birth: str,
        subject_email: Optional[str] = None,
        document_id: Optional[str] = None,
        full_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> JSON:
        """POST /vault/subject-update — supply or correct a subject's date of birth."""
        body = _clean(
            {
                "date_of_birth": date_of_birth,
                "subject_email": subject_email,
                "document_id": document_id,
                "full_name": full_name,
                "reason": reason,
            }
        )
        return self._t.request("POST", "/vault/subject-update", body=body)

    def revoke_subject_binding(self, binding_token: str, *, reason: Optional[str] = None) -> JSON:
        """DELETE /vault/subject-bindings — revoke a TrueRoute binding token. Idempotent."""
        return self._t.request("DELETE", "/vault/subject-bindings", body=_clean({"binding_token": binding_token, "reason": reason}))


# ---------------------------------------------------------------- custody


class Custody:
    def __init__(self, t: Transport) -> None:
        self._t = t

    def grant(self, *, document_ids: Sequence[str], grants: Sequence[JSON]) -> JSON:
        """POST /custody/grants — per-item failures are in ``grant_errors``. Scope: custody.grant"""
        return self._t.request("POST", "/custody/grants", body={"document_ids": list(document_ids), "grants": list(grants)})

    def revoke(self, *, document_ids: Sequence[str], grants: Sequence[JSON], reason: Optional[str] = None) -> JSON:
        """DELETE /custody/grants — revoke (tombstone) grants. Idempotent. Scope: custody.grant"""
        body = _clean({"document_ids": list(document_ids), "grants": list(grants), "reason": reason})
        return self._t.request("DELETE", "/custody/grants", body=body)

    def replace(
        self,
        *,
        from_: str,
        to: str,
        scope: str,
        subject_email: Optional[str] = None,
        document_id: Optional[str] = None,
        relationship: Optional[str] = None,
        expiry: Optional[JSON] = None,
        reason: Optional[str] = None,
    ) -> JSON:
        """POST /custody/replace — end one custodian's authority and start another's atomically. Scope: custody.replace"""
        body = _clean(
            {
                "from": from_,
                "to": to,
                "scope": scope,
                "subject_email": subject_email,
                "document_id": document_id,
                "relationship": relationship,
                "expiry": expiry,
                "reason": reason,
            }
        )
        return self._t.request("POST", "/custody/replace", body=body)

    def dispute(self, *, reason: str, subject_email: Optional[str] = None, document_id: Optional[str] = None) -> JSON:
        """POST /custody/dispute — suspend every grant on a vault pending human review. Idempotent. Scope: custody.events"""
        body = _clean({"reason": reason, "subject_email": subject_email, "document_id": document_id})
        return self._t.request("POST", "/custody/dispute", body=body)

    def assert_event(
        self,
        *,
        event: str,
        subject_email: Optional[str] = None,
        document_id: Optional[str] = None,
        evidence: Optional[str] = None,
        note: Optional[str] = None,
    ) -> JSON:
        """POST /custody/events — assert a life event and resolve every term bound to it. Scope: custody.events"""
        body = _clean({"event": event, "subject_email": subject_email, "document_id": document_id, "evidence": evidence, "note": note})
        return self._t.request("POST", "/custody/events", body=body)

    def list_events(self, *, subject_email: Optional[str] = None, document_id: Optional[str] = None, limit: Optional[int] = None) -> JSON:
        """GET /custody/events — the custody ledger as this integration may see it. Scope: custody.events"""
        return self._t.request("GET", "/custody/events", query={"subject_email": subject_email, "document_id": document_id, "limit": limit})


# ------------------------------------------------------------ connections


class Connections:
    def __init__(self, t: Transport) -> None:
        self._t = t

    def request(self, email: str) -> JSON:
        """POST /connections/request — ask a member to connect; MeCentral sends them an OTP."""
        return self._t.request("POST", "/connections/request", body={"email": email})

    def verify(self, connection_id: str, otp: str) -> JSON:
        """POST /connections/verify — exchange the OTP for a member token (mec_tok_…)."""
        return self._t.request("POST", "/connections/verify", body={"connection_id": connection_id, "otp": otp})


# ----------------------------------------------------------------- people


class People:
    """A connected member's People Graph. Needs a connection token on the client. Scope: people.write"""

    def __init__(self, t: Transport) -> None:
        self._t = t

    def list(self) -> JSON:
        """GET /people"""
        return self._t.request("GET", "/people")

    def create(
        self,
        *,
        full_name: str,
        date_of_birth: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        relationship: Optional[str] = None,
        facts: Optional[Sequence[JSON]] = None,
    ) -> JSON:
        """POST /people — 201. A bad ``relationship`` code is reported under relationship_error, not fatal."""
        body = _clean(
            {
                "full_name": full_name,
                "date_of_birth": date_of_birth,
                "jurisdiction": jurisdiction,
                "relationship": relationship,
                "facts": list(facts) if facts is not None else None,
            }
        )
        return self._t.request("POST", "/people", body=body)

    def get(self, person_id: str) -> JSON:
        """GET /people/{person_id}"""
        return self._t.request("GET", f"/people/{_enc(person_id)}")

    def update(self, person_id: str, **fields: Any) -> JSON:
        """PATCH /people/{person_id} — any of full_name, date_of_birth, jurisdiction, relationship.

        Pass ``None`` explicitly to clear a field (date_of_birth, jurisdiction,
        relationship); omit it to leave it untouched.
        """
        return self._t.request("PATCH", f"/people/{_enc(person_id)}", body=dict(fields))

    def remove(self, person_id: str, *, reason: Optional[str] = None) -> JSON:
        """DELETE /people/{person_id} — tombstone. Idempotent (already_removed)."""
        return self._t.request("DELETE", f"/people/{_enc(person_id)}", body={"reason": reason} if reason else None)

    def list_facts(self, person_id: str) -> JSON:
        """GET /people/{person_id}/facts"""
        return self._t.request("GET", f"/people/{_enc(person_id)}/facts")

    def confirm_facts(self, person_id: str, facts: Sequence[JSON]) -> JSON:
        """POST /people/{person_id}/facts — malformed facts land in ``rejected``."""
        return self._t.request("POST", f"/people/{_enc(person_id)}/facts", body={"facts": list(facts)})


# --------------------------------------------------------------- webhooks


class WebhookEndpoints:
    """Endpoint registration. Scope: webhooks.manage. Verification lives in ``mecentral.Webhooks``."""

    def __init__(self, t: Transport) -> None:
        self._t = t

    def list(self) -> JSON:
        """GET /webhooks/endpoints"""
        return self._t.request("GET", "/webhooks/endpoints")

    def create(self, *, url: str, enabled_events: Sequence[str], description: Optional[str] = None) -> JSON:
        """POST /webhooks/endpoints — 201. The ``secret`` in the response is shown once."""
        body = _clean({"url": url, "enabled_events": list(enabled_events), "description": description})
        return self._t.request("POST", "/webhooks/endpoints", body=body)

    def get(self, endpoint_id: str) -> JSON:
        """GET /webhooks/endpoints/{id}"""
        return self._t.request("GET", f"/webhooks/endpoints/{_enc(endpoint_id)}")

    def update(self, endpoint_id: str, **fields: Any) -> JSON:
        """PATCH /webhooks/endpoints/{id} — any of url, enabled_events, description, disabled."""
        return self._t.request("PATCH", f"/webhooks/endpoints/{_enc(endpoint_id)}", body=dict(fields))

    def delete(self, endpoint_id: str) -> JSON:
        """DELETE /webhooks/endpoints/{id}"""
        return self._t.request("DELETE", f"/webhooks/endpoints/{_enc(endpoint_id)}")

    def event_types(self) -> JSON:
        """GET /webhooks/events — the catalog registration validates against."""
        return self._t.request("GET", "/webhooks/events")


# ----------------------------------------------------------- integrations


class Integrations:
    """Scope: vault.deposit_on_behalf"""

    def __init__(self, t: Transport) -> None:
        self._t = t

    def list_signing_certificates(self) -> JSON:
        """GET /integrations/signing-certificates"""
        return self._t.request("GET", "/integrations/signing-certificates")

    def register_signing_certificate(self, *, certificate_pem: str, label: Optional[str] = None) -> JSON:
        """POST /integrations/signing-certificates — only the fingerprint is kept."""
        return self._t.request("POST", "/integrations/signing-certificates", body=_clean({"certificate_pem": certificate_pem, "label": label}))

    def revoke_signing_certificate(self, *, fingerprint_sha256: str, reason: Optional[str] = None) -> JSON:
        """DELETE /integrations/signing-certificates — tombstone."""
        return self._t.request("DELETE", "/integrations/signing-certificates", body=_clean({"fingerprint_sha256": fingerprint_sha256, "reason": reason}))


__all__: List[str] = ["Vault", "Custody", "Connections", "People", "WebhookEndpoints", "Integrations"]
