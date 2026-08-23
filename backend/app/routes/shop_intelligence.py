"""
Shop-floor intelligence API.

The Raspberry Pi posts here. Everything else reads from here.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services import ai_box, demand_analysis, shop_intelligence, transcription
from ..services.interaction_outcome_engine import summarise_outcomes
from .deps import (
    all_events,
    all_interactions,
    contexts,
    demand_summary,
    merchant_id,
    week_events,
    week_interactions,
)

router = APIRouter(prefix="/api/shop-intelligence", tags=["shop-intelligence"])

# A 10-second 16 kHz mono WAV is about 320 KB. 25 MB is generous headroom
# and still small enough that a malformed upload cannot exhaust memory.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


@router.post("/audio")
async def ingest_audio(
    audio: Optional[UploadFile] = File(default=None),
    merchant: Optional[str] = Form(default=None),
    merchant_id_field: Optional[str] = Form(default=None, alias="merchant_id"),
    timestamp: Optional[str] = Form(default=None),
    transcript: Optional[str] = Form(default=None),
    device_id: Optional[str] = Form(default=None),
) -> dict:
    """
    Audio (or a pre-computed transcript) in, structured shop events out.

    Two modes, so the Pi never has to run the heavy stack:

      Mode A  the client transcribed locally and sends `transcript`
      Mode B  the client sends a WAV and the backend transcribes it

    Sending both is allowed: the transcript wins and the audio is ignored,
    which lets a Pi fall back to Mode A without changing endpoints.
    """
    resolved_merchant = merchant_id_field or merchant or merchant_id()

    when = datetime.now()
    if timestamp:
        try:
            when = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            # A bad clock on the Pi must not lose the event.
            when = datetime.now()

    text = (transcript or "").strip()
    transcription_meta: dict = {"source": "client", "engine": None}

    if not text:
        if audio is None:
            raise HTTPException(
                status_code=422,
                detail="Send either an `audio` file or a `transcript` field.",
            )

        suffix = Path(audio.filename or "chunk.wav").suffix.lower() or ".wav"
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported audio format '{suffix}'. Send WAV from the Pi.",
            )

        payload = await audio.read()
        if not payload:
            raise HTTPException(status_code=422, detail="Audio file was empty.")
        if len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Audio exceeds {MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
            )

        tmp_dir = Path(tempfile.mkdtemp(prefix="vyapaar_"))
        tmp_path = tmp_dir / f"chunk{suffix}"
        try:
            tmp_path.write_bytes(payload)
            try:
                result = transcription.transcribe_file(tmp_path)
            except transcription.TranscriptionUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            text = result["text"]
            transcription_meta = {
                "source": "backend",
                "engine": result.get("engine"),
                "is_mock": result.get("is_mock", False),
                "language": result.get("language"),
                "language_probability": result.get("language_probability"),
                "rejected": result.get("rejected"),
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not text:
        return {
            "success": True,
            "transcript": "",
            "events": [],
            "message": transcription_meta.get("rejected")
            or "No intelligible speech in this sample.",
            "transcription": transcription_meta,
        }

    interaction, events = shop_intelligence.build_interaction_and_events(
        text,
        merchant_id=resolved_merchant,
        timestamp=when,
        source="audio",
    )
    shop_intelligence.interaction_store().append(interaction)
    shop_intelligence.event_store().append(events)

    box_result = None
    if device_id:
        box_result = ai_box.process(
            text,
            merchant_id=resolved_merchant,
            source="audio",
            device_id=device_id,
            persist_product=False,
        )

    return {
        "success": True,
        "transcript": text,
        "events": [
            {
                "product": e.product_display or e.product,
                "catalog_item": e.product,
                "intent": e.intent,
                "availability": e.availability,
                "potential_lost_sale": e.potential_lost_sale,
                "confidence": e.confidence,
                "timestamp": e.timestamp,
            }
            for e in events
        ],
        "event_count": len(events),
        "device_id": device_id,
        "transcription": transcription_meta,
        "extractor": interaction.extractor,
        "ai_box": box_result,
        # The buyer/seller reading, so the Pi and the dashboard can show what
        # was actually understood rather than just that something was stored.
        "interaction": {
            "interaction_id": interaction.interaction_id,
            "conversation": interaction.conversation,
            "product": interaction.product,
            "quantity": interaction.quantity,
            "buyer_intent": interaction.buyer_intent,
            "seller_response": interaction.seller_response,
            "interaction_outcome": interaction.interaction_outcome,
            "potential_lost_sale": interaction.potential_lost_sale,
            "expects_transaction": interaction.expects_transaction,
            "confidence": interaction.confidence,
            "role_confidence": interaction.role_confidence,
            "reasoning": interaction.reasoning,
        },
    }


@router.post("/text")
def ingest_text(payload: dict) -> dict:
    """
    Transcript-only ingest, for testing without any audio hardware at all.

    Same pipeline as /audio from the transcript onward.
    """
    text = str(payload.get("transcript", "")).strip()
    if not text:
        raise HTTPException(status_code=422, detail="`transcript` is required.")

    when = datetime.now()
    if payload.get("timestamp"):
        try:
            when = datetime.fromisoformat(str(payload["timestamp"]))
        except ValueError:
            pass

    interaction, events = shop_intelligence.build_interaction_and_events(
        text,
        merchant_id=payload.get("merchant_id") or merchant_id(),
        timestamp=when,
        source=payload.get("source", "manual"),
    )
    shop_intelligence.interaction_store().append(interaction)
    shop_intelligence.event_store().append(events)

    return {
        "success": True,
        "transcript": text,
        "events": [e.as_dict() for e in events],
        "event_count": len(events),
        "interaction": interaction.as_dict(),
    }


@router.get("/summary")
def get_summary() -> dict:
    """Demand, high-demand products and out-of-stock requests for this week."""
    ctx, _ = contexts()
    events = week_events(ctx)
    summary = demand_summary(ctx, events)

    return {
        **summary,
        "window": {
            "start": ctx.current.start.date().isoformat(),
            "end": ctx.current.end.date().isoformat(),
            "days": ctx.current.days,
        },
        "demo_mode": shop_intelligence.demo_mode_enabled(),
        "transcription": transcription.status(),
    }


@router.get("/events")
def get_events(limit: int = 100, product: Optional[str] = None) -> dict:
    """Raw event feed, newest first."""
    events = all_events()

    if product:
        needle = product.lower()
        events = [
            e
            for e in events
            if needle in (e.get("product_display") or "").lower()
            or needle in (e.get("product") or "").lower()
        ]

    limited = events[: max(1, min(limit, 500))]
    return {
        "events": limited,
        "total": len(events),
        "returned": len(limited),
        "demo_mode": shop_intelligence.demo_mode_enabled(),
    }


@router.get("/products/{family}")
def get_product(family: str) -> dict:
    """Everything known about one product family."""
    ctx, _ = contexts()
    events = week_events(ctx)

    rows = demand_analysis.product_demand(events)
    row = next((r for r in rows if r["family"] == family.lower()), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"No shop demand for '{family}'.")

    return {
        "product": row,
        "events": demand_analysis.filter_events(events, families={family.lower()}),
    }


@router.get("/interactions")
def get_interactions(limit: int = 50, outcome: Optional[str] = None) -> dict:
    """
    Buyer/seller exchanges, newest first.

    This is the audit trail behind every demand number: each interaction
    carries the conversation that produced it, with roles attached.
    """
    interactions = all_interactions()

    if outcome:
        needle = outcome.strip().lower()
        interactions = [
            i for i in interactions if i.get("interaction_outcome") == needle
        ]

    limited = interactions[: max(1, min(limit, 200))]
    return {
        "interactions": limited,
        "total": len(interactions),
        "returned": len(limited),
        "outcomes": summarise_outcomes(interactions),
        "demo_mode": shop_intelligence.demo_mode_enabled(),
    }


@router.get("/demand")
def get_demand() -> dict:
    """Demand and fulfilment for the current analysis window."""
    ctx, _ = contexts()
    events = week_events(ctx)
    interactions = week_interactions(ctx)
    summary = demand_summary(ctx, events)

    return {
        **summary,
        "outcomes": summarise_outcomes(interactions),
        "window": {
            "start": ctx.current.start.date().isoformat(),
            "end": ctx.current.end.date().isoformat(),
        },
    }


@router.post("/demo/seed")
def seed_demo() -> dict:
    """Reload the scripted shop day. Deterministic and idempotent."""
    ctx, _ = contexts()
    anchor = ctx.anchor.to_pydatetime().replace(hour=23, minute=59, second=59)
    created = shop_intelligence.seed_demo_events(merchant_id(), anchor, replace=True)
    return {
        "status": "ok",
        "events_created": created,
        "anchored_to": ctx.anchor.date().isoformat(),
        "message": f"Seeded {created} shop events across the last 7 days.",
    }


@router.post("/events/clear")
def clear_events() -> dict:
    shop_intelligence.event_store().clear()
    shop_intelligence.interaction_store().clear()
    return {"status": "ok", "message": "Shop event and interaction stores cleared."}


@router.get("/status")
def status() -> dict:
    """Health of the shop-floor pipeline, for the Pi and the dashboard."""
    from ..services import ai_engine

    return {
        "demo_mode": shop_intelligence.demo_mode_enabled(),
        "stored_events": shop_intelligence.event_store().count(),
        "catalog_size": len(shop_intelligence.load_catalog()),
        "transcription": transcription.status(),
        "extraction": {
            "stage_1": "llm" if ai_engine.active_provider() != "template" else "rules",
            "stage_2": "deterministic catalogue match",
            "provider": ai_engine.provider_status(),
        },
    }
