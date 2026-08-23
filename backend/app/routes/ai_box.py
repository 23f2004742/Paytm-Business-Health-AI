"""Paytm Vyapaar AI Box and Smart Khata API."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services import ai_box, transcription, tts
from .deps import merchant_id

router = APIRouter(prefix="/api/ai-box", tags=["ai-box"])


@router.get("/state")
def get_state(device_id: str = "pi-shopfloor-01") -> dict:
    return {"device": ai_box.status(device_id), "khata": ai_box.snapshot()}


@router.post("/status")
def update_status(payload: dict) -> dict:
    return ai_box.set_status(str(payload.get("device_id", "demo-box")), str(payload.get("status", "ONLINE")))


@router.post("/register")
def register_device(payload: dict) -> dict:
    return ai_box.set_status(str(payload.get("device_id", "demo-box")), "ONLINE")


@router.post("/heartbeat")
def heartbeat(payload: dict) -> dict:
    return ai_box.set_status(str(payload.get("device_id", "demo-box")), str(payload.get("status", "ONLINE")))


@router.post("/process")
def process_event(payload: dict) -> dict:
    return ai_box.process(str(payload.get("transcript", "")).strip(), merchant_id=str(payload.get("merchant_id") or merchant_id()), source=str(payload.get("source", "demo")), device_id=str(payload.get("device_id", "demo-box")))


@router.post("/voice")
async def process_voice(
    audio: UploadFile = File(...),
    merchant: Optional[str] = Form(default=None),
    device_id: str = Form(default="dashboard-mic"),
) -> dict:
    """
    Speak in any Indian language; the books update and Munim answers aloud.

    The dashboard mic used to run the browser's own recogniser pinned to
    `hi-IN`, which meant Marathi came back as mangled Hindi and Odia could not
    come back at all -- Chrome ships no Odia model. Posting the audio here
    instead puts it through Sarvam, which detects the language itself.

    Nothing in this route names a language. The merchant does not choose one,
    the client does not send one, and the only place a language appears is in
    the reply, so Munim answers in the voice that was spoken to it.
    """
    suffix = Path(audio.filename or "clip.wav").suffix.lower() or ".wav"
    if suffix not in transcription.ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format '{suffix}'.",
        )

    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=422, detail="Audio file was empty.")
    if len(payload) > transcription.MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds {transcription.MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
        )

    try:
        heard = transcription.transcribe_bytes(payload, suffix=suffix)
    except transcription.TranscriptionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    text = (heard.get("text") or "").strip()
    detected = heard.get("language")
    meta = {
        "engine": heard.get("engine"),
        "language": detected,
        "language_probability": heard.get("language_probability"),
        "is_mock": heard.get("is_mock", False),
        "rejected": heard.get("rejected"),
    }

    # Silence is not an error, and it must not reach the ledger. Say so out
    # loud, because the merchant is looking at the counter, not the screen.
    if not text:
        spoken = heard.get("rejected") or "Kuch sunai nahi diya. Phir se boliye."
        return {
            "success": True,
            "heard_nothing": True,
            "transcript": "",
            "text_response": spoken,
            "action_taken": False,
            "voice": tts.speak(spoken, language=detected),
            "transcription": meta,
        }

    result = ai_box.process(
        text,
        merchant_id=merchant or merchant_id(),
        source="voice",
        device_id=device_id,
        language=detected,
    )
    result["transcription"] = meta
    return result


@router.post("/confirm/{event_id}")
def confirm_event(event_id: str) -> dict:
    item = ai_box.activity_item(event_id)
    if not item or not item.get("requires_confirmation"):
        return {"success": False, "message": "Confirmation is no longer pending."}
    return ai_box.process(item["transcript"], merchant_id=merchant_id(), source="confirmed", device_id=item.get("device_id", "demo-box"), confirmed=True)


@router.post("/reject/{event_id}")
def reject_event(event_id: str) -> dict:
    item = ai_box.activity_item(event_id)
    return {"success": bool(item), "event_id": event_id, "action_taken": False, "message": "Khata update rejected; no balance changed."}


@router.get("/activity")
def get_activity() -> dict:
    return ai_box.snapshot()


@router.post("/reset")
def reset_box() -> dict:
    ai_box.reset()
    return {"status": "ok", **ai_box.snapshot()}