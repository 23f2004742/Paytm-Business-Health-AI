"""
Which pipe an outbound message goes down.

Three providers, one interface. Callers ask this module to send and never learn
whether it went over Telegram, Twilio, or the Meta WhatsApp Cloud API, which is the point:
the choice is an operational one and it changed twice in a week.

    MESSAGING_PROVIDER=whatsapp_cloud   Meta's API      (default when its keys exist)
    MESSAGING_PROVIDER=twilio           Twilio          (SMS or WhatsApp sandbox)
    MESSAGING_PROVIDER=telegram         Telegram Bot API
    MESSAGING_PROVIDER=none             send nothing    (explicitly off)

With nothing set, whichever provider is actually configured wins, preferring
WhatsApp Cloud. That means adding keys to `.env` is enough to switch, and a
half-configured provider never silently becomes the active one.
"""

from __future__ import annotations

import os
from typing import Optional

from .providers import telegram, twilio_sms, whatsapp_cloud
from .providers.base import MessagingError, MessagingNotConfigured

PROVIDERS = {
    "whatsapp_cloud": whatsapp_cloud,
    "twilio": twilio_sms,
    "telegram": telegram,
}


def configured_provider() -> str:
    """What `MESSAGING_PROVIDER` asks for, or the one that is actually ready."""
    requested = (os.environ.get("MESSAGING_PROVIDER") or "").strip().lower()
    if requested in PROVIDERS or requested == "none":
        return requested

    # Selection by readiness rather than by key-presence alone: a provider with
    # credentials but no recipient cannot deliver, so it does not get to win.
    if telegram.is_configured():
        return "telegram"
    if whatsapp_cloud.is_configured():
        return "whatsapp_cloud"
    if twilio_sms.is_configured():
        return "twilio"
    # Nothing complete. Name the one with credentials so status() can explain
    # what is still missing instead of reporting a bare "not configured".
    if telegram.has_credentials():
        return "telegram"
    if whatsapp_cloud.has_credentials():
        return "whatsapp_cloud"
    if twilio_sms.has_credentials():
        return "twilio"
    return "whatsapp_cloud"


def active():
    """The provider module, or None when messaging is switched off."""
    name = configured_provider()
    return None if name == "none" else PROVIDERS[name]


def enabled() -> bool:
    provider = active()
    return bool(provider and provider.notifications_enabled())


def is_configured() -> bool:
    provider = active()
    return bool(provider and provider.is_configured())


def status() -> dict:
    provider = active()
    if provider is None:
        return {
            "provider": "none",
            "configured": False,
            "enabled": False,
            "missing": [],
            "note": "MESSAGING_PROVIDER=none, so no message is ever sent.",
        }
    return {**provider.status(), "selected_by": (
        "MESSAGING_PROVIDER" if os.environ.get("MESSAGING_PROVIDER") else "auto-detected"
    )}


def send(body: str, to: Optional[str] = None) -> dict:
    provider = active()
    if provider is None:
        raise MessagingNotConfigured("Messaging is switched off (MESSAGING_PROVIDER=none).")
    return provider.send(body, to=to)


__all__ = [
    "MessagingError",
    "MessagingNotConfigured",
    "active",
    "configured_provider",
    "enabled",
    "is_configured",
    "send",
    "status",
]
