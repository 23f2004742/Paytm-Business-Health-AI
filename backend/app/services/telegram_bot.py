"""Inbound Telegram lending assistant backed by Sarvam AI.

The notification provider sends alerts; this module is the other half of a
bot: it receives a Telegram update, asks Sarvam for a short reply in the
user's language, then sends text and (optionally) spoken audio back to the
same chat.  It supports either local long polling or a production webhook.
"""

from __future__ import annotations

import hmac
import os
import threading
from typing import Any, Optional

from .providers import sarvam, telegram
from .providers.base import MessagingError, MessagingNotConfigured

BOT_SYSTEM_PROMPT = """You are Sujit Shopwala Lending Assistant.
Help users understand sample loan repayments, due dates, and payment links.
Reply in the same language and native script as the user's last message. For
Hindi or Hinglish, use simple Hindi in Devanagari. Keep answers to two short,
clear sentences unless the user explicitly asks for more detail.

Never claim that a payment was received, a loan was approved, or that a due
amount is verified unless the user supplied it in this conversation. Never
ask for an OTP, PIN, password, card number, Aadhaar number, or bank login.
If the user asks for a payment link, explain that the configured link is a
demo unless it explicitly says otherwise. Do not give legal, investment, or
credit-approval advice."""

_TTS_LANGUAGE_CODES = {
    "hi-IN", "en-IN", "bn-IN", "ta-IN", "te-IN", "gu-IN", "kn-IN",
    "ml-IN", "mr-IN", "pa-IN", "od-IN",
}
BOT_JSON_SYSTEM_PROMPT = (
    BOT_SYSTEM_PROMPT
    + "\n\nReturn JSON only with exactly two keys: `reply` (the user-facing "
    "answer) and `language_code` (the BCP-47 language for that reply). Use a "
    "Bulbul-supported language code when possible: "
    + ", ".join(sorted(_TTS_LANGUAGE_CODES))
    + ". Use an empty language_code only when none applies."
)

WELCOME = (
    "नमस्ते! मैं Sujit Shopwala Lending Assistant हूँ। आप हिंदी, Hinglish, "
    "English और अन्य भारतीय भाषाओं में loan या repayment के बारे में पूछ सकते हैं।"
)
HELP = (
    "अपना सवाल लिखें, जैसे: ‘मेरी EMI कब देनी है?’ या ‘payment link भेजो’। "
    "मैं उसी भाषा में छोटा जवाब दूँगा और समर्थित भाषाओं में आवाज़ भी भेजूँगा।"
)
UNSUPPORTED = (
    "अभी मैं text messages का जवाब दे सकता हूँ। कृपया अपना loan या payment "
    "का सवाल लिखकर भेजें।"
)
FALLBACK = (
    "माफ़ कीजिए, AI reply अभी उपलब्ध नहीं है। कृपया थोड़ी देर बाद फिर कोशिश करें।"
)

_VALID_MODES = {"off", "polling", "webhook"}
_poll_lock = threading.Lock()
_poll_thread: Optional[threading.Thread] = None
_poll_stop: Optional[threading.Event] = None


