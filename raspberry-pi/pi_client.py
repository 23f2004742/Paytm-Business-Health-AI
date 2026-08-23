"""
Paytm Vyapaar AI: Raspberry Pi shop-floor client.

Records short chunks of shop conversation and posts them to the backend,
which turns them into structured demand events.

    python pi_client.py                  run continuously
    python pi_client.py --once           one chunk, then exit
    python pi_client.py --demo           no microphone, scripted transcripts
    python pi_client.py --list-devices   show input devices and exit
    python pi_client.py --check          test config and backend, then exit
    python pi_client.py --text "..."     send one transcript by hand

Design rules, in priority order:

  1. Never crash. A shop counter is not a place to debug a stack trace.
     Missing mic, dead WiFi, backend restarting, wrong IP: all are reported
     in one line and retried.
  2. Never lose an event. Undeliverable chunks spool to disk and go out when
     the link returns.
  3. Stay light. No torch, no LLM, no Whisper unless explicitly asked for.
     Standard library plus requests, and numpy/sounddevice for the mic.
"""

from __future__ import annotations

import argparse
import json
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

try:
    import requests
except ImportError:  # pragma: no cover - the one hard dependency
    print("[!] `requests` is not installed. Run: pip install -r requirements-pi.txt")
    raise SystemExit(1)


AUDIO_ENDPOINT = "/api/shop-intelligence/audio"
TEXT_ENDPOINT = "/api/shop-intelligence/text"
STATUS_ENDPOINT = "/api/shop-intelligence/status"
BOX_STATUS_ENDPOINT = "/api/ai-box/status"

# Scripted shop-floor lines for --demo. The Maggi thread is deliberate: it is
# the story the dashboard is built around.
# Written as buyer/seller exchanges so --demo exercises the same role
# classification and outcome logic that live audio does.
DEMO_TRANSCRIPTS = [
    "Bhaiya Maggi hai? Nahi beta khatam ho gaya",
    "Do Parle-G packet dena. Haan deta hoon",
    "Ek Maggi packet chahiye. Sorry khatam ho gaya",
    "Nandini milk dena. Haan hai, lijiye",
    "Maggi milega kya? Nahi abhi nahi hai",
    "Ek Maggi dena. Haan, 20 rupaye. UPI kar diya",
    "Thums Up ek bottle dena. Haan lijiye",
    "Bhaiya Maggi noodles chahiye. Khatam ho gaya bhai",
    "Do Lays packet dena. Haan deta hoon",
    "Maggi hai? Maggi nahi hai, noodles le lo",
]

_running = True


def _stop(_signum, _frame) -> None:
    global _running
    _running = False
    print("\n[*] Stopping after this chunk...")


