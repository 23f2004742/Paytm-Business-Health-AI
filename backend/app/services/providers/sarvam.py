"""
Sarvam AI provider: speech-to-text and chat, for Indian languages.

Sarvam is the right shape of tool for this product. The audio is Hinglish
spoken across a counter, and a model built for Indian languages will beat a
general one at exactly the thing that matters here.

------------------------------------------------------------------------------
Credentials
------------------------------------------------------------------------------
NO KEY IS EMBEDDED IN THIS FILE, and none should ever be. The key is read
from SARVAM_API_KEY at call time and is:

  * never sent to the frontend
  * never sent to the Raspberry Pi
  * never written to a log or an error message
  * never committed (`.env` is gitignored; `.env.example` holds placeholders)

The Pi posts raw audio to this backend, and the backend alone talks to Sarvam.
That is the reason the Pi never needs a key: the trust boundary is here.

------------------------------------------------------------------------------
Model and endpoint names are configurable on purpose
------------------------------------------------------------------------------
Endpoints and model identifiers are read from environment variables with
documented defaults rather than hard-coded. Vendor model names change, and a
hackathon project that pins one silently breaks months later. If a default is
wrong for your account, set SARVAM_STT_MODEL / SARVAM_CHAT_MODEL and nothing
else needs to change.

Every failure returns None or raises a typed error, so a missing key, an
expired key or an outage degrades the product to the deterministic path
instead of breaking it.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

# Documented defaults. Override with environment variables if your account
# exposes different names.
DEFAULT_BASE_URL = "https://api.sarvam.ai"
DEFAULT_STT_MODEL = "saarika:v2.5"
DEFAULT_CHAT_MODEL = "sarvam-105b-conversations"
DEFAULT_TTS_MODEL = "bulbul:v3"
DEFAULT_TTS_SPEAKER = "shubh"

STT_TIMEOUT = 60.0
CHAT_TIMEOUT = 45.0
TTS_TIMEOUT = 60.0

# Sarvam authenticates with this header rather than a bearer token.
AUTH_HEADER = "api-subscription-key"


class SarvamNotConfigured(RuntimeError):
    """No API key present. Callers fall back rather than fail."""


class SarvamError(RuntimeError):
    """The API was reached but did not return a usable result."""


def _api_key() -> Optional[str]:
    key = (os.environ.get("SARVAM_API_KEY") or "").strip()
    # Treat the placeholder as absent so a copied .env.example does not look
    # configured and then fail confusingly on the first real call.
    if not key or key.upper().startswith("YOUR_"):
        return None
    return key


def base_url() -> str:
    return os.environ.get("SARVAM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def stt_model() -> str:
    return os.environ.get("SARVAM_STT_MODEL", DEFAULT_STT_MODEL)


def chat_model() -> str:
    return os.environ.get("SARVAM_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def tts_model() -> str:
    return os.environ.get("SARVAM_TTS_MODEL", DEFAULT_TTS_MODEL)


def tts_speaker() -> str:
    return os.environ.get("SARVAM_TTS_SPEAKER", DEFAULT_TTS_SPEAKER)


def tts_pace() -> float:
    """Bulbul v3 accepts a pace from 0.5 to 2.0."""
    try:
        value = float(os.environ.get("SARVAM_TTS_PACE", "1.0"))
    except ValueError:
        return 1.0
    return min(2.0, max(0.5, value))


def language_code() -> str:
    """`unknown` lets Sarvam auto-detect, which suits mixed Hinglish speech."""
    return os.environ.get("SARVAM_LANGUAGE_CODE", "unknown")


def is_configured() -> bool:
    return _api_key() is not None


def status() -> dict:
    """Safe to expose: reports whether a key exists, never what it is."""
    return {
        "configured": is_configured(),
        "base_url": base_url(),
        "stt_model": stt_model() if is_configured() else None,
        "chat_model": chat_model() if is_configured() else None,
        "tts_model": tts_model() if is_configured() else None,
        "language_code": language_code(),
        "note": (
            "Set SARVAM_API_KEY in backend/.env to enable. Without it the "
            "product runs on the deterministic engine and any configured "
            "local transcription."
        ),
    }


# ----------------------------------------------------------------- speech

def transcribe(audio_path: Path) -> dict:
    """
    Send one audio file to Sarvam speech-to-text.

    Returns {"text", "language", "raw"}. Raises SarvamNotConfigured when no
    key is set, so the caller can choose another provider.
    """
    key = _api_key()
    if not key:
        raise SarvamNotConfigured(
            "SARVAM_API_KEY is not set. Add it to backend/.env, or set "
            "TRANSCRIPTION_PROVIDER to `whisper` or `mock`."
        )

    url = f"{base_url()}/speech-to-text"

    try:
        with open(audio_path, "rb") as handle:
            files = {"file": (audio_path.name, handle, "audio/wav")}
            data: dict[str, Any] = {"model": stt_model()}
            code = language_code()
            if code and code != "unknown":
                data["language_code"] = code

            response = httpx.post(
                url,
                headers={AUTH_HEADER: key},
                files=files,
                data=data,
                timeout=STT_TIMEOUT,
            )
    except httpx.HTTPError as exc:
        raise SarvamError(f"Could not reach Sarvam: {type(exc).__name__}") from exc

    if response.status_code == 401 or response.status_code == 403:
        raise SarvamError("Sarvam rejected the API key (401/403).")
    if response.status_code >= 400:
        # Deliberately does not echo the request: it contained the audio, and
        # the headers contained the key.
        raise SarvamError(f"Sarvam speech-to-text returned {response.status_code}.")

    try:
        body = response.json()
    except ValueError as exc:
        raise SarvamError("Sarvam returned a non-JSON response.") from exc

    # Field naming has varied across Sarvam API versions, so accept the
    # documented key and the obvious alternatives rather than breaking.
    text = (
        body.get("transcript")
        or body.get("text")
        or body.get("transcription")
        or ""
    ).strip()

    return {
        "text": text,
        "language": body.get("language_code") or body.get("language"),
        "raw": body,
    }


# ------------------------------------------------------------------- chat

def chat(
    system_prompt: str,
    user_prompt: str,
    *,
    want_json: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> str:
    """
    Sarvam chat completions, OpenAI-compatible shape.

    Used only to phrase explanations from numbers computed elsewhere. It is
    never asked to calculate anything.
    """
    key = _api_key()
    if not key:
        raise SarvamNotConfigured("SARVAM_API_KEY is not set.")

    payload: dict[str, Any] = {
        "model": chat_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0 if want_json else temperature,
        "max_tokens": max_tokens,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = httpx.post(
            f"{base_url()}/v1/chat/completions",
            headers={
                AUTH_HEADER: key,
                "Authorization": f"Bearer {key}",   # accepted by the OpenAI-compatible route
                "content-type": "application/json",
            },
            json=payload,
            timeout=CHAT_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise SarvamError(f"Could not reach Sarvam: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise SarvamError("Sarvam rejected the API key (401/403).")
    if response.status_code >= 400:
        raise SarvamError(f"Sarvam chat returned {response.status_code}.")

    try:
        body = response.json()
        message = body["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as exc:
        raise SarvamError("Unexpected response shape from Sarvam chat.") from exc

    # Sarvam's reasoning models (sarvam-105b) fill `reasoning_content` first
    # and only then `content`. When max_tokens runs out mid-thought `content`
    # comes back as null rather than absent, and a bare .strip() would raise
    # AttributeError deep inside a request handler instead of degrading.
    text = (message.get("content") or "").strip()

    if not text:
        if message.get("reasoning_content"):
            raise SarvamError(
                "Sarvam returned reasoning but no answer: max_tokens ran out "
                "while the model was still thinking. Raise max_tokens, or set "
                "SARVAM_CHAT_MODEL=sarvam-105b-conversations."
            )
        raise SarvamError("Sarvam returned an empty completion.")
    return text


def extract_json(system_prompt: str, user_prompt: str) -> Optional[dict]:
    """JSON-mode chat. Returns None on any failure so callers can fall back."""
    try:
        raw = chat(system_prompt, user_prompt, want_json=True, max_tokens=300)
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (SarvamNotConfigured, SarvamError, ValueError):
        return None


# ----------------------------------------------------------- text to speech

_CODEC_MIME_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
}


def synthesise_speech(
    text: str,
    *,
    language_code: str,
    output_audio_codec: str = "mp3",
) -> dict:
    """Generate speech with Bulbul and return decoded audio bytes.

    Sarvam's REST endpoint returns base64 strings rather than a binary audio
    response. Keeping decoding here prevents delivery channels from needing to
    know the vendor response shape.
    """
    key = _api_key()
    if not key:
        raise SarvamNotConfigured("SARVAM_API_KEY is not set.")

    clean_text = text.strip()[:2500]
    if not clean_text:
        raise SarvamError("Cannot synthesise an empty reply.")

    codec = output_audio_codec.lower().strip() or "mp3"
    payload = {
        "text": clean_text,
        "language_code": language_code,
        "model": tts_model(),
        "speaker": tts_speaker(),
        "pace": tts_pace(),
        "output_audio_codec": codec,
    }
    try:
        response = httpx.post(
            f"{base_url()}/text-to-speech",
            headers={AUTH_HEADER: key, "content-type": "application/json"},
            json=payload,
            timeout=TTS_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise SarvamError(f"Could not reach Sarvam TTS: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise SarvamError("Sarvam rejected the API key (401/403).")
    if response.status_code >= 400:
        raise SarvamError(f"Sarvam text-to-speech returned {response.status_code}.")

    try:
        body = response.json()
        encoded_audio = "".join(str(part) for part in (body.get("audios") or []))
        if encoded_audio.startswith("data:"):
            encoded_audio = encoded_audio.split(",", 1)[-1]
        audio = base64.b64decode(encoded_audio)
    except (ValueError, TypeError) as exc:
        raise SarvamError("Sarvam returned invalid text-to-speech audio.") from exc

    if not audio:
        raise SarvamError("Sarvam returned empty text-to-speech audio.")

    return {
        "audio": audio,
        "mime_type": _CODEC_MIME_TYPES.get(codec, "application/octet-stream"),
        "extension": "ogg" if codec == "opus" else codec,
        "request_id": body.get("request_id"),
        "language_code": language_code,
    }