def _enabled(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def mode() -> str:
    selected = (os.environ.get("TELEGRAM_BOT_MODE") or "off").strip().lower()
    return selected if selected in _VALID_MODES else "off"


def voice_replies_enabled() -> bool:
    return _enabled(os.environ.get("TELEGRAM_BOT_VOICE_REPLIES"))


def webhook_secret() -> str:
    return (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()


def webhook_secret_matches(value: Optional[str]) -> bool:
    expected = webhook_secret()
    return bool(expected and value and hmac.compare_digest(expected, value))


def allowed_chat_ids() -> set[str]:
    """Only the configured owner chat may use the lending bot by default."""
    configured = (os.environ.get("TELEGRAM_BOT_ALLOWED_CHAT_IDS") or "").strip()
    values = configured.split(",") if configured else [telegram.recipient_default()]
    return {value.strip() for value in values if value and value.strip()}


def status() -> dict:
    thread_alive = bool(_poll_thread and _poll_thread.is_alive())
    return {
        "mode": mode(),
        "configured": telegram.has_credentials(),
        "allowed_chat_count": len(allowed_chat_ids()),
        "voice_replies": voice_replies_enabled(),
        "sarvam_configured": sarvam.is_configured(),
        "poller_running": thread_alive,
        "webhook_secret_configured": bool(webhook_secret()),
        "note": (
            "Use one delivery mode only: local polling or a public HTTPS webhook. "
            "Only allowed chat IDs receive replies."
        ),
    }


def _payment_link() -> str:
    return (
        os.environ.get("LENDING_DEMO_PAYMENT_LINK")
        or "https://example.com/?payment=DEMO-LOAN-001"
    ).strip()


def _command(text: str) -> str:
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    return first.split("@", 1)[0].lower()


def _answer(text: str) -> tuple[str, Optional[str]]:
    command = _command(text)
    if command == "/start":
        return WELCOME, "hi-IN"
    if command in {"/help", "/commands"}:
        return HELP, "hi-IN"
    if command in {"/payment", "/pay", "/link"}:
        return (
            "यह sample payment link है: "
            f"{_payment_link()}\n\n"
            "यह केवल demo है; इससे कोई असली payment collect नहीं होगी।"
        ), "hi-IN"

    if not sarvam.is_configured():
        return FALLBACK, "hi-IN"

    try:
        structured = sarvam.extract_json(
            BOT_JSON_SYSTEM_PROMPT,
            f"User message:\n{text.strip()[:2000]}",
        )
        if structured:
            reply = str(structured.get("reply") or "").strip()
            language = str(structured.get("language_code") or "").strip()
            if reply:
                return reply[:2500], language if language in _TTS_LANGUAGE_CODES else None

        # A malformed structured response should not leave the user silent.
        return sarvam.chat(
            BOT_SYSTEM_PROMPT,
            f"User message:\n{text.strip()[:2000]}",
            temperature=0.25,
            max_tokens=350,
        ), None
    except (sarvam.SarvamError, sarvam.SarvamNotConfigured):
        return FALLBACK, "hi-IN"


_SCRIPT_TTS_LANGUAGES = (
    ((0x0900, 0x097F), "hi-IN"),  # Devanagari: Hindi / Hinglish default
    ((0x0980, 0x09FF), "bn-IN"),
    ((0x0A00, 0x0A7F), "pa-IN"),
    ((0x0A80, 0x0AFF), "gu-IN"),
    ((0x0B00, 0x0B7F), "od-IN"),
    ((0x0B80, 0x0BFF), "ta-IN"),
    ((0x0C00, 0x0C7F), "te-IN"),
    ((0x0C80, 0x0CFF), "kn-IN"),
    ((0x0D00, 0x0D7F), "ml-IN"),
)


def tts_language_code(text: str) -> Optional[str]:
    """Map the reply script to one of Bulbul's supported TTS languages."""
    counts: list[tuple[int, str]] = []
    for (start, end), code in _SCRIPT_TTS_LANGUAGES:
        counts.append((sum(start <= ord(char) <= end for char in text), code))
    best_count, best_code = max(counts, default=(0, ""))
    if best_count:
        return best_code
    if any(char.isascii() and char.isalpha() for char in text):
        return "en-IN"
    return None


def _send_reply(
    chat_id: str, reply: str, language_code: Optional[str] = None
) -> dict:
    text_result = telegram.send(reply, to=chat_id)
    voice_sent = False
    voice_error: Optional[str] = None

    if voice_replies_enabled() and sarvam.is_configured():
        language = language_code or tts_language_code(reply)
        if language:
            try:
                voice = sarvam.synthesise_speech(
                    reply,
                    language_code=language,
                    output_audio_codec="mp3",
                )
                telegram.send_audio(
                    voice["audio"],
                    extension=voice["extension"],
                    mime_type=voice["mime_type"],
                    to=chat_id,
                )
                voice_sent = True
            except (sarvam.SarvamError, sarvam.SarvamNotConfigured, MessagingError) as exc:
                # A spoken reply must never suppress the useful text reply.
                voice_error = type(exc).__name__

    return {
        "sent": True,
        "chat_id": telegram.mask_chat_id(chat_id),  # safe status value only
        "message_id": text_result.get("sid"),
        "voice_sent": voice_sent,
        "voice_error": voice_error,
    }


def handle_update(update: dict[str, Any]) -> dict:
    """Handle exactly one Telegram update; safe to call from webhook or poller."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    sender = message.get("from") or {}

    if not chat_id or sender.get("is_bot"):
        return {"handled": False, "reason": "No eligible message."}
    if chat_id not in allowed_chat_ids():
        return {"handled": False, "reason": "Chat is not allowed."}

    text = (message.get("text") or "").strip()
    if not text:
        result = _send_reply(chat_id, UNSUPPORTED, "hi-IN")
        return {"handled": True, "kind": "non_text", **result}

    reply, language_code = _answer(text)
    result = _send_reply(chat_id, reply, language_code)
    return {"handled": True, "kind": "text", **result}


def poll_forever(stop_event: Optional[threading.Event] = None, *, once: bool = False) -> int:
    """Run Telegram long polling. Return the number of received updates."""
    stop = stop_event or threading.Event()
    offset: Optional[int] = None
    handled = 0

    while not stop.is_set():
        try:
            updates = telegram.get_updates(offset=offset)
        except (MessagingError, MessagingNotConfigured):
            if once:
                return handled
            stop.wait(5)
            continue

        for update in updates:
            update_id = update.get("update_id")
            try:
                handle_update(update)
            finally:
                if isinstance(update_id, int):
                    offset = update_id + 1
                handled += 1
        if once:
            return handled
    return handled


def start_background_poller() -> bool:
    """Start one daemon polling thread when the FastAPI app runs locally."""
    global _poll_stop, _poll_thread
    with _poll_lock:
        if _poll_thread and _poll_thread.is_alive():
            return False
        _poll_stop = threading.Event()
        _poll_thread = threading.Thread(
            target=poll_forever,
            args=(_poll_stop,),
            name="telegram-bot-poller",
            daemon=True,
        )
        _poll_thread.start()
        return True


def stop_background_poller() -> None:
    if _poll_stop:
        _poll_stop.set()
