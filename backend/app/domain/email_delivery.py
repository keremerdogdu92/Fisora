from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage
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
    normalized_recipient = recipient.strip()
    if provider in {"", "disabled"}:
        return _delivery_result("disabled", "disabled", normalized_recipient, action_url)
    if provider == "dry_run":
        return _delivery_result("dry_run", "dry_run", normalized_recipient, action_url)
    if provider == "resend":
        return _send_resend(
            recipient=normalized_recipient,
            subject=subject,
            body_text=body_text,
            action_url=action_url,
            env=config,
        )
    if provider == "brevo":
        return _send_brevo(
            recipient=normalized_recipient,
            subject=subject,
            body_text=body_text,
            action_url=action_url,
            env=config,
        )
    if provider == "smtp":
        return _send_smtp(
            recipient=normalized_recipient,
            subject=subject,
            body_text=body_text,
            action_url=action_url,
            env=config,
        )
    return _delivery_result("error", provider, normalized_recipient, action_url, reason="unsupported_provider")


def _delivery_result(
    status: str,
    provider: str,
    recipient: str,
    action_url: str,
    *,
    reason: str = "",
    provider_message_id: str = "",
) -> dict[str, object]:
    result = {
        "status": status,
        "provider": provider,
        "recipient": recipient,
        "action_url": action_url,
    }
    if reason:
        result["reason"] = reason
    if provider_message_id:
        result["provider_message_id"] = provider_message_id
    return result


def _send_resend(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    action_url: str,
    env: Mapping[str, str],
) -> dict[str, object]:
    api_key = str(env.get("FISORA_RESEND_API_KEY") or "").strip()
    sender = str(env.get("FISORA_EMAIL_FROM") or "").strip()
    if not api_key or not sender or not recipient:
        return _delivery_result("error", "resend", recipient, action_url, reason="missing_resend_config")
    payload = json.dumps(
        {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body_text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return _delivery_result("error", "resend", recipient, action_url, reason=f"send_failed:{type(exc).__name__}")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = {}
    return _delivery_result("sent", "resend", recipient, action_url, provider_message_id=str(decoded.get("id") or ""))


def _send_brevo(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    action_url: str,
    env: Mapping[str, str],
) -> dict[str, object]:
    api_key = str(env.get("FISORA_BREVO_API_KEY") or "").strip()
    sender_email = str(env.get("FISORA_BREVO_SENDER_EMAIL") or env.get("FISORA_EMAIL_FROM") or "").strip()
    sender_name = str(env.get("FISORA_BREVO_SENDER_NAME") or "Fisora").strip() or "Fisora"
    if not api_key or not sender_email or not recipient:
        return _delivery_result("error", "brevo", recipient, action_url, reason="missing_brevo_config")
    payload = json.dumps(
        {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": recipient}],
            "subject": subject,
            "textContent": body_text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return _delivery_result("error", "brevo", recipient, action_url, reason=f"send_failed:{type(exc).__name__}")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = {}
    return _delivery_result(
        "sent",
        "brevo",
        recipient,
        action_url,
        provider_message_id=str(decoded.get("messageId") or decoded.get("message_id") or ""),
    )


def _send_smtp(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    action_url: str,
    env: Mapping[str, str],
) -> dict[str, object]:
    host = str(env.get("FISORA_SMTP_HOST") or "").strip()
    username = str(env.get("FISORA_SMTP_USERNAME") or "").strip()
    password = str(env.get("FISORA_SMTP_PASSWORD") or "").strip()
    sender = str(env.get("FISORA_EMAIL_FROM") or username).strip()
    try:
        port = int(str(env.get("FISORA_SMTP_PORT") or "587").strip())
    except ValueError:
        return _delivery_result("error", "smtp", recipient, action_url, reason="invalid_smtp_port")
    if not host or not username or not password or not sender or not recipient:
        return _delivery_result("error", "smtp", recipient, action_url, reason="missing_smtp_config")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body_text)
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        return _delivery_result("error", "smtp", recipient, action_url, reason=f"send_failed:{type(exc).__name__}")
    return _delivery_result("sent", "smtp", recipient, action_url)
