"""
Collections: chasing money that is stuck.

Money in and money out are bookkeeping. This is the only part of the product
that acts on the merchant's behalf towards someone else, which is why it is
the most carefully bounded thing here.

    "Kumar ko yaad dilao"  ->  Kumar gets a WhatsApp, in his own language,
                               saying what he owes, with a way to pay it.

------------------------------------------------------------------------------
Rules this module enforces, all for the same reason
------------------------------------------------------------------------------
A reminder is a message from a shopkeeper to a real customer, and getting it
wrong costs the merchant a relationship, not a rupee.

  * Never chase a settled account. A zero balance means no message, ever.
  * Never chase twice in a day. A shop that nags loses the customer; the
    cooldown is refused politely rather than silently swallowed.
  * Never invent an amount. The figure comes from the khata balance, and the
    exact text sent is stored so the merchant can show it later.
  * Never invent a payment link. If no real one is configured the line is
    omitted, because a dead link in a payment request is worse than no link.

The message is composed deterministically, not by a model. It states money and
a merchant's name to somebody's customer, so it is never left to phrasing.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import db, messaging

# A shop that reminds the same person twice in a day is a shop that loses them.
COOLDOWN_HOURS = 24

# Real payment links need Paytm's payment-links API, which this project does
# not have. Set PAYMENT_LINK_BASE to a base URL you control and the line is
# included; leave it unset and the message simply asks them to pay, because a
# link that goes nowhere in a payment request destroys trust immediately.
DEFAULT_LINK_BASE = ""


class CollectionError(RuntimeError):
    """Refused for a stated reason. Never raised for a delivery failure."""


def link_base() -> str:
    return (os.environ.get("PAYMENT_LINK_BASE") or DEFAULT_LINK_BASE).strip().rstrip("/")


def payment_link(customer_id: str, reminder_id: str) -> Optional[str]:
    """A per-reminder reference, so a merchant can tell two requests apart."""
    base = link_base()
    if not base:
        return None
    return f"{base}/{reminder_id.lower()}"


# --------------------------------------------------------------- languages

# The shop floor is not monolingual and a payment request is exactly the wrong
# place to make somebody read a second language. Each template takes the same
# four fields, so adding a language is adding one row.
TEMPLATES: dict[str, dict[str, str]] = {
    "hinglish": {
        "label": "Hinglish",
        "body": ("Hi {name},\n"
                 "{shop} se: aapka ₹{amount} baaki hai.\n"
                 "Kripya payment kar dijiye."),
        "pay": "Pay Now: {link}",
    },
    "hindi": {
        "label": "हिन्दी",
        "body": ("नमस्ते {name},\n"
                 "{shop} से: आपके ₹{amount} बाकी हैं।\n"
                 "कृपया भुगतान कर दीजिए।"),
        "pay": "भुगतान करें: {link}",
    },
    "english": {
        "label": "English",
        "body": ("Hi {name},\n"
                 "From {shop}: ₹{amount} is pending on your account.\n"
                 "Please make the payment."),
        "pay": "Pay Now: {link}",
    },
    "telugu": {
        "label": "తెలుగు",
        "body": ("నమస్కారం {name},\n"
                 "{shop}: మీ ఖాతాలో ₹{amount} బకాయి ఉంది.\n"
                 "దయచేసి చెల్లించండి."),
        "pay": "చెల్లించండి: {link}",
    },
    "marathi": {
        "label": "मराठी",
        "body": ("नमस्कार {name},\n"
                 "{shop}: तुमचे ₹{amount} बाकी आहेत.\n"
                 "कृपया पेमेंट करा."),
        "pay": "पेमेंट करा: {link}",
    },
    "gujarati": {
        "label": "ગુજરાતી",
        "body": ("નમસ્તે {name},\n"
                 "{shop}: તમારા ₹{amount} બાકી છે.\n"
                 "કૃપા કરીને પેમેન્ટ કરો."),
        "pay": "પેમેન્ટ કરો: {link}",
    },
}


def languages() -> list[dict]:
    return [{"key": key, "label": value["label"]} for key, value in TEMPLATES.items()]


def compose(name: str, amount: float, shop: str, language: str, link: Optional[str]) -> str:
    """The exact text that will be sent. Deterministic, and stored verbatim."""
    template = TEMPLATES.get(language, TEMPLATES["hinglish"])
    message = template["body"].format(
        name=name, shop=shop, amount=f"{amount:,.0f}"
    )
    if link:
        message += "\n" + template["pay"].format(link=link)
    return message


# ------------------------------------------------------------------ people

def _find(identifier: str) -> Optional[dict]:
    """By customer id, or by name the way a merchant would actually say it."""
    needle = identifier.strip().lower()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM khata_customers").fetchall()
    for row in rows:
        if row["customer_id"].lower() == needle:
            return dict(row)
    for row in rows:
        name = row["name"].lower()
        if name == needle or name in needle or needle in name:
            return dict(row)
    return None


def outstanding() -> list[dict]:
    """Everyone who owes something, most owed first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM khata_customers WHERE balance > 0 ORDER BY balance DESC"
        ).fetchall()
    return db.rows_to_dicts(rows)


