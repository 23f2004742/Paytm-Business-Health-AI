"""
Paytm Vyapaar AI: FastAPI application.

    Payments tell us what customers bought.
    Conversations tell us what customers wanted.
    Paytm Vyapaar AI tells merchants what to do next.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env from the repo root as well as the backend directory.
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")

from .routes.analysis import router as analysis_router  # noqa: E402
from .routes.ai_box import router as ai_box_router  # noqa: E402
from .routes.campaigns import router as campaigns_router  # noqa: E402
from .routes.collections import router as collections_router  # noqa: E402
from .routes.dashboard import router as dashboard_router  # noqa: E402
from .routes.health import router as health_router  # noqa: E402
from .routes.insights import router as insights_router  # noqa: E402
from .routes.money import router as money_router  # noqa: E402
from .routes.notifications import router as notifications_router  # noqa: E402
from .routes.recommendations import router as recommendations_router  # noqa: E402
from .routes.shop_intelligence import router as shop_router  # noqa: E402
from .routes.telegram import router as telegram_router  # noqa: E402
from .services import ai_engine, shop_intelligence, telegram_bot, transcription  # noqa: E402
from .services.data_loader import DatasetMissingError  # noqa: E402

app = FastAPI(
    title="Paytm Vyapaar AI",
    description=(
        "Transaction intelligence and shop-floor conversation intelligence, "
        "joined into one business copilot for Paytm merchants."
    ),
    version="2.0.0",
)


def _cors_origins() -> list[str]:
    """
    Defaults cover local development. The Pi does not need an entry: it is an
    HTTP client, not a browser, so CORS never applies to it.
    """
    configured = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [o.strip() for o in configured.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DatasetMissingError)
async def dataset_missing_handler(_: Request, exc: DatasetMissingError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "hint": "Run `python data/generate_data.py` from the backend directory.",
        },
    )


app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(insights_router)
app.include_router(recommendations_router)
app.include_router(campaigns_router)
app.include_router(money_router)
app.include_router(collections_router)
app.include_router(notifications_router)
app.include_router(shop_router)
app.include_router(analysis_router)
app.include_router(ai_box_router)
app.include_router(telegram_router)


@app.on_event("startup")
def start_telegram_poller() -> None:
    """Local mode: receive Telegram messages without a public webhook URL."""
    if telegram_bot.mode() == "polling" and telegram_bot.status()["configured"]:
        telegram_bot.start_background_poller()


@app.on_event("shutdown")
def stop_telegram_poller() -> None:
    telegram_bot.stop_background_poller()


@app.get("/")
def root() -> dict:
    return {
        "service": "Paytm Vyapaar AI",
        "tagline": "Payments tell us what customers bought. "
        "Conversations tell us what customers wanted.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    """Liveness, plus which optional pieces are actually present."""
    from .services import paytm_provider

    return {
        "status": "ok",
        "ai_provider": ai_engine.provider_status(),
        "transcription": transcription.status(),
        "paytm_data": paytm_provider.status(),
        "shop_intelligence": {
            "demo_mode": shop_intelligence.demo_mode_enabled(),
            "stored_events": shop_intelligence.event_store().count(),
            "catalog_size": len(shop_intelligence.load_catalog()),
        },
    }
