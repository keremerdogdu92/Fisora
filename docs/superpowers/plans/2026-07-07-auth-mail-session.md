# Auth Mail Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish first-live authentication with custom sessions and free-tier transactional email for invite and password reset links.

**Architecture:** Keep the existing `session_required` custom auth as the first MVP path. Add a small email sender abstraction used by invite and password reset routes; in development it can log links, in production it sends through one configured free-tier provider. `trusted_header` remains documented as a later gateway-only option, not part of this implementation.

**Tech Stack:** FastAPI routes, existing session auth domain, workflow store auth token records, Python standard library HTTP client or SMTP, React portal client actions, Node tests and Python unittest.

---

## File Map

- Create `backend/app/domain/email_delivery.py`: provider-neutral email sender with `disabled`, `smtp`, and `resend` modes.
- Modify `backend/app/api/phase0_routes_auth.py`: send invite/reset links after token creation and return `email_delivery_status`.
- Modify `backend/app/api/phase0_schemas.py`: add optional `email` fields to invite/reset payloads if absent.
- Modify `backend/tests/test_auth_policy.py`: cover invite/reset email delivery behavior without network calls.
- Modify `frontend/app/upload-api.js`: pass invite email and consume delivery status.
- Modify `frontend/app/portal-client-actions.ts`: show mail sent / link copied status instead of raw token as the default message.
- Modify `frontend/app/upload-api.test.cjs`: assert invite payload includes email fields and no raw token display assumption.
- Modify `deploy/production.env.example`: document chosen mail env vars.
- Modify `docs/auth-strategy.md`: record exact first-live mail mode and manual fallback.

## Task 1: Email Delivery Domain

**Files:**
- Create `backend/app/domain/email_delivery.py`
- Test `backend/tests/test_auth_policy.py`

- [ ] **Step 1: Write failing tests for disabled and dry-run delivery**

Add tests that do not call the network.

```python
def test_email_delivery_disabled_returns_link_only(self) -> None:
    from app.domain.email_delivery import send_auth_email

    result = send_auth_email(
        recipient="client@example.com",
        subject="Fisora davet",
        body_text="Link: https://portal.test/invite?token=abc",
        action_url="https://portal.test/invite?token=abc",
        env={"FISORA_EMAIL_PROVIDER": "disabled"},
    )

    self.assertEqual(result["status"], "disabled")
    self.assertEqual(result["action_url"], "https://portal.test/invite?token=abc")
```

```python
def test_email_delivery_dry_run_records_provider_without_network(self) -> None:
    from app.domain.email_delivery import send_auth_email

    result = send_auth_email(
        recipient="client@example.com",
        subject="Fisora sifre sifirlama",
        body_text="Link: https://portal.test/reset?token=abc",
        action_url="https://portal.test/reset?token=abc",
        env={"FISORA_EMAIL_PROVIDER": "dry_run"},
    )

    self.assertEqual(result["status"], "dry_run")
    self.assertEqual(result["provider"], "dry_run")
```

- [ ] **Step 2: Run the targeted test and confirm failure**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy
```

Expected before implementation: `app.domain.email_delivery` does not exist.

- [ ] **Step 3: Implement provider-neutral sender**

Create `email_delivery.py` with this shape:

```python
from __future__ import annotations

import os
from typing import Mapping


