"""
Speech to text.

faster-whisper is **optional**. It pulls ctranslate2, onnxruntime and av,
roughly 250 MB, which is more than a hackathon backend should demand of
anyone cloning the repo. So it is lazy-imported and never listed in
requirements.txt.

Three ways audio becomes text, in the order they are tried:

  1. The client already transcribed it and sent a `transcript` field.
     This is Mode A: a laptop or a Pi 5 running Whisper locally.
  2. The backend transcribes with faster-whisper, if it is installed.
     This is Mode B: the Pi ships a WAV and stays a cheap edge sensor.
  3. Neither is available, and the request is rejected with an explanation
     rather than a stack trace.

The model config is carried over from the original project: `small` on CPU
with int8, which avoids the missing-CUDA-DLL failure on Windows, plus the
VAD filter and the Hindi/English language gate that stops Whisper
hallucinating Tamil or Korean out of shop-floor background noise.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

DEFAULT_MODEL_SIZE = "small"

# Whisper guesses a language per chunk, and shop-floor background noise makes
# it guess confidently and wrongly. The gate is here to drop Korean and Welsh,
# NOT to pick a language for the merchant: a kirana in Cuttack runs in Odia and
# one in Pune runs in Marathi, and rejecting either was the bug this list used
# to cause. Every language Sarvam Saarika transcribes is allowed through.
ALLOWED_LANGUAGES = {
    "hi",   # Hindi
    "en",   # English
    "mr",   # Marathi
    "or",   # Odia -- Whisper's ISO 639-1 code; Sarvam calls it `od-IN`
    "bn",   # Bengali
    "gu",   # Gujarati
    "kn",   # Kannada
    "ml",   # Malayalam
    "pa",   # Punjabi
    "ta",   # Tamil
    "te",   # Telugu
    "ur",   # Urdu
    "as",   # Assamese
    "ne",   # Nepali -- close enough to Hindi that Whisper often lands here
    "sa",   # Sanskrit -- ditto, a common misfire on clean Hindi
}

# Whisper's classic silence hallucinations. Dropping them stops empty audio
# from becoming a confident-looking event.
_HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "you", "bye.", "okay.",
    "a conversation in hindi and english",
    "subtitles by the amara.org community",
}

_model = None
_model_lock = threading.Lock()
_load_error: Optional[str] = None


def model_size() -> str:
    return os.environ.get("WHISPER_MODEL_SIZE", DEFAULT_MODEL_SIZE)


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model():
    """Loaded once, on first use. Never at import: it costs seconds."""
    global _model, _load_error

    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                model_size(),
                device=os.environ.get("WHISPER_DEVICE", "cpu"),
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            )
            _load_error = None
        except Exception as exc:  # noqa: BLE001
            _load_error = f"{type(exc).__name__}: {exc}"
            raise
    return _model


class TranscriptionUnavailable(RuntimeError):
    """Raised when audio arrives and there is no way to turn it into text."""


# --------------------------------------------------------------- providers
#
# TRANSCRIPTION_PROVIDER selects the engine:
#
#   sarvam    Sarvam AI speech-to-text, best for Hinglish shop audio
#   whisper   local faster-whisper (also accepted as `existing`)
#   mock      deterministic canned transcripts; no audio is decoded
#   auto      Sarvam if a key is set, else whisper if installed, else mock
#             when DEMO_MODE is on                              (default)

VALID_TRANSCRIPTION_PROVIDERS = ("auto", "sarvam", "whisper", "existing", "mock")

# Used only by the mock provider. Cycles so repeated calls differ, which makes
# a mic-free demo look like a shop rather than a stuck record.
MOCK_TRANSCRIPTS = [
    "Bhaiya Maggi hai? Nahi beta khatam ho gaya",
    "Ek Maggi dena. Haan, 20 rupaye. UPI kar diya",
    "Do packet Parle-G dena. Haan deta hoon",
    "Maggi milega kya? Nahi abhi nahi hai",
    "Nandini milk hai? Haan hai, lijiye",
]
_mock_index = 0


def configured_provider() -> str:
    value = os.environ.get("TRANSCRIPTION_PROVIDER", "auto").strip().lower()
    return value if value in VALID_TRANSCRIPTION_PROVIDERS else "auto"


def _demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def active_provider() -> str:
    """
    Which engine will actually run, after checking what is installed.

    Resolved rather than assumed, so a missing key or an uninstalled package
    degrades the request instead of raising deep inside a handler.
    """
    from .providers import sarvam

    requested = configured_provider()

    if requested == "sarvam":
        return "sarvam" if sarvam.is_configured() else ("mock" if _demo_mode() else "none")
    if requested in {"whisper", "existing"}:
        return "whisper" if is_available() else ("mock" if _demo_mode() else "none")
    if requested == "mock":
        return "mock"

    # auto
    if sarvam.is_configured():
        return "sarvam"
    if is_available():
        return "whisper"
    return "mock" if _demo_mode() else "none"


def _mock_transcribe() -> dict:
    """
    Canned text. Decodes nothing, and says so in the payload so a mock result
    can never be mistaken for a real one downstream.
    """
    global _mock_index
    text = MOCK_TRANSCRIPTS[_mock_index % len(MOCK_TRANSCRIPTS)]
    _mock_index += 1
    return {
        "text": text,
        "language": "hi",
        "language_probability": 1.0,
        "rejected": None,
        "engine": "mock",
        "is_mock": True,
        "note": "Mock transcription. The audio was not decoded.",
    }


def transcribe_file(path: Path) -> dict:
    """
    Audio file to text, via whichever provider is active.

    Raises TranscriptionUnavailable only when nothing at all can transcribe,
    so the route can answer with a useful 503 rather than a stack trace.
    """
    provider = active_provider()

    if provider == "mock":
        return _mock_transcribe()

    if provider == "sarvam":
        from .providers import sarvam

        try:
            result = sarvam.transcribe(path)
        except (sarvam.SarvamNotConfigured, sarvam.SarvamError) as exc:
            # Sarvam is a network dependency in a shop. Falling back to a
            # local model beats losing the event.
            if is_available():
                return _whisper_transcribe(path)
            if _demo_mode():
                return _mock_transcribe()
            raise TranscriptionUnavailable(str(exc)) from exc

        text = result["text"]
        if len(text) < 3:
            return {
                "text": "",
                "language": result.get("language"),
                "language_probability": None,
                "rejected": "Audio contained no intelligible speech.",
                "engine": "sarvam",
                "is_mock": False,
            }
        return {
            "text": text,
            "language": result.get("language"),
            "language_probability": None,
            "rejected": None,
            "engine": "sarvam",
            "is_mock": False,
        }

    if provider == "whisper":
        return _whisper_transcribe(path)

    raise TranscriptionUnavailable(
        "No transcription engine is available. Either set SARVAM_API_KEY, or "
        "`pip install -r requirements-optional.txt` for local Whisper, or have "
        "the client send a `transcript` form field alongside the audio."
    )


# Formats a client may post. The Pi sends WAV; the browser recorder sends WAV
# too, so that one format reaches Sarvam from both.
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}

# A 10-second 16 kHz mono WAV is about 320 KB. 25 MB is generous headroom and
# still small enough that a malformed upload cannot exhaust memory.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def transcribe_bytes(payload: bytes, *, suffix: str = ".wav") -> dict:
    """
    Transcribe an uploaded body without leaving a temp file behind.

    Shared by the Pi ingest route and the dashboard mic so both reach the same
    engine with the same fallbacks; the caller only has to hold the bytes.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="vyapaar_"))
    tmp_path = tmp_dir / f"chunk{suffix}"
    try:
        tmp_path.write_bytes(payload)
        return transcribe_file(tmp_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _whisper_transcribe(path: Path) -> dict:
    """Local faster-whisper. The original engine, unchanged in behaviour."""
    if not is_available():
        raise TranscriptionUnavailable(
            "faster-whisper is not installed on the backend. Either "
            "`pip install -r requirements-optional.txt`, or have the client "
            "send a `transcript` form field alongside the audio."
        )

    model = _get_model()
    segments, info = model.transcribe(
        str(path),
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,   # every chunk stands alone
    )

    language = getattr(info, "language", None)
    probability = float(getattr(info, "language_probability", 0.0) or 0.0)

    # Background chatter makes Whisper guess exotic languages with confidence.
    # Anything outside the Indian set is noise rather than a merchant speaking.
    if language not in ALLOWED_LANGUAGES:
        return {
            "text": "",
            "language": language,
            "language_probability": round(probability, 2),
            "rejected": f"Detected language '{language}', which is not an Indian language.",
            "engine": "faster-whisper",
            "is_mock": False,
        }

    text = " ".join(segment.text.strip() for segment in segments).strip()

    if len(text) < 3 or text.lower().strip(" .!?") in _HALLUCINATIONS:
        return {
            "text": "",
            "language": language,
            "language_probability": round(probability, 2),
            "rejected": "Audio contained no intelligible speech.",
            "engine": "faster-whisper",
            "is_mock": False,
        }

    return {
        "text": text,
        "language": language,
        "language_probability": round(probability, 2),
        "rejected": None,
        "engine": "faster-whisper",
        "is_mock": False,
    }


def status() -> dict:
    from .providers import sarvam

    active = active_provider()
    return {
        "configured": configured_provider(),
        "active": active,
        "available": active not in {"none"},
        "engine": {
            "sarvam": "Sarvam AI speech-to-text",
            "whisper": "faster-whisper (local)",
            "mock": "Mock transcripts (audio not decoded)",
            "none": None,
        }[active],
        "sarvam": sarvam.status(),
        "whisper": {
            "installed": is_available(),
            "model_size": model_size() if is_available() else None,
            "loaded": _model is not None,
            "load_error": _load_error,
        },
        "note": (
            "Clients may always send a pre-computed `transcript` field instead "
            "of audio, which bypasses transcription entirely."
        ),
    }
