"""
Merchant notifications.

The boundary between a merchant action and the channel that announces it.
Routes call the functions here; only this module knows a message has a delivery channel.

The rule this module exists to enforce
------------------------------------------------------------------------------
A NOTIFICATION IS NEVER A PRECONDITION. Raising a restock alert and launching
a campaign are the two merchant actions in this product, and both must return
201 whether or not a text goes out. Twilio being unconfigured, out of credit,
rate limited or simply down is reported in the response body and nowhere else.
Every send is therefore wrapped, and no exception from the provider escapes.

Delivery is off by default for every provider, so running the demo never
contacts a real person by accident.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from . import messaging


def status() -> dict:
    """Configuration report for the dashboard. Contains no secret."""
    return messaging.status()


def _skipped(reason: str) -> dict:
    return {"sent": False, "reason": reason}


def _deliver(body: str, to: Optional[str] = None) -> dict:
    """
    One send attempt, with every failure turned into a result rather than an
    exception. The caller is a merchant action that must succeed regardless.
    """
    if not messaging.enabled():
        return _skipped("Notifications are off. Set the enable flag in .env.")

    try:
        result = messaging.send(body, to=to)
    except messaging.MessagingNotConfigured as exc:
        return _skipped(str(exc))
    except messaging.MessagingError as exc:
        return {"sent": False, "reason": str(exc), "error": True}
    except Exception as exc:  # noqa: BLE001 - a merchant action must not 500 here
        return {"sent": False, "reason": f"Unexpected {type(exc).__name__}.", "error": True}

    return {"sent": True, **result}


def _rupees(value: object) -> str:
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return "Rs -"


def _setting(name: str, default: str) -> str:
    """A non-secret, optional notification setting from the environment."""
    value = (os.environ.get(name) or "").strip()
    return value or default


# --------------------------------------------------------------- messages

def restock_message(alert: dict) -> str:
    """
    Short on purpose: one SMS segment, and readable on a feature phone at a
    counter. Leads with the product because that is the actionable word.
    """
    product = alert.get("product", "an item")
    unmet = alert.get("unfulfilled_requests", 0)
    lost = alert.get("estimated_lost_revenue")

    line = f"Paytm Vyapaar AI: RESTOCK {product}."
    if unmet:
        line += f" {unmet} customers asked and left without it this week."
    if lost:
        line += f" Approx {_rupees(lost)} of sales missed."
    return line


def campaign_message(campaign: dict, projection: Optional[dict] = None) -> str:
    name = campaign.get("campaign_name", "Campaign")
    cashback = campaign.get("cashback_amount")

    line = f"Paytm Vyapaar AI: {name} is now live."
    if cashback:
        line += f" {_rupees(cashback)} cashback"
        minimum = campaign.get("minimum_transaction")
        if minimum:
            line += f" on bills over {_rupees(minimum)}"
        line += "."

    if projection:
        delta = projection.get("delta")
        if isinstance(delta, (int, float)) and delta:
            line += f" Health score projected {delta:+.0f}."
    return line


def lending_repayment_message(
    borrower: str,
    amount: float,
    due_date: str,
    payment_link: Optional[str] = None,
) -> str:
    """A clearly labelled sample repayment reminder for a lending demo.

    The fallback URL intentionally points at example.com. It demonstrates a
    clickable payment link without pretending to collect a real payment.
    """
    brand = _setting("LENDING_BRAND_NAME", "Sujit Shopwala Lending")
    link = payment_link or _setting(
        "LENDING_DEMO_PAYMENT_LINK",
        "https://example.com/?payment=DEMO-LOAN-001",
    )
    safe_name = borrower.strip() or "Customer"
    safe_due_date = due_date.strip() or date.today().isoformat()
    due_phrase = (
        "due today" if safe_due_date.lower() == "today"
        else f"due on {safe_due_date}"
    )

    return (
        f"{brand}\n"
        "Loan repayment reminder\n\n"
        f"Hi {safe_name}, your sample repayment of {_rupees(amount)} is "
        f"{due_phrase}.\n\n"
        f"Pay sample installment: {link}\n\n"
        "Demo only — this link does not collect a real payment."
    )


# ---------------------------------------------------------------- actions

def notify_restock(alert: dict, to: Optional[str] = None) -> dict:
    return _deliver(restock_message(alert), to=to)


def notify_campaign(
    campaign: dict, projection: Optional[dict] = None, to: Optional[str] = None
) -> dict:
    return _deliver(campaign_message(campaign, projection), to=to)


def send_test(to: Optional[str] = None) -> dict:
    """Used by the test endpoint to prove the channel end to end."""
    return _deliver(
        "Paytm Vyapaar AI: test message. Your alert channel is working.", to=to
    )


def send_lending_demo(
    *,
    borrower: str = "Sujit",
    amount: float = 1_500,
    due_date: Optional[str] = None,
    payment_link: Optional[str] = None,
    to: Optional[str] = None,
) -> dict:
    """Send a configurable lending-message preview to the active channel."""
    return _deliver(
        lending_repayment_message(
            borrower=borrower,
            amount=amount,
            due_date=due_date or date.today().isoformat(),
            payment_link=payment_link,
        ),
        to=to,
    )
