"""
Merchant notification channel: configuration report and a manual test send.

The status endpoint exists so the setup problem is visible from the dashboard
instead of being discovered when a restock alert quietly fails to arrive. It
reports which variables are missing and never reports a secret.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..services import notifications

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/status")
def get_notification_status() -> dict:
    return notifications.status()


@router.post("/test")
def post_notification_test(
    to: Optional[str] = Query(
        default=None,
        description=(
            "Override the recipient. Defaults to MERCHANT_ALERT_NUMBER. On a "
            "Twilio trial account this must be a verified number."
        ),
    ),
) -> dict:
    """
    Send one test message so the channel can be proven end to end.

    Unlike the merchant actions, this endpoint has nothing to succeed at other
    than delivering, so a failure here is a 502 with the reason attached.
    """
    result = notifications.send_test(to=to)

    if not result.get("sent"):
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Test message was not sent.",
                "reason": result.get("reason"),
                "status": notifications.status(),
            },
        )

    return {"status": "sent", "result": result}


@router.post("/lending-demo")
def post_lending_demo(
    borrower: str = Query(default="Sujit", min_length=1, max_length=80),
    amount: float = Query(default=1500, gt=0, le=10_000_000),
    due_date: str = Query(default="today", min_length=1, max_length=80),
    payment_link: Optional[str] = Query(default=None, max_length=2048),
    to: Optional[str] = Query(default=None),
) -> dict:
    """Send a clearly marked lending repayment preview with a sample link."""
    result = notifications.send_lending_demo(
        borrower=borrower,
        amount=amount,
        due_date=due_date,
        payment_link=payment_link,
        to=to,
    )
    if not result.get("sent"):
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Lending demo message was not sent.",
                "reason": result.get("reason"),
                "status": notifications.status(),
            },
        )
    return {"status": "sent", "result": result}
