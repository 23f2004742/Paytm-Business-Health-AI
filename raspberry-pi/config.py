"""
Raspberry Pi configuration.

Everything is an environment variable with a sane default, so the same code
runs on a Pi with a USB mic, a Pi with a webcam mic, and a laptop with no
mic at all. Nothing about the audio hardware is assumed.

Set values in a `.env` file next to this one, or export them in the shell.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """
    A five-line .env reader.

    python-dotenv is a perfectly good package, but the Pi client is meant to
    install in seconds over a slow shop connection, and this is the only
    thing it would be used for.
    """
    env_path = HERE / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Existing environment always wins, so `FOO=1 python pi_client.py`
        # overrides the file rather than the other way round.
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


def _str(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- Where to send events ----------------------------------------------------
# Never localhost on a real Pi: the backend runs on another machine.
# Find the backend machine's LAN address with `ipconfig` / `ip addr`.
BACKEND_URL = _str("BACKEND_URL", "http://localhost:8000").rstrip("/")
MERCHANT_ID = _str("MERCHANT_ID", "PAYTM_M_001")
DEVICE_ID = _str("DEVICE_ID", "pi-shopfloor-01")
VOICE_OUTPUT_MODE = _str("VOICE_OUTPUT_MODE", "raspberry_pi")

# --- Audio device ------------------------------------------------------------
# AUDIO_DEVICE may be a numeric index or a substring of the device name.
# Leave empty to use the system default input.
#   List devices:  python pi_client.py --list-devices   (or: arecord -l)
AUDIO_DEVICE = _str("AUDIO_DEVICE", "")
SAMPLE_RATE = _int("SAMPLE_RATE", 16000)      # what Whisper expects
CHANNELS = _int("CHANNELS", 1)
RECORDING_DURATION = _float("RECORDING_DURATION", 8.0)    # seconds per chunk

# --- Voice activity ----------------------------------------------------------
# A cheap RMS gate, not a neural VAD. It exists to stop the Pi uploading
# 8,640 chunks of silence a day, not to make linguistic decisions.
VAD_ENABLED = _bool("VAD_ENABLED", True)
VAD_RMS_THRESHOLD = _float("VAD_RMS_THRESHOLD", 0.015)   # 0.0 - 1.0
VAD_MIN_VOICED_RATIO = _float("VAD_MIN_VOICED_RATIO", 0.06)

# --- Modes -------------------------------------------------------------------
# DEMO_MODE: no microphone touched. Scripted transcripts are POSTed instead,
# so the Pi client is demonstrable on any machine.
DEMO_MODE = _bool("DEMO_MODE", False)

# LOCAL_TRANSCRIPTION (Mode A): transcribe on the Pi and send text.
# Off by default. faster-whisper on a Pi 4B runs roughly 3-6x slower than
# real time on the `small` model, which cannot keep up with a live shop.
# Use `tiny` if you enable it at all.
LOCAL_TRANSCRIPTION = _bool("LOCAL_TRANSCRIPTION", False)
WHISPER_MODEL_SIZE = _str("WHISPER_MODEL_SIZE", "tiny")

# --- Networking --------------------------------------------------------------
REQUEST_TIMEOUT = _float("REQUEST_TIMEOUT", 45.0)
MAX_RETRIES = _int("MAX_RETRIES", 3)
RETRY_BACKOFF = _float("RETRY_BACKOFF", 2.0)     # seconds, doubled each try
LOOP_PAUSE = _float("LOOP_PAUSE", 0.5)           # between chunks

# --- Storage -----------------------------------------------------------------
TEMP_DIR = Path(_str("TEMP_DIR", str(HERE / "temp_audio")))
# Chunks that could not be delivered wait here and are retried later, so a
# dropped WiFi link loses nothing.
SPOOL_DIR = Path(_str("SPOOL_DIR", str(HERE / "spool")))
KEEP_AUDIO = _bool("KEEP_AUDIO", False)
LOG_FILE = _str("LOG_FILE", "")


def endpoint(path: str) -> str:
    return f"{BACKEND_URL}{path}"


def summary() -> str:
    """Printed at startup so a misconfigured Pi is obvious immediately."""
    mode = (
        "DEMO (no microphone)"
        if DEMO_MODE
        else ("A - local transcription" if LOCAL_TRANSCRIPTION else "B - edge sensor")
    )
    return "\n".join(
        [
            f"  Backend        {BACKEND_URL}",
            f"  Merchant       {MERCHANT_ID}",
            f"  Device         {DEVICE_ID}",
            f"  Mode           {mode}",
            f"  Audio device   {AUDIO_DEVICE or '(system default)'}",
            f"  Chunk length   {RECORDING_DURATION:g}s @ {SAMPLE_RATE} Hz, "
            f"{CHANNELS} ch",
            f"  Voice gate     {'on, RMS > ' + str(VAD_RMS_THRESHOLD) if VAD_ENABLED else 'off'}",
        ]
    )