def send_auth_email(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    action_url: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    config = env or os.environ
    provider = str(config.get("FISORA_EMAIL_PROVIDER") or "disabled").strip().lower()
    if provider in {"", "disabled"}:
        return {"status": "disabled", "provider": "disabled", "recipient": recipient, "action_url": action_url}
    if provider == "dry_run":
        return {"status": "dry_run", "provider": "dry_run", "recipient": recipient, "action_url": action_url}
    if provider == "resend":
        return _send_resend(recipient=recipient, subject=subject, body_text=body_text, action_url=action_url, env=config)
    if provider == "smtp":
        return _send_smtp(recipient=recipient, subject=subject, body_text=body_text, action_url=action_url, env=config)
    return {"status": "error", "provider": provider, "recipient": recipient, "reason": "unsupported_provider"}
```

Implement `_send_resend` and `_send_smtp` with explicit env validation. They must return a structured `error` status when credentials are missing rather than raising.

- [ ] **Step 4: Run targeted auth tests**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy
```

Expected: existing auth tests and the new sender tests pass.

## Task 2: Invite Email Route

**Files:**
- Modify `backend/app/api/phase0_schemas.py`
- Modify `backend/app/api/phase0_routes_auth.py`
- Test `backend/tests/test_auth_policy.py`

- [ ] **Step 1: Write failing route-level test**

Add a route test or service-adjacent test that patches `send_auth_email`.

```python
def test_invite_route_returns_email_delivery_status(self) -> None:
    from unittest.mock import patch

    with patch("app.api.phase0_routes_auth.send_auth_email") as sender:
        sender.return_value = {"status": "dry_run", "provider": "dry_run", "action_url": "https://portal.test/invite?token=abc"}
        response = self.client.post(
            "/store/auth/invite",
            json={
                "user_id": "client-user",
                "display_name": "Client User",
                "role": "client_user",
                "allowed_client_ids": ["client-1"],
                "invited_by": "mali-musavir",
                "email": "client@example.com",
            },
        )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["email_delivery"]["status"], "dry_run")
```

- [ ] **Step 2: Add `email` to `AuthInvitePayload`**

Use a default empty string to preserve old callers:

```python
email: str = ""
```

- [ ] **Step 3: Build invite accept URL**

In `store_auth_invite`, after token creation, build:

```python
portal_base_url = os.getenv("FISORA_PORTAL_BASE_URL", "").rstrip("/")
action_url = f"{portal_base_url}/portal/invite?token={token.raw_token}" if portal_base_url else ""
```

If `payload.email` and `action_url` are present, call `send_auth_email`. If not, return `{"status": "manual_link", "action_url": action_url}`.

- [ ] **Step 4: Run auth tests**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy
```

Expected: invite route returns token for manual fallback and `email_delivery` for UI status.

## Task 3: Password Reset Email Route

**Files:**
- Modify `backend/app/api/phase0_schemas.py`
- Modify `backend/app/api/phase0_routes_auth.py`
- Test `backend/tests/test_auth_policy.py`

- [ ] **Step 1: Add reset delivery test**

```python
def test_password_reset_route_returns_email_delivery_status(self) -> None:
    from unittest.mock import patch

    with patch("app.api.phase0_routes_auth.send_auth_email") as sender:
        sender.return_value = {"status": "dry_run", "provider": "dry_run", "action_url": "https://portal.test/reset?token=abc"}
        response = self.client.post(
            "/store/auth/password-reset",
            json={"user_id": "client-user", "email": "client@example.com"},
        )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["email_delivery"]["status"], "dry_run")
```

- [ ] **Step 2: Add `email` to reset payload**

Use:

```python
email: str = ""
```

- [ ] **Step 3: Build reset URL and send**

Use:

```python
action_url = f"{portal_base_url}/portal/password-reset?token={token.raw_token}" if portal_base_url else ""
```

Return `email_delivery` with `manual_link` fallback when mail is not configured.

- [ ] **Step 4: Run auth tests**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy
```

Expected: password reset still works without email configuration, and returns delivery status.

## Task 4: Frontend Invite Status

**Files:**
- Modify `frontend/app/upload-api.js`
- Modify `frontend/app/portal-client-actions.ts`
- Test `frontend/app/upload-api.test.cjs`

- [ ] **Step 1: Write failing frontend API test**

```javascript
test("createPortalInvite includes recipient email", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ invite_token: "secret-token", email_delivery: { status: "dry_run" } });
  };

  await api.createPortalInvite({
    apiBaseUrl: "https://example.test",
    userId: "client-user",
    displayName: "Client User",
    clientId: "client-1",
    invitedBy: "mali-musavir",
    email: "client@example.com",
  });

  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.email, "client@example.com");
});
```

- [ ] **Step 2: Add `email` to `createPortalInvite` request body**

Map from selected client user email when available. If no email exists, send empty string and keep manual link fallback.

- [ ] **Step 3: Replace default raw-token status**

Change the success message in `createInviteForSelectedClientAction`:

```typescript
const delivery = result.email_delivery as Record<string, unknown> | undefined;
const status = String(delivery?.status || "");
setInviteStatus(status === "sent" ? "Davet maili gonderildi." : "Davet linki hazir. Mail kapaliysa link elle paylasilabilir.");
```

- [ ] **Step 4: Run frontend tests and build**

Run:

```powershell
node --test frontend/app/upload-api.test.cjs
cd frontend
npm.cmd run build
```

Expected: tests pass and UI build completes.

## Task 5: Env and Final Verification

**Files:**
- Modify `deploy/production.env.example`
- Modify `docs/auth-strategy.md`

- [ ] Add production env examples:

```text
FISORA_AUTH_MODE=session_required
FISORA_PORTAL_BASE_URL=https://portal.example.com
FISORA_EMAIL_PROVIDER=dry_run
FISORA_EMAIL_FROM=noreply@example.com
FISORA_RESEND_API_KEY=
FISORA_SMTP_HOST=
FISORA_SMTP_PORT=587
FISORA_SMTP_USERNAME=
FISORA_SMTP_PASSWORD=
```

- [ ] Run final checks:

```powershell
python -m unittest backend.tests.test_auth_policy
node --test frontend/app/upload-api.test.cjs
cd frontend
npm.cmd run build
git diff --check
```

- [ ] Acceptance:
  - `session_required` remains first-live auth mode.
  - Invite and reset routes return token for manual fallback.
  - Email send is configurable and does not require paid service.
  - UI no longer treats raw token as the normal success path.