def log(message: str, *, level: str = "*") -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] [{level}] {message}"
    print(line, flush=True)
    if config.LOG_FILE:
        try:
            with open(config.LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            # Logging must never be the thing that stops the shop listener.
            pass


# --------------------------------------------------------------- networking

def post_with_retry(
    url: str,
    *,
    files: Optional[dict] = None,
    data: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Optional[dict]:
    """
    POST with bounded exponential backoff.

    Returns the decoded body, or None when every attempt failed. Never
    raises: the caller decides whether to spool or drop.
    """
    delay = config.RETRY_BACKOFF

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                files=files,
                data=data,
                json=json_body,
                timeout=config.REQUEST_TIMEOUT,
            )

            if response.status_code < 300:
                return response.json()

            # 4xx means this request is wrong and will stay wrong. Retrying
            # a malformed upload just burns the shop's bandwidth.
            if 400 <= response.status_code < 500:
                detail = _detail(response)
                log(f"Backend rejected the request ({response.status_code}): {detail}", level="!")
                if response.status_code in (413, 415, 422):
                    return None
            else:
                log(f"Backend error {response.status_code}, retrying...", level="!")

        except requests.exceptions.ConnectionError:
            log(
                f"Cannot reach {config.BACKEND_URL} (attempt {attempt}/{config.MAX_RETRIES}). "
                "Is the backend running, and is BACKEND_URL the right LAN address?",
                level="!",
            )
        except requests.exceptions.Timeout:
            log(f"Backend timed out (attempt {attempt}/{config.MAX_RETRIES}).", level="!")
        except ValueError:
            log("Backend returned a non-JSON response.", level="!")
            return None
        except Exception as exc:  # noqa: BLE001 - stay alive whatever happens
            log(f"Unexpected error: {type(exc).__name__}: {exc}", level="!")

        if attempt < config.MAX_RETRIES:
            time.sleep(delay)
            delay *= 2

    return None


def _detail(response) -> str:
    try:
        return str(response.json().get("detail", response.text[:200]))
    except ValueError:
        return response.text[:200]


# How each outcome reads on the shop-floor console.
_OUTCOME_DISPLAY = {
    "unfulfilled": ("!", "LOST SALE"),
    "fulfilled": ("*", "SALE"),
    "alternative_offered": ("!", "SUBSTITUTE OFFERED"),
    "abandoned": ("-", "CUSTOMER LEFT"),
    "uncertain": ("-", "UNCLEAR"),
}


def report(result: dict) -> None:
    """
    Print what the backend understood: the roles, then the outcome.

    Showing the buyer/seller split on the Pi console is not decoration. When
    the shopkeeper is standing next to the device during setup, seeing the
    roles come out right is how they know it is working, and seeing them come
    out wrong is how they know the mic is picking up the wrong side of the
    counter.
    """
    box_result = result.get("ai_box") or result
    transcript = (result.get("transcript") or "").strip()
    if not transcript:
        log(result.get("message") or "No speech detected.", level="-")
        return

    response_text = (box_result.get("text_response") or "").strip()
    if response_text and config.VOICE_OUTPUT_MODE == "raspberry_pi":
        speaker = shutil.which("espeak") or shutil.which("espeak-ng")
        if speaker:
            try:
                subprocess.run([speaker, response_text], check=False, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                log("Could not play the response through the Pi speaker.", level="!")

    log(f'Heard: "{transcript}"')

    interaction = result.get("interaction") or {}
    conversation = interaction.get("conversation") or []

    for turn in conversation:
        speaker = (turn.get("speaker") or "unknown").upper()
        confidence = turn.get("confidence", 0)
        meaning = turn.get("intent") or turn.get("response") or ""
        suffix = f"  [{meaning.replace('_', ' ')}]" if meaning else ""
        log(f"   {speaker:7} ({confidence:.0%}): \"{turn.get('text', '')}\"{suffix}", level="-")

    if not interaction:
        # An older backend, or a transcript with nothing in it.
        events = result.get("events") or []
        if not events:
            log("No product requests in that exchange.", level="-")
        for event in events:
            log(f"Request: {event.get('product', '?')}")
        return

    outcome = interaction.get("interaction_outcome", "uncertain")
    marker, label = _OUTCOME_DISPLAY.get(outcome, ("-", outcome.upper()))
    product = interaction.get("product")
    quantity = interaction.get("quantity")

    parts = [label]
    if product:
        parts.append(f"{product}{f' x{quantity}' if quantity and quantity > 1 else ''}")
    parts.append(f"confidence {interaction.get('confidence', 0):.0%}")

    log(" | ".join(parts), level=marker)

    if interaction.get("potential_lost_sale"):
        log("   ^ a customer asked for this and left without it.", level="!")
    elif interaction.get("expects_transaction"):
        log("   ^ a matching payment is expected.", level="-")


# ------------------------------------------------------------------- spool

def spool(path: Path, timestamp: str) -> None:
    """Keep an undeliverable chunk for later rather than losing it."""
    config.SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    target = config.SPOOL_DIR / f"{timestamp.replace(':', '-')}_{path.name}"
    try:
        path.replace(target)
        meta = target.with_suffix(target.suffix + ".json")
        meta.write_text(json.dumps({"timestamp": timestamp}), encoding="utf-8")
        log(f"Spooled to {target.name}; will retry when the backend is reachable.", level="-")
    except OSError as exc:
        log(f"Could not spool the chunk: {exc}", level="!")


def flush_spool() -> int:
    """Try to deliver everything waiting on disk. Returns how many went out."""
    if not config.SPOOL_DIR.exists():
        return 0

    waiting = sorted(p for p in config.SPOOL_DIR.glob("*.wav"))
    if not waiting:
        return 0

    log(f"{len(waiting)} spooled chunk(s) waiting, retrying...")
    sent = 0

    for path in waiting:
        meta_path = path.with_suffix(path.suffix + ".json")
        timestamp = datetime.now().isoformat(timespec="seconds")
        if meta_path.exists():
            try:
                timestamp = json.loads(meta_path.read_text(encoding="utf-8"))["timestamp"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        result = send_audio(path, timestamp)
        if result is None:
            break   # still down; leave the rest for next time

        sent += 1
        report(result)
        path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    return sent


# -------------------------------------------------------------------- send

def send_audio(path: Path, timestamp: str, transcript: Optional[str] = None) -> Optional[dict]:
    data = {
        "merchant_id": config.MERCHANT_ID,
        "timestamp": timestamp,
        "device_id": config.DEVICE_ID,
    }
    if transcript:
        data["transcript"] = transcript

    try:
        with open(path, "rb") as handle:
            return post_with_retry(
                config.endpoint(AUDIO_ENDPOINT),
                files={"audio": (path.name, handle, "audio/wav")},
                data=data,
            )
    except OSError as exc:
        log(f"Could not read {path}: {exc}", level="!")
        return None


def send_text(transcript: str, timestamp: Optional[str] = None) -> Optional[dict]:
    return post_with_retry(
        config.endpoint(TEXT_ENDPOINT),
        json_body={
            "transcript": transcript,
            "merchant_id": config.MERCHANT_ID,
            "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
            "source": "audio",
        },
    )


def set_box_status(value: str) -> None:
    post_with_retry(
        config.endpoint(BOX_STATUS_ENDPOINT),
        json_body={"device_id": config.DEVICE_ID, "status": value},
    )


# ------------------------------------------------------------------ checks

def check() -> int:
    """Validate configuration and connectivity without recording anything."""
    print("Paytm Vyapaar AI: Pi client check")
    print("=" * 52)
    print(config.summary())
    print()

    ok = True

    print("[1/3] Backend reachable...")
    try:
        response = requests.get(config.endpoint(STATUS_ENDPOINT), timeout=10)
        response.raise_for_status()
        status = response.json()
        print(f"      OK. Catalogue {status.get('catalog_size')} items, "
              f"{status.get('stored_events')} events stored.")
        engine = (status.get("transcription") or {}).get("available")
        print(f"      Backend transcription: {'available' if engine else 'NOT installed'}")
        if not engine and not config.LOCAL_TRANSCRIPTION:
            print("      [!] Neither side can transcribe audio.")
            print("          Install faster-whisper on the backend")
            print("          (pip install -r requirements-optional.txt),")
            print("          or set LOCAL_TRANSCRIPTION=true here,")
            print("          or run this client with --demo.")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"      FAILED: {type(exc).__name__}")
        print(f"      Could not reach {config.BACKEND_URL}")
        print("      Check: backend running? correct LAN IP? same network? firewall?")
        ok = False

    print("[2/3] Audio input...")
    if config.DEMO_MODE:
        print("      Skipped (demo mode).")
    else:
        try:
            from audio_capture import AudioUnavailable, resolve_device

            device = resolve_device(config.AUDIO_DEVICE)
            print(f"      OK. Using device {device if device is not None else '(default)'}.")
        except AudioUnavailable as exc:
            print(f"      FAILED: {exc}")
            ok = False
        except Exception as exc:  # noqa: BLE001
            print(f"      FAILED: {type(exc).__name__}: {exc}")
            ok = False

    print("[3/3] Local transcription...")
    if not config.LOCAL_TRANSCRIPTION:
        print("      Disabled (Mode B: the backend transcribes). This is the default.")
    else:
        import audio_processor

        available = audio_processor.is_available()
        print(f"      faster-whisper {'installed' if available else 'NOT installed'}")
        ok = ok and available

    print()
    print("Result:", "READY" if ok else "NOT READY (see above)")
    return 0 if ok else 1


# ------------------------------------------------------------------- loops

def run_demo(once: bool = False) -> int:
    """No microphone involved. Posts scripted transcripts on a timer."""
    log("DEMO MODE: no microphone will be used.")
    set_box_status("ONLINE")
    log(f"Posting scripted shop conversations to {config.BACKEND_URL}")
    print()

    index = 0
    while _running:
        transcript = DEMO_TRANSCRIPTS[index % len(DEMO_TRANSCRIPTS)]
        index += 1

        log(f"Simulating: \"{transcript}\"")
        result = send_text(transcript)

        if result is None:
            log("Backend unreachable. Will try again.", level="!")
        else:
            report(result)

        if once:
            return 0
        print()
        for _ in range(int(config.RECORDING_DURATION * 2)):
            if not _running:
                break
            time.sleep(0.5)

    return 0


def run_capture(once: bool = False) -> int:
    """The real thing: record, optionally transcribe, upload, repeat."""
    from audio_capture import AudioRecorder, AudioUnavailable

    try:
        recorder = AudioRecorder.from_config()
    except AudioUnavailable as exc:
        log(str(exc), level="!")
        log("Start with --demo to run without a microphone.", level="!")
        return 1

    log("Listening. Press Ctrl+C to stop.")
    set_box_status("LISTENING")
    print()

    chunk = 0
    consecutive_failures = 0

    while _running:
        chunk += 1
        timestamp = datetime.now().isoformat(timespec="seconds")
        path = config.TEMP_DIR / f"chunk_{chunk:05d}.wav"

        try:
            path, speech, level = recorder.record(path)
        except AudioUnavailable as exc:
            log(str(exc), level="!")
            # The mic may come back (a USB device gets re-seated), so wait
            # and retry rather than exiting and losing the shop listener.
            time.sleep(5)
            continue

        if not speech:
            log(f"Quiet (RMS {level:.4f}), skipping upload.", level="-")
            if not config.KEEP_AUDIO:
                path.unlink(missing_ok=True)
            if once:
                return 0
            time.sleep(config.LOOP_PAUSE)
            continue

        transcript = None
        if config.LOCAL_TRANSCRIPTION:
            import audio_processor

            try:
                transcript = audio_processor.transcribe(path)
                if transcript is None:
                    log("Local transcription found no usable speech.", level="-")
                    if not config.KEEP_AUDIO:
                        path.unlink(missing_ok=True)
                    if once:
                        return 0
                    continue
            except audio_processor.LocalTranscriptionUnavailable as exc:
                log(str(exc), level="!")
                log("Falling back to sending audio to the backend.", level="-")

        set_box_status("PROCESSING")
        result = send_audio(path, timestamp, transcript)

        if result is None:
            consecutive_failures += 1
            spool(path, timestamp)
            if consecutive_failures == 3:
                log(
                    "The backend has been unreachable for a while. Recording "
                    "continues and chunks are being kept on disk.",
                    level="!",
                )
        else:
            if consecutive_failures:
                log("Backend is back.", level="*")
            consecutive_failures = 0
            report(result)
            set_box_status("LISTENING")
            if not config.KEEP_AUDIO:
                path.unlink(missing_ok=True)
            flush_spool()

        if once:
            return 0

        print()
        time.sleep(config.LOOP_PAUSE)

    return 0


# -------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Paytm Vyapaar AI shop-floor client for Raspberry Pi.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--once", action="store_true", help="capture one chunk and exit")
    parser.add_argument("--demo", action="store_true", help="no microphone; scripted transcripts")
    parser.add_argument("--list-devices", action="store_true", help="list audio inputs and exit")
    parser.add_argument("--check", action="store_true", help="verify setup and exit")
    parser.add_argument("--text", metavar="TRANSCRIPT", help="send one transcript and exit")
    args = parser.parse_args()

    if args.list_devices:
        from audio_capture import list_devices

        print(list_devices())
        return 0

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if args.check:
        return check()

    if args.text:
        result = send_text(args.text)
        if result is None:
            log("Could not reach the backend.", level="!")
            return 1
        print(json.dumps(result, indent=2))
        return 0

    print("=" * 52)
    print("  Paytm Vyapaar AI: shop-floor listener")
    print("=" * 52)
    print(config.summary())
    print("=" * 52)
    print()

    if args.demo or config.DEMO_MODE:
        return run_demo(once=args.once)

    flush_spool()
    return run_capture(once=args.once)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[*] Stopped.")
        sys.exit(0)
