"""
Optional on-Pi processing (Mode A).

By default the Pi does none of this: it ships the WAV and the backend does
the work. That is the whole point of the edge-sensor design, and it is what
keeps a Pi 4B viable.

Enable LOCAL_TRANSCRIPTION only if you have measured it on your own hardware.
On a Pi 4B, faster-whisper runs roughly:

    tiny    ~1.5-2.5x slower than real time   (usable for 10s chunks)
    base    ~3-4x slower                      (falls behind a live shop)
    small   ~6-8x slower                      (not viable)

A 10-second chunk taking 25 seconds to transcribe means the queue grows
forever, so `tiny` is the default here and even that is a compromise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import config

_model = None


class LocalTranscriptionUnavailable(RuntimeError):
    pass


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model():
    global _model
    if _model is not None:
        return _model

    if not is_available():
        raise LocalTranscriptionUnavailable(
            "faster-whisper is not installed on this Pi. Either\n"
            "    pip install faster-whisper\n"
            "or leave LOCAL_TRANSCRIPTION=false and let the backend do it."
        )

    from faster_whisper import WhisperModel

    print(f"[*] Loading faster-whisper '{config.WHISPER_MODEL_SIZE}' (first run is slow)...")
    _model = WhisperModel(config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("[*] Model loaded.")
    return _model


# Kept in step with backend/app/services/transcription.py. Whisper reports
# ISO 639-1, so Odia is `or` here and `od-IN` on the Sarvam side.
ALLOWED_LANGUAGES = {
    "hi", "en", "mr", "or", "bn", "gu", "kn", "ml", "pa", "ta", "te", "ur",
    "as", "ne", "sa",
}


def transcribe(path: Path) -> Optional[str]:
    """
    WAV to text on the Pi. Returns None when there is nothing usable, so the
    caller can skip the upload entirely.

    The language gate is the same one the backend uses: it exists to drop the
    exotic languages Whisper hallucinates out of shop-floor background noise,
    NOT to pick a language for the merchant. It used to allow only Hindi and
    English, which silently threw away every Odia and Marathi sentence spoken
    at the counter.
    """
    model = _get_model()

    segments, info = model.transcribe(
        str(path),
        beam_size=1,                      # greedy: the Pi has no headroom for 5
        vad_filter=True,
        condition_on_previous_text=False,
    )

    if getattr(info, "language", None) not in ALLOWED_LANGUAGES:
        return None

    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text if len(text) >= 3 else None
