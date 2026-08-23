"""
Small TTS boundary; audio playback stays with the browser or Pi client.

Two ways a reply becomes sound:

  browser   the client speaks it with the Web Speech API. Free, offline, and
            it sounds like a satnav reading Hinglish, because the voice is
            tuned for English.
  sarvam    Bulbul returns real audio for the reply. Costs a fraction of a
            paisa per line and actually sounds like someone in the shop.

`auto` (the default) picks sarvam when a key is configured and falls back to
the browser when it is not, so a clone of this repo with no credentials still
talks back.

Audio is returned as a base64 data URI rather than a file the client fetches
separately. A spoken reply is one or two seconds -- tens of kilobytes -- and
inlining it means the answer and its audio arrive together, with no second
round trip and no temp file to clean up.
"""

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from typing import Optional

# Bulbul needs a language to pick a voice. The replies this product generates
# are romanised Hinglish, which the Hindi voices read correctly -- including
# the English words inside them.
DEFAULT_TTS_LANGUAGE = "hi-IN"

# What the merchant spoke, mapped to the voice that should answer. Sarvam
# spells Odia `od-IN`, not the ISO `or-IN` that Whisper reports.
_LANGUAGE_CODES = {
    "hi": "hi-IN", "en": "en-IN", "mr": "mr-IN", "or": "od-IN", "od": "od-IN",
    "bn": "bn-IN", "gu": "gu-IN", "kn": "kn-IN", "ml": "ml-IN", "pa": "pa-IN",
    "ta": "ta-IN", "te": "te-IN",
}


def voice_language(detected: Optional[str]) -> str:
    """
    Which Bulbul voice answers a merchant who spoke `detected`.

    Falls back to Hindi, because the reply text is Hinglish either way and a
    Hindi voice reading it is always intelligible. Answering an Odia speaker in
    an Odia voice is better; answering them in no voice at all is worse.
    """
    if not detected:
        return DEFAULT_TTS_LANGUAGE
    key = detected.strip().lower().replace("_", "-").split("-")[0]
    return _LANGUAGE_CODES.get(key, DEFAULT_TTS_LANGUAGE)


class BaseTTSProvider(ABC):
    @abstractmethod
    def synthesise(self, text: str, *, language_code: str) -> dict:
        """Return provider metadata or an audio reference."""


class BrowserTTSProvider(BaseTTSProvider):
    def synthesise(self, text: str, *, language_code: str) -> dict:
        return {
            "available": True,
            "mode": "browser",
            "text": text,
            "language_code": language_code,
        }


class SarvamTTSProvider(BaseTTSProvider):
    def synthesise(self, text: str, *, language_code: str) -> dict:
        from .providers import sarvam

        try:
            result = sarvam.synthesise_speech(text, language_code=language_code)
        except (sarvam.SarvamNotConfigured, sarvam.SarvamError) as exc:
            # A TTS outage must never cost the merchant the action they just
            # took, so this degrades to the browser voice rather than raising.
            fallback = BrowserTTSProvider().synthesise(text, language_code=language_code)
            fallback["reason"] = f"Sarvam TTS unavailable: {exc}"
            fallback["attempted"] = "sarvam"
            return fallback

        encoded = base64.b64encode(result["audio"]).decode("ascii")
        return {
            "available": True,
            "mode": "sarvam",
            "text": text,
            "language_code": result["language_code"],
            "mime_type": result["mime_type"],
            "audio_data_uri": f"data:{result['mime_type']};base64,{encoded}",
            "audio_bytes": len(result["audio"]),
            "request_id": result.get("request_id"),
        }


class MockTTSProvider(BaseTTSProvider):
    def synthesise(self, text: str, *, language_code: str) -> dict:
        return {
            "available": False,
            "mode": "mock",
            "text": text,
            "language_code": language_code,
        }


def configured_provider() -> str:
    return os.environ.get("TTS_PROVIDER", "auto").strip().lower()


def active_provider() -> str:
    """Resolved rather than assumed, so a missing key degrades predictably."""
    from .providers import sarvam

    requested = configured_provider()
    if requested == "sarvam":
        return "sarvam" if sarvam.is_configured() else "browser"
    if requested in {"browser", "mock"}:
        return requested
    return "sarvam" if sarvam.is_configured() else "browser"


def provider() -> BaseTTSProvider:
    return {
        "sarvam": SarvamTTSProvider,
        "mock": MockTTSProvider,
        "browser": BrowserTTSProvider,
    }[active_provider()]()


def speak(text: str, *, language: Optional[str] = None) -> dict:
    """
    One reply, spoken.

    `language` is whatever the recogniser detected, not a setting: the merchant
    never picks a language, so neither does this.
    """
    code = voice_language(language)
    result = provider().synthesise(text, language_code=code)
    result["output_mode"] = os.environ.get("VOICE_OUTPUT_MODE", "browser")
    return result


def status() -> dict:
    from .providers import sarvam

    return {
        "configured": configured_provider(),
        "active": active_provider(),
        "sarvam_configured": sarvam.is_configured(),
        "default_language": DEFAULT_TTS_LANGUAGE,
    }
