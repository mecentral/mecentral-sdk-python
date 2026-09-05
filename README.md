# mecentral

Official MeCentral API client for Python 3.8+. Standard library only; no third-party dependencies.

```bash
pip install mecentral
```

```python
import os
from mecentral import MeCentral

mc = MeCentral(os.environ["MECENTRAL_API_KEY"])

# Documents this integration's account owns
page = mc.vault.list_documents(limit=20)
print(page["total"], [d.get("display_name") for d in page["documents"]])

# File a document into its subject's vault, then wait for the worker
with open("bls-card.pdf", "rb") as fh:
    accepted = mc.vault.deposit_on_behalf(
        subject_email="student@example.edu",
        subject_role="student",
        filename="bls-card.pdf",
        mime_type="application/pdf",
        content=fh.read(),
        grants=[{"user": "coordinator@school.edu", "scope": "co_owner"}],
    )
result = mc.vault.wait_for_deposit(accepted["job_id"])
if result.get("grant_errors"):
    print("some grants did not apply:", result["grant_errors"])
```

## Authentication

Every request sends your key in `X-API-Key`. Keys are `mec_sbx_…` (sandbox) or `mec_prd_…` (production); both talk to the same host. Sandbox keys can be minted without a console login for proof-of-concept builds — see `MeCentral.provision_sandbox`.

```python
mc = MeCentral(
    "mec_sbx_…",
    base_url="https://api.mecentral.org/v1",  # default
    timeout=30.0,                              # default, seconds
    max_retries=2,                             # default
)
```

The People Graph endpoints act on a **member's** graph and need a member connection token as well:

```python
conn = mc.connections.request("member@example.com")
# …the member reads the one-time code MeCentral sent them…
verified = mc.connections.verify(conn["connection_id"], "123456")

member = mc.with_connection(verified["token"])
created = member.people.create(
    full_name="Amelia Glisson",
    relationship="biological_child",
    facts=[{"key": "school", "value": "Parker Elementary"}],
)
```

## Surface

| Group | Methods | Scope |
|---|---|---|
| `vault` | `list_documents`, `get_document`, `download_document`, `deposit_on_behalf`, `deposit_status`, `wait_for_deposit`, `recall_deposit`, `update_subject`, `revoke_subject_binding` | `vault.read`, `custody.read` (stream), `vault.deposit_on_behalf` |
| `custody` | `grant`, `revoke`, `replace`, `dispute`, `assert_event`, `list_events` | `custody.grant`, `custody.replace`, `custody.events` |
| `connections` | `request`, `verify` | any key |
| `people` | `list`, `create`, `get`, `update`, `remove`, `list_facts`, `confirm_facts` | `people.write` + connection token |
| `webhooks` | `list`, `create`, `get`, `update`, `delete`, `event_types` | `webhooks.manage` |
| `integrations` | `list_signing_certificates`, `register_signing_certificate`, `revoke_signing_certificate` | `vault.deposit_on_behalf` |
| `Webhooks` (static) | `construct_event`, `verify`, `sign` | — |

Keyword names are the REST API's own (`snake_case`), so the API reference at `/developers/api` applies unchanged. One exception: `custody.replace(from_=…)` because `from` is a Python keyword. Responses are returned as the API sends them, `success` envelope included. Unknown keywords on `deposit_on_behalf` pass straight through.

## Webhooks

Deliveries are signed with HMAC-SHA256 over `"<timestamp>.<raw body>"` using the secret returned **once** when you register the endpoint. Verify against the raw body, never a re-serialised object.

```python
# Flask
from flask import Flask, request, abort
from mecentral import Webhooks, SignatureVerificationError

app = Flask(__name__)

@app.post("/hooks/mecentral")
def hooks():
    try:
        event = Webhooks.construct_event(request.get_data(), request.headers, os.environ["MECENTRAL_WEBHOOK_SECRET"])
    except SignatureVerificationError:
        abort(400)
    if event.type == "deposit.completed":
        ...  # event.data["document_id"], event.data["grant_errors"], …
    return "", 200
```

Django's `request.META` works as the headers argument too (`HTTP_X_MECENTRAL_SIGNATURE` style keys are recognised).

Deliveries are best-effort and not retried. Treat them as a nudge and reconcile against `vault.deposit_status`, which is the source of truth.

## Errors

All failures raise `MeCentralError` or a subclass with `.status`, `.message`, `.code`, `.retry_after`, and the decoded `.body`.

| Class | Status |
|---|---|
| `AuthenticationError` | 401 |
| `PermissionDenied` | 403 (scope, IP, or endpoint allowlist) |
| `NotFoundError` | 404 (never distinguishes "not yours" from "never existed") |
| `ValidationError` | 400 / 422 |
| `RateLimitError` | 429, `retry_after` in seconds |
| `ServerError` | 5xx |
| `ConnectionFailed` | no HTTP response |
| `SignatureVerificationError` | webhook check failed |
| `DepositTimeoutError` | `wait_for_deposit` ran out of time |

## Retries

`429` and `503` are retried for every method with exponential backoff (honouring `Retry-After`). `502`, `504`, and transport failures are retried only for `GET` and `DELETE`, because a `POST` that timed out may already have been processed. Set `max_retries=0` to disable.

## Sandbox provisioning

```python
issued = MeCentral.provision_sandbox(
    token=os.environ["INTEGRATION_PROVISION_TOKEN"],
    slug="myapp.example.com",
    scopes=["vault.deposit_on_behalf", "custody.grant", "webhooks.manage"],
    ttl_days=90,
)
issued["key"]["key"]  # shown here and nowhere else
```

## Building from source

```bash
pip install build
python -m build   # dist/mecentral-0.1.0-py3-none-any.whl
```
