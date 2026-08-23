"""Run the Telegram bot locally without needing a public HTTPS URL.

Usage:
    python scripts/run_telegram_bot.py
    python scripts/run_telegram_bot.py --once
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "backend"))

from app.services import telegram_bot  # noqa: E402


def main() -> None:
    once = "--once" in sys.argv[1:]
    config = telegram_bot.status()
    if not config["configured"]:
        raise SystemExit("Telegram is not configured. Set TELEGRAM_BOT_TOKEN in .env.")
    if not config["sarvam_configured"]:
        raise SystemExit("Sarvam is not configured. Set SARVAM_API_KEY in .env.")
    telegram_bot.poll_forever(once=once)


if __name__ == "__main__":
    main()