def set_contact(
    identifier: str, phone: Optional[str] = None, language: Optional[str] = None
) -> dict:
    customer = _find(identifier)
    if customer is None:
        raise CollectionError(f"No khata customer matching '{identifier}'.")
    if language and language not in TEMPLATES:
        raise CollectionError(
            f"Unknown language '{language}'. Use one of: {', '.join(TEMPLATES)}."
        )

    with db.connect() as conn:
        if phone is not None:
            conn.execute(
                "UPDATE khata_customers SET phone = ? WHERE customer_id = ?",
                (phone.strip() or None, customer["customer_id"]),
            )
        if language:
            conn.execute(
                "UPDATE khata_customers SET language = ? WHERE customer_id = ?",
                (language, customer["customer_id"]),
            )
    return _find(customer["customer_id"]) or customer


def _recently_reminded(customer: dict) -> bool:
    stamp = customer.get("last_reminded_at")
    if not stamp:
        return False
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(hours=COOLDOWN_HOURS)


# ---------------------------------------------------------------- the act

def remind(identifier: str, *, shop: str, force: bool = False) -> dict:
    """
    Chase one customer.

    Raises CollectionError when the reminder should not be sent at all, and
    returns a result with `delivered: False` when it should have been sent but
    the channel failed. Those are different problems and the merchant needs to
    tell them apart: one is "don't", the other is "couldn't".
    """
    customer = _find(identifier)
    if customer is None:
        raise CollectionError(f"No khata customer matching '{identifier}'.")

    balance = float(customer.get("balance") or 0)
    if balance <= 0:
        raise CollectionError(
            f"{customer['name']} ka khata clear hai. Kuch baaki nahi."
        )

    if not force and _recently_reminded(customer):
        raise CollectionError(
            f"{customer['name']} ko pehle hi yaad dila diya hai aaj. "
            f"Dobara bhejne ke liye force karein."
        )

    if not customer.get("phone"):
        raise CollectionError(
            f"{customer['name']} ka phone number nahi hai. "
            f"Pehle number add karein."
        )

    reminder_id = f"REM_{uuid.uuid4().hex[:8].upper()}"
    link = payment_link(customer["customer_id"], reminder_id)
    language = customer.get("language") or "hinglish"
    message = compose(customer["name"], balance, shop, language, link)

    delivered = False
    detail = ""
    try:
        result = messaging.send(message, to=customer["phone"])
        delivered = True
        detail = f"{result.get('channel')} {result.get('status')} {result.get('sid')}"
    except messaging.MessagingNotConfigured as exc:
        detail = str(exc)
    except messaging.MessagingError as exc:
        detail = str(exc)
    except Exception as exc:  # noqa: BLE001 - a send must not 500 the route
        detail = f"Unexpected {type(exc).__name__}."

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO reminders(reminder_id, customer_id, name, amount, channel,"
            " message, pay_link, delivered, detail, sent_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                reminder_id, customer["customer_id"], customer["name"], balance,
                messaging.status().get("channel", "sms"),
                message, link, int(delivered), detail, now,
            ),
        )
        # The cooldown counts attempts, not successes: a failed send that is
        # retried in a loop would otherwise become a stream of duplicates the
        # moment the channel recovers.
        conn.execute(
            "UPDATE khata_customers SET last_reminded_at = ?,"
            " reminder_count = reminder_count + 1 WHERE customer_id = ?",
            (now, customer["customer_id"]),
        )

    return {
        "reminder_id": reminder_id,
        "customer": customer["name"],
        "customer_id": customer["customer_id"],
        "amount": round(balance, 2),
        "language": language,
        "message": message,
        "pay_link": link,
        "delivered": delivered,
        "detail": detail,
        "sent_at": now,
    }


def history(limit: int = 20) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{**dict(r), "delivered": bool(r["delivered"])} for r in rows]


def snapshot() -> dict:
    """What the Money page needs: who owes, and what has been chased."""
    people = outstanding()
    return {
        "outstanding": people,
        "total_outstanding": round(sum(float(p["balance"]) for p in people), 2),
        "chaseable": [p for p in people if p.get("phone")],
        "missing_phone": [p["name"] for p in people if not p.get("phone")],
        "recent_reminders": history(10),
        "languages": languages(),
        "cooldown_hours": COOLDOWN_HOURS,
        "pay_link_configured": bool(link_base()),
    }


# ------------------------------------------------------------------ voice

# "Kumar ko yaad dilao", "Sagar ko yaad dila do", "remind Sujit".
# Deliberately narrow: this branch sends a message to somebody's customer, so
# it fires on an explicit instruction to chase and on nothing else.
CHASE_MARKERS = ("yaad dila", "yaad dilao", "yaad dilana", "remind", "paise mango",
                 "payment mango", "udhaar mango", "chase")


def detect_reminder(text: str) -> Optional[str]:
    """
    The customer named in a chase instruction, or None.

    Parsed by splitting rather than a regex: the two shapes a merchant
    actually uses are "<name> ko yaad dilao" and "remind <name>", and both are
    a single token next to a known word.
    """
    lower = " ".join(text.lower().split())
    if not any(marker in lower for marker in CHASE_MARKERS):
        return None

    # "<name> ko yaad dilao" - the name sits immediately before " ko ".
    if " ko " in f" {lower} ":
        before = lower.split(" ko ")[0].strip().split()
        if before:
            return before[-1]

    # "remind <name>" / "chase <name>"
    for marker in ("remind", "chase"):
        if marker in lower:
            after = lower.split(marker, 1)[1].strip().split()
            if after:
                return after[0]

    return None
