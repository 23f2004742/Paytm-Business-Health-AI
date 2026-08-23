"""Telegram bot control endpoints.

Local development uses long polling. A deployed service can instead expose the
webhook below over HTTPS and configure Telegram with the same secret token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ..services import telegram_bot

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.get("/status")
def get_telegram_status() -> dict:
    """Safe bot readiness report; it never exposes credentials or chat IDs."""
    return telegram_bot.status()


@router.post("/webhook")
async def post_telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Accept an update from Telegram after verifying the configured secret."""
    if not telegram_bot.webhook_secret_matches(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret.")

    try:
        payload: Any = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Telegram update must be JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Telegram update must be an object.")

    # Telegram only needs a quick acknowledgement. Sarvam generation and audio
    # synthesis continue after the HTTP response has been returned.
    background_tasks.add_task(telegram_bot.handle_update, payload)
    return {"ok": True}
