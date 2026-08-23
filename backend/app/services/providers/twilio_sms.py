"""
Twilio provider: outbound SMS / WhatsApp for merchant alerts.

Why a merchant action sends a message at all
------------------------------------------------------------------------------
The shop floor tells us a product is missing before the payments data ever
will. A restock alert that only lands in a dashboard is a dashboard the
merchant is not looking at while standing behind a counter. A text reaches
them there.

------------------------------------------------------------------------------
Credentials
------------------------------------------------------------------------------
NO CREDENTIAL IS EMBEDDED IN THIS FILE. Everything is read from the
environment at call time, and the secret is:

  * never sent to the frontend
  * never sent to the Raspberry Pi
  * never written to a log or an error message
  * never committed (`.env` is gitignored; `.env.example` holds placeholders)

Authentication is a Twilio API Key, not the account auth token. The key SID
(SK...) and its secret are the HTTP basic auth pair, while the REST path still
needs the Account SID (AC...). That is three values, not two, and a missing
Account SID is the usual reason an otherwise valid API Key 404s.

------------------------------------------------------------------------------
No `twilio` SDK on purpose
------------------------------------------------------------------------------
httpx is already a dependency for the Sarvam and OpenAI paths, and this is one
form-encoded POST. Same reasoning as the Ollama provider: keep the package
count down and keep every provider the same shape.

Sending is OFF unless TWILIO_NOTIFICATIONS_ENABLED is true, so a demo can
never silently spend credit or text a real phone. Every failure returns a
result dict or raises a typed error, so a merchant action still succeeds even
when the message does not.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .base import MessagingError, MessagingNotConfigured

API_ROOT = "https://api.twilio.com/2010-04-01"
SEND_TIMEOUT = 20.0

# Twilio bills a long SMS as multiple segments. Merchant alerts are short by
# design, but a runaway product name should not quietly cost five segments.
MAX_BODY_CHARS = 320

WHATSAPP_PREFIX = "whatsapp:"


class TwilioNotConfigured(MessagingNotConfigured):
    """Credentials or routing numbers missing. Callers carry on without a message."""


class TwilioError(MessagingError):
    """The API was reached but did not accept the message."""


def _clean(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    # Treat a copied placeholder as absent, so a half-filled .env does not look
    # configured and then fail confusingly on the first real send.
    if value.upper().startswith("YOUR_"):
        return ""
    return value


def account_sid() -> str:
    return _clean("TWILIO_ACCOUNT_SID")


def _api_key_sid() -> str:
    return _clean("TWILIO_API_KEY_SID")


def _api_key_secret() -> str:
    return _clean("TWILIO_API_KEY_SECRET")


def _auth_token() -> str:
    return _clean("TWILIO_AUTH_TOKEN")


def auth_pair() -> Optional[tuple[str, str]]:
    """
    The HTTP basic auth pair, from whichever credential style is configured.

    Twilio accepts two, and a fresh account starts with the simpler one:

      Account SID + Auth Token   copy-paste straight off the Console home page
      API Key SID + Secret       revocable without rotating the account itself

    The API key wins when both are present, because an account that has gone
    to the trouble of making one is the account that meant to use it.
    """
    if _api_key_sid() and _api_key_secret():
        return _api_key_sid(), _api_key_secret()
    if account_sid() and _auth_token():
        return account_sid(), _auth_token()
    return None


def from_number() -> str:
    return _clean("TWILIO_FROM_NUMBER")


def merchant_number() -> str:
    return _clean("MERCHANT_ALERT_NUMBER")


def notifications_enabled() -> bool:
    value = os.environ.get("TWILIO_NOTIFICATIONS_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def has_credentials() -> bool:
    """Auth is complete. Says nothing about whether a message can be addressed."""
    return bool(account_sid() and auth_pair())


def is_configured() -> bool:
    """Everything needed to actually deliver one message."""
    return bool(has_credentials() and from_number() and merchant_number())


def _mask(value: str) -> Optional[str]:
    """Enough to identify a number in a status payload, not enough to dial it."""
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def status() -> dict:
    """Safe to expose: reports what is missing, never a secret."""
    missing = [
        name
        for name, present in (
            ("TWILIO_ACCOUNT_SID", account_sid()),
            # Either credential style satisfies this row.
            ("TWILIO_AUTH_TOKEN or TWILIO_API_KEY_SID/SECRET", auth_pair() or ""),
            ("TWILIO_FROM_NUMBER", from_number()),
            ("MERCHANT_ALERT_NUMBER", merchant_number()),
        )
        if not present
    ]
    return {
        "provider": "twilio",
        "configured": is_configured(),
        "credentials_present": has_credentials(),
        "auth_style": (
            "api_key" if (_api_key_sid() and _api_key_secret())
            else "auth_token" if _auth_token() else None
        ),
        "enabled": notifications_enabled(),
        "channel": "whatsapp" if from_number().startswith(WHATSAPP_PREFIX) else "sms",
        "from": _mask(from_number()),
        "to": _mask(merchant_number()),
        "missing": missing,
        "note": (
            "Set the missing variables in .env and TWILIO_NOTIFICATIONS_ENABLED=true "
            "to send. Merchant actions succeed either way: a message is a "
            "notification, never a precondition."
        ),
    }


def send(body: str, to: Optional[str] = None) -> dict:
    """
    Send one message. Raises TwilioNotConfigured when it cannot be addressed,
    so the caller can choose to carry on silently.
    """
    credentials = auth_pair()
    if not account_sid() or credentials is None:
        raise TwilioNotConfigured(
            "Twilio credentials are incomplete. Need TWILIO_ACCOUNT_SID plus "
            "either TWILIO_AUTH_TOKEN, or TWILIO_API_KEY_SID with "
            "TWILIO_API_KEY_SECRET."
        )

    sender = from_number()
    if not sender:
        raise TwilioNotConfigured(
            "TWILIO_FROM_NUMBER is not set. Buy a number, or use the WhatsApp "
            "sandbox sender `whatsapp:+14155238886`."
        )

    recipient = (to or merchant_number()).strip()
    if not recipient:
        raise TwilioNotConfigured("No recipient. Set MERCHANT_ALERT_NUMBER in .env.")

    # WhatsApp is addressed on both ends or neither. Mixing them returns a 400
    # that reads like a credentials problem and wastes an afternoon.
    if sender.startswith(WHATSAPP_PREFIX) and not recipient.startswith(WHATSAPP_PREFIX):
        recipient = f"{WHATSAPP_PREFIX}{recipient}"

    text = body.strip()[:MAX_BODY_CHARS]
    payload: dict[str, Any] = {"To": recipient, "From": sender, "Body": text}

    try:
        response = httpx.post(
            f"{API_ROOT}/Accounts/{account_sid()}/Messages.json",
            data=payload,
            auth=credentials,
            timeout=SEND_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise TwilioError(f"Could not reach Twilio: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise TwilioError("Twilio rejected the API key (401/403).")

    if response.status_code >= 400:
        # Twilio's own error code is the useful part and carries no secret. The
        # request is deliberately not echoed: it held the auth pair.
        detail = ""
        try:
            problem = response.json()
            code = problem.get("code")
            detail = f" [{code}] {problem.get('message', '')}".rstrip()
            # The codes worth translating. Twilio's own text names the
            # problem but not the fix, and every one of these has exactly one.
            hints = {
                21608: "a trial account can only message verified numbers",
                21606: "that From number cannot send to this destination",
                21610: "that number replied STOP; it must opt back in",
                21614: "not a valid mobile number",
                63007: (
                    "that phone has not joined the WhatsApp sandbox. Send "
                    "`join <your-code>` from it to +1 415 523 8886, the code "
                    "is in Console > Messaging > Try it out"
                ),
                21654: (
                    "no open WhatsApp session. A freeform message is only "
                    "allowed within 24 hours of that phone messaging you, so "
                    "WhatsApp `join <your-code>` to +1 415 523 8886 first "
                    "(code: Console > Messaging > Try it out > Send a WhatsApp "
                    "message). Outside that window only an approved template "
                    "can be sent, which needs a ContentSid"
                ),
                63016: (
                    "outside the 24-hour WhatsApp window, so only an approved "
                    "template can be sent. Message the sandbox from that phone "
                    "to reopen the window"
                ),
                63018: "WhatsApp rate limit reached",
                21910: "From and To must be on the same channel (both whatsapp:, or neither)",
            }
            if code in hints:
                detail += f" ({hints[code]})"
        except ValueError:
            pass
        raise TwilioError(f"Twilio returned {response.status_code}.{detail}")

    try:
        result = response.json()
    except ValueError as exc:
        raise TwilioError("Twilio returned a non-JSON response.") from exc

    return {
        "sid": result.get("sid"),
        "status": result.get("status"),
        "channel": "whatsapp" if sender.startswith(WHATSAPP_PREFIX) else "sms",
        "to": _mask(recipient),
        "body": text,
    }
