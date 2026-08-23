"""
Shared contract for outbound messaging providers.

Two providers exist and a third is plausible, so the callers should not know
which one is live. Everything above this layer catches these two exceptions and
reads the same result dict, whether the message went out over Twilio or the
Meta WhatsApp Cloud API.

The distinction the whole product leans on is between the two errors:

    MessagingNotConfigured   we should not send   (no key, no number, disabled)
    MessagingError           we tried and failed  (rejected, offline, throttled)

A merchant action degrades silently on the first and reports loudly on the
second, because "nothing was set up" and "your customer did not get the
message" need completely different responses.
"""

from __future__ import annotations


class MessagingNotConfigured(RuntimeError):
    """Missing credentials or routing. Callers carry on without a message."""


class MessagingError(RuntimeError):
    """The provider was reached but did not accept the message."""
