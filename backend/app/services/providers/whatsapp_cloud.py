"""
Meta WhatsApp Cloud API provider.

Why this exists alongside the Twilio one
------------------------------------------------------------------------------
Twilio's trial tier refuses free text on every channel: WhatsApp wants a
ContentSid, SMS wants a predefined template name, and creating a template is
gated behind a paid plan. A payment reminder has to say a real name and a real
amount, so none of that is usable.

Meta runs WhatsApp, and their Cloud API has a genuinely free tier: a test
sender issued instantly, up to five verified recipients, and custom templates
allowed. Same product, no paywall between us and a sentence.

------------------------------------------------------------------------------
The 24-hour rule, which is WhatsApp's and not any vendor's
------------------------------------------------------------------------------
WhatsApp does not let a business send free text to somebody who has not
messaged them recently. That is a platform rule and it applies here too:

    inside 24h of their last message   free text works
    outside it                         only an approved template

So this provider sends free text and, when Meta rejects it for being outside
the window, says exactly that rather than reporting a generic failure. The
merchant's fix is to have the customer message them once, which is a thing a
merchant can actually do.

Credentials are read from the environment at call time and never logged.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .base import MessagingError, MessagingNotConfigured

GRAPH_ROOT = "https://graph.facebook.com"
SEND_TIMEOUT = 20.0
MAX_BODY_CHARS = 4096  # WhatsApp's own limit for a text body.

# Meta's own codes, translated into the one thing the merchant can act on.
ERROR_HINTS = {
    131047: (
        "outside the 24-hour window, so free text is not allowed. Ask the "
        "customer to send any message to your WhatsApp number, which reopens "
        "it, or use an approved template"
    ),
    131026: (
        "that number cannot receive WhatsApp messages. On a test sender it "
        "must first be added under API Setup > recipient phone number and "
        "confirmed by OTP"
    ),
    131030: (
        "that number is not in your test sender's allow-list. Add it under "
        "WhatsApp > API Setup"
    ),
    132000: "the template exists but the variable count does not match",
    190: "the access token is invalid or has expired. Temporary tokens last 24 hours",
    100: "a parameter was rejected: usually the phone number id or the recipient format",
}


def _clean(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if value.upper().startswith("YOUR_"):
        return ""
    return value


def phone_number_id() -> str:
    return _clean("WHATSAPP_PHONE_NUMBER_ID")


def _access_token() -> str:
    return _clean("WHATSAPP_ACCESS_TOKEN")


def api_version() -> str:
    return _clean("WHATSAPP_API_VERSION") or "v21.0"


def recipient_default() -> str:
    return _clean("MERCHANT_ALERT_NUMBER")


def notifications_enabled() -> bool:
    value = os.environ.get("WHATSAPP_NOTIFICATIONS_ENABLED", "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    # Falls back to the shared switch so one flag can turn messaging off.
    return os.environ.get("TWILIO_NOTIFICATIONS_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def has_credentials() -> bool:
    return bool(phone_number_id() and _access_token())


def is_configured() -> bool:
    return bool(has_credentials() and recipient_default())


def _normalise(number: str) -> str:
    """
    Meta wants bare international digits: no `whatsapp:` prefix, no `+`.

    Accepting the Twilio-shaped value too means one MERCHANT_ALERT_NUMBER
    works for whichever provider is live, instead of the merchant keeping two.
    """
    cleaned = number.strip()
    for prefix in ("whatsapp:", "sms:", "tel:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.lstrip("+").replace(" ", "").replace("-", "")


def _mask(value: str) -> Optional[str]:
    if not value:
        return None
    digits = _normalise(value)
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def status() -> dict:
    missing = [
        name
        for name, present in (
            ("WHATSAPP_PHONE_NUMBER_ID", phone_number_id()),
            ("WHATSAPP_ACCESS_TOKEN", _access_token()),
            ("MERCHANT_ALERT_NUMBER", recipient_default()),
        )
        if not present
    ]
    return {
        "provider": "whatsapp_cloud",
        "configured": is_configured(),
        "credentials_present": has_credentials(),
        "enabled": notifications_enabled(),
        "channel": "whatsapp",
        "api_version": api_version(),
        "from": phone_number_id() or None,
        "to": _mask(recipient_default()),
        "missing": missing,
        "note": (
            "Meta WhatsApp Cloud API. Free text only reaches a customer within "
            "24 hours of their last message; outside that, an approved template "
            "is required."
        ),
    }


def _post(payload: dict) -> dict:
    url = f"{GRAPH_ROOT}/{api_version()}/{phone_number_id()}/messages"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {_access_token()}",
                "Content-Type": "application/json",
            },
            timeout=SEND_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise MessagingError(f"Could not reach Meta: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        # Meta's error body names the problem; the fix is added from the table
        # above. The request is not echoed: it carried the access token.
        detail = f"HTTP {response.status_code}"
        try:
            problem = response.json().get("error", {})
            code = problem.get("code")
            sub = (problem.get("error_data") or {}).get("details")
            detail = f"[{code}] {problem.get('message', '')}"
            if sub:
                detail += f" - {sub}"
            if code in ERROR_HINTS:
                detail += f" ({ERROR_HINTS[code]})"
        except ValueError:
            pass
        raise MessagingError(f"Meta rejected the message. {detail}")

    try:
        return response.json()
    except ValueError as exc:
        raise MessagingError("Meta returned a non-JSON response.") from exc


def send(body: str, to: Optional[str] = None) -> dict:
    """Free text. Works only inside the 24-hour window; see the module docstring."""
    if not has_credentials():
        raise MessagingNotConfigured(
            "WhatsApp Cloud is not configured. Need WHATSAPP_PHONE_NUMBER_ID "
            "and WHATSAPP_ACCESS_TOKEN in .env."
        )

    target = _normalise(to or recipient_default())
    if not target:
        raise MessagingNotConfigured("No recipient. Set MERCHANT_ALERT_NUMBER in .env.")

    text = body.strip()[:MAX_BODY_CHARS]
    result = _post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": target,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    })

    messages = result.get("messages") or [{}]
    return {
        "sid": messages[0].get("id"),
        "status": "accepted",
        "channel": "whatsapp",
        "to": _mask(target),
        "body": text,
    }


def send_template(
    name: str,
    variables: Optional[list[str]] = None,
    to: Optional[str] = None,
    language: str = "en_US",
) -> dict:
    """
    An approved template, which reaches a customer at any time.

    This is the only thing that works outside the 24-hour window, so it is what
    a real collections flow would use in production. `hello_world` ships
    pre-approved on every test sender and is useful for proving the pipe.
    """
    if not has_credentials():
        raise MessagingNotConfigured("WhatsApp Cloud is not configured.")

    target = _normalise(to or recipient_default())
    if not target:
        raise MessagingNotConfigured("No recipient. Set MERCHANT_ALERT_NUMBER in .env.")

    template: dict[str, Any] = {"name": name, "language": {"code": language}}
    if variables:
        template["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variables],
        }]

    result = _post({
        "messaging_product": "whatsapp",
        "to": target,
        "type": "template",
        "template": template,
    })

    messages = result.get("messages") or [{}]
    return {
        "sid": messages[0].get("id"),
        "status": "accepted",
        "channel": "whatsapp",
        "to": _mask(target),
        "body": f"[template:{name}]",
    }
