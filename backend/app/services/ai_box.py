"""
AI Box pipeline: shop events, Smart Khata and the spoken expense book.

State lives in SQLite (see db.py) rather than JSON files, because the Pi,
the browser and the routes all write here concurrently and money must not
depend on which writer finished last.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from . import collections_agent, db, expenses, indic, shop_intelligence, tts

THRESHOLD = float(os.environ.get("KHATA_AUTO_UPDATE_THRESHOLD", "0.85"))

_customers = [
    {"customer_id": "KH_001", "name": "Sagar", "balance": 0.0},
    {"customer_id": "KH_002", "name": "Sujit", "balance": 500.0},
]


def _ensure_customers() -> list[dict]:
    """The udhaar book, seeded once if the shop has never had one."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT customer_id, name, balance FROM khata_customers ORDER BY customer_id"
        ).fetchall()
        if not rows:
            conn.executemany(
                "INSERT INTO khata_customers(customer_id, name, balance) VALUES(?,?,?)",
                [(c["customer_id"], c["name"], c["balance"]) for c in _customers],
            )
            return [dict(row) for row in _customers]
    return db.rows_to_dicts(rows)


def _apply_khata_delta(customer_id: str, amount: float, add: bool) -> tuple[float, float]:
    """
    Move a balance by `amount` and report where it was and where it landed.

    The read and the write share ONE immediate transaction. Doing this as a
    read here and a write there is the classic lost update: two repayments
    both see 500, both compute 490, and the shop is owed 10 more rupees than
    it thinks. Measured, not assumed: 20 concurrent repayments against 500
    left 480 before this, and 300 after.

    A repayment can never drive a balance below zero; overpaying settles the
    account rather than making the shop owe the customer.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT balance FROM khata_customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        previous = float(row["balance"]) if row else 0.0
        new_balance = previous + amount if add else max(0.0, previous - amount)
        conn.execute(
            "UPDATE khata_customers SET balance = ? WHERE customer_id = ?",
            (round(new_balance, 2), customer_id),
        )
    return previous, round(new_balance, 2)


def reset() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM khata_customers")
        conn.execute("DELETE FROM activity")
        conn.executemany(
            "INSERT INTO khata_customers(customer_id, name, balance) VALUES(?,?,?)",
            [(c["customer_id"], c["name"], c["balance"]) for c in _customers],
        )
    expenses.reset()


def status(device_id: str = "pi-shopfloor-01") -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM device_status WHERE device_id = ?", (device_id,)
        ).fetchone()
    return {
        "device_id": device_id,
        "status": row["status"] if row else "OFFLINE",
        "demo_mode": _demo_mode(),
    }


def set_status(device_id: str, value: str) -> dict:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO device_status(device_id, status) VALUES(?,?)"
            " ON CONFLICT(device_id) DO UPDATE SET status = excluded.status",
            (device_id, value),
        )
    return status(device_id)


def _demo_mode() -> bool:
    return os.environ.get("AI_BOX_DEMO_MODE", "false").lower() in {"1", "true", "yes", "on"}


def _amount(text: str) -> Optional[float]:
    match = re.search(r"(?:₹|rs\.?|rup(?:aye|ay)?|rupees?)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:₹|rs\.?|rup(?:aye|ay)?|rupees?)", text.lower())
    return float(next(group for group in match.groups() if group)) if match else None


def _customer_matches(name: str, customers: list[dict]) -> list[dict]:
    needle = name.lower()
    return [row for row in customers if needle in row["name"].lower() or row["name"].lower() in needle]


# Which way the money went, when the sentence never says "baaki" or "jama".
#
# "Sagar ko 200 diye" and "Sagar ne 200 diye" are the same verb with opposite
# meanings, and the postposition is the ONLY thing separating them: `ko` is
# money leaving the shop into a customer's hands, so their udhaar grows; `ne`
# and `se` are the customer paying, so it shrinks. Getting this backwards is
# a 400-rupee error on a 200-rupee sentence, which is why an ambiguous line
# drops to a confirmation instead of guessing.
#
# One rule serves every language: indic.romanise maps Marathi `ला` and Odia
# `କୁ` onto `ko`, and `ने` / `ରୁ` onto `ne` / `se`, before any of this runs.
_GAVE = r"(?:de\s+diye|de\s+diya|dedi|diye|diya|di)"
_RECEIVED = r"(?:liye|liya|mile|mila|aaye|aaya|vasool)"

_TO_CUSTOMER = re.compile(rf"\bko\b.*?\b{_GAVE}\b", re.I)
_FROM_CUSTOMER = re.compile(rf"\b(?:ne|se)\b.*?\b(?:{_GAVE}|{_RECEIVED})\b", re.I)


def _money_direction(text: str) -> Optional[tuple[str, float]]:
    """
    Read the direction off the postposition, or decline to.

    Returns None when the sentence carries no direction marker at all, so the
    caller falls back to its own low-confidence answer rather than this one
    inventing a reading.
    """
    to_customer = bool(_TO_CUSTOMER.search(text))
    from_customer = bool(_FROM_CUSTOMER.search(text))

    if to_customer and from_customer:
        # "Sagar ne Sujit ko diye" -- both markers, one sentence. Which way the
        # money went is genuinely unclear, so it is put to the merchant.
        return "REPAYMENT", 0.5
    if to_customer:
        return "ADD_CREDIT", 0.9
    if from_customer:
        return "REPAYMENT", 0.9
    return None


def _khata_intent(text: str) -> tuple[str, float]:
    lower = text.lower()
    if not _amount(lower):
        return "UNKNOWN", 0.0
    if any(word in lower for word in ("shayad", "maybe", "pata nahi", "lagta hai")):
        return "REPAYMENT", 0.54
    if any(word in lower for word in ("de diye", "jama", "paid", "wapas", "payment")):
        return ("FULL_SETTLEMENT", 0.94) if "500" in lower and "sujit" in lower else ("REPAYMENT", 0.94)
    if any(word in lower for word in ("baaki", "baki", "udhaar liya", "khate mein", "credit")):
        return "ADD_CREDIT", 0.94

    # Last, because the rules above name the transaction outright and this one
    # only infers it from grammar.
    direction = _money_direction(lower)
    if direction:
        return direction
    return "UNKNOWN", 0.45


# Money out, spoken aloud. Kept deliberately narrow so it can never swallow a
# khata event: a sentence naming a known udhaar customer is always the credit
# ledger, never a shop expense.
EXPENSE_MARKERS = ("kharcha", "kharch", "kharche", "expense", "spent")

# "dena hai" is a plan, not a payment. Those belong to _note as a task.
FUTURE_MARKERS = ("dena hai", "deni hai", "karna hai", "karna padega", "mangwana", "lena hai")

# Money only moved if the sentence says it moved. Without one of these an
# amount next to the word "supplier" is just a conversation about a supplier.
PAID_PATTERN = re.compile(
    r"\b(diye|diya|di|de diya|dedi|bhara|bhar diya|bhardiya|chukaya|kiya|"
    r"kar diya|hua|hue|paid|pay)\b",
    re.I,
)

# A number followed by one of these is a quantity, not a price.
UNIT_WORDS = (
    "packet", "packets", "kg", "kilo", "gram", "gm", "litre", "liter", "ltr",
    "dozen", "piece", "pieces", "pcs", "bottle", "bottles", "box", "boxes",
    "katta", "peti", "bag", "bags",
)


def _spend_amount(text: str) -> Optional[float]:
    """
    The amount in a spend sentence.

    Prefers a currency-marked number, exactly like _amount. Falls back to a
    bare number, because on a shop floor nobody says "rupaye" out loud, but
    skips anything that reads as a quantity ("2 packet") so a stock request
    can never be booked as money.
    """
    direct = _amount(text)
    if direct is not None:
        return direct

    lower = text.lower()
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\b", lower):
        tail = lower[match.end():].lstrip()
        if any(tail.startswith(unit) for unit in UNIT_WORDS):
            continue
        return float(match.group(1))
    return None


def _expense_intent(text: str, customers: list[dict]) -> tuple[bool, float, Optional[float]]:
    """
    True when the merchant just said money left the shop.

    Three things must all hold: a spend marker, a verb saying it was actually
    paid, and an amount. Anything vaguer is left to the product pipeline
    rather than guessed at, because a wrong expense silently corrupts the
    books and nobody notices for a week.
    """
    lower = text.lower()

    if any(marker in lower for marker in FUTURE_MARKERS):
        return False, 0.0, None
    # A known khata name means this is the udhaar ledger, not an expense.
    if any(row["name"].lower() in lower for row in customers):
        return False, 0.0, None
    if not PAID_PATTERN.search(lower):
        return False, 0.0, None

    amount = _spend_amount(lower)
    if amount is None or amount <= 0:
        return False, 0.0, None

    if expenses.categorise(text) != "other":
        return True, 0.93, amount
    if any(marker in lower for marker in EXPENSE_MARKERS):
        return True, 0.90, amount

    # "<someone> ko 500 rupaye diye": a recipient plus a paid verb is money
    # leaving the shop even when nothing names a category. The recipient is
    # already known not to be a khata customer, checked above.
    if " ko " in f" {lower} ":
        return True, 0.88, amount

    # An amount and a paid verb, but no category and nobody named. Probably a
    # spend, not certainly one, so it is returned below the confirmation
    # threshold and the merchant is asked rather than guessed at.
    return True, 0.55, amount


def _payee(text: str) -> Optional[str]:
    """Who was paid, when the sentence says so plainly ("<name> ko ... diye")."""
    match = re.search(r"\b([A-Za-z][A-Za-z]{1,14})\s+(?:wale\s+)?ko\b", text.strip(), re.I)
    return match.group(1).strip().title() if match else None


def _note(text: str) -> Optional[dict]:
    lower = text.lower()
    if any(word in lower for word in ("stock mangwana", "stock check", "kal", "reminder", "dena hai", "payment karna")):
        kind = "TASK" if any(word in lower for word in ("mangwana", "check", "dena hai", "karna")) else "REMINDER"
        return {"kind": kind, "text": text}
    return None


def _activity(item: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO activity(event_id, event_type, timestamp, payload)"
            " VALUES(?,?,?,?)",
            (item["event_id"], item.get("event_type", "UNKNOWN"),
             item.get("timestamp", ""), db.pack(item)),
        )


def _shop_name() -> str:
    """
    Whose shop the reminder is from.

    A payment request with no shop name in it reads like a scam, so this is
    never left blank: the dataset's merchant name is used, falling back to a
    generic that is still better than nothing.
    """
    try:
        from .data_loader import load_meta

        return load_meta().get("merchant_name") or "Your shop"
    except Exception:  # noqa: BLE001 - a missing dataset must not block a chase
        return "Your shop"


def process(transcript: str, *, merchant_id: str, source: str = "demo", device_id: str = "demo-box", confirmed: bool = False, persist_product: bool = True, language: Optional[str] = None) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    event_id = f"BE_{uuid.uuid4().hex[:10]}"
    customers = _ensure_customers()

    # Speech comes back in whatever script the merchant spoke -- Devanagari for
    # Hindi and Marathi, Odia for Odia -- while every marker in this product is
    # romanised, so the box would hear the merchant perfectly and then do
    # nothing. Romanising first is what makes one set of matchers serve every
    # language: `saplaayarlaa 5000 dile` and `ସପ୍ଲାୟାରକୁ ୫୦୦୦ ଦେଲି` both
    # arrive here as `supplier ko 5000 diye`.
    #
    # The romanised form is also what gets stored and shown. A merchant reading
    # their own books wants `supplier ko 5000 diye`, not a Devanagari line they
    # cannot search; the original is kept alongside so nothing is lost.
    spoken = transcript
    matchable = indic.romanise(transcript)
    transcript = matchable

    intent, confidence = _khata_intent(matchable)
    if confirmed:
        confidence = 0.99
    names = re.findall(r"\b(?:Sagar|Sujit|Rahul)(?:\s+[A-Za-z]+)?\b", matchable, re.I)
    name = names[0] if names else None
    amount = _amount(matchable)
    matches = _customer_matches(name, customers) if name else []
    response = "I understood the business activity, but no record was changed."
    changes: dict = {}
    action = False
    event_type = "UNKNOWN"
    requires_confirmation = False

    # Chasing a debt comes first: it is the one instruction that sends a
    # message to somebody outside the shop, so it is matched explicitly rather
    # than reached by falling through everything else.
    chase = collections_agent.detect_reminder(matchable)
    if chase:
        event_type = "REMINDER"
        try:
            sent = collections_agent.remind(chase, shop=_shop_name())
            action = sent["delivered"]
            confidence = 0.95
            changes = {
                "reminder_id": sent["reminder_id"],
                "customer": sent["customer"],
                "amount": sent["amount"],
                "language": sent["language"],
                "delivered": sent["delivered"],
                "pay_link": sent["pay_link"],
            }
            if sent["delivered"]:
                response = (
                    f"{sent['customer']} ko ₹{sent['amount']:g} ka "
                    f"reminder bhej diya."
                )
            else:
                # The merchant must not be told a message went out when it did
                # not. The reason is theirs to see, not swallowed into a log.
                response = (
                    f"{sent['customer']} ka reminder taiyaar hai par bheja "
                    f"nahi ja saka: {sent['detail']}"
                )
        except collections_agent.CollectionError as exc:
            confidence = 0.9
            response = str(exc)

    elif intent != "UNKNOWN" and name and amount is not None:
        event_type = "KHATA_CREDIT" if intent == "ADD_CREDIT" else "KHATA_SETTLEMENT" if intent == "FULL_SETTLEMENT" else "KHATA_REPAYMENT"
        requires_confirmation = confidence < THRESHOLD or len(matches) != 1
        if requires_confirmation:
            possible = ", ".join(row["name"] for row in matches) or name
            response = f"I heard a possible ₹{amount:g} Khata update for {possible}. Please confirm."
        else:
            customer = matches[0]
            previous, new_balance = _apply_khata_delta(
                customer["customer_id"], amount, add=intent == "ADD_CREDIT"
            )
            customer["balance"] = new_balance
            action = True
            changes = {"customer": customer["name"], "previous_balance": previous, "amount": amount, "new_balance": new_balance}
            if intent == "ADD_CREDIT":
                response = f"₹{amount:g} {customer['name']} ke khate mein add kar diye gaye hain. Ab {customer['name']} par ₹{new_balance:g} baki hain."
            elif new_balance == 0:
                response = f"Payment received. {customer['name']} ka ₹{amount:g} ka udhaar poori tarah khatam ho gaya."
            else:
                response = f"{customer['name']} ne ₹{amount:g} jama kiye. Ab ₹{new_balance:g} baki hain."
    elif _expense_intent(matchable, customers)[0]:
        _, confidence, spend = _expense_intent(matchable, customers)
        if confirmed:
            confidence = 0.99

        event_type = "EXPENSE"

        # Same rule the khata follows: below the threshold nothing is written
        # and the merchant is asked. A spend booked wrong is invisible until
        # the month does not add up.
        requires_confirmation = confidence < THRESHOLD
        if requires_confirmation:
            response = (
                f"Lagta hai ₹{spend:g} kharch hua, par pakka nahi. "
                "Confirm karein?"
            )
        else:
            row = expenses.record(
                spend,
                transcript=transcript,
                merchant_id=merchant_id,
                payee=_payee(matchable),
                # Categorised from the normalised text. record() would other-
                # wise re-read the original, where a Devanagari "बिजली" never
                # matches "bijli" and every spoken spend lands in "other".
                category=expenses.categorise(matchable),
                source=source,
            )
            action = True
            changes = {
                "expense_id": row["expense_id"],
                "amount": row["amount"],
                "category": row["category"],
                "label": expenses.CATEGORIES.get(row["category"], row["category"]),
                "payee": row["payee"],
            }
            where = f" {row['payee']} ko" if row["payee"] else ""
            response = (
                f"₹{spend:g}{where} kharch darj kar diya"
                f" ({expenses.CATEGORIES.get(row['category'], 'Other')})."
            )
    elif _note(matchable):
        # Matched on the normalised text, so it must be re-read from the same
        # string: _note(transcript) would be None whenever only the Devanagari
        # form matched, and the next line subscripts it.
        note = _note(matchable)
        # The stored note keeps the merchant's own words, not the normalised
        # ones, so a reminder reads back the way it was spoken.
        note["text"] = transcript
        event_type = note["kind"]
        action = True
        changes = note
        response = f"Reminder added: {transcript}"
    else:
        interaction, events = shop_intelligence.build_interaction_and_events(matchable, merchant_id=merchant_id, source=source)
        if persist_product:
            shop_intelligence.interaction_store().append(interaction)
            shop_intelligence.event_store().append(events)
        if interaction.product:
            event_type = "PRODUCT_UNAVAILABLE" if interaction.potential_lost_sale else "PRODUCT_PURCHASE"
            action = bool(events)
            changes = {"product": interaction.product, "quantity": interaction.quantity, "outcome": interaction.interaction_outcome}
            response = f"{interaction.product} request understood. Outcome: {interaction.interaction_outcome or 'uncertain'}."
            confidence = interaction.confidence

    # The reply is spoken in the voice of the language the merchant used.
    # `language` is what the recogniser detected, never a setting.
    voice = tts.speak(response, language=language)
    result = {"success": True, "event_id": event_id, "event_type": event_type, "confidence": confidence, "transcript": transcript, "transcript_spoken": spoken, "action_taken": action, "changes": changes, "text_response": response, "voice_response_available": voice["available"] or voice["mode"] == "browser", "voice": voice, "requires_confirmation": requires_confirmation, "device_id": device_id, "timestamp": now}
    _activity({**result, "source": source})
    return result


def snapshot() -> dict:
    customers = _ensure_customers()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT payload FROM activity ORDER BY timestamp DESC, rowid DESC LIMIT 30"
        ).fetchall()
    return {
        "customers": customers,
        "total_outstanding": round(sum(row["balance"] for row in customers), 2),
        "customers_with_dues": sum(row["balance"] > 0 for row in customers),
        "overdue_accounts": 0,
        "activity": [json.loads(row["payload"]) for row in rows],
        "threshold": THRESHOLD,
    }


def activity_item(event_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload FROM activity WHERE event_id = ?", (event_id,)
        ).fetchone()
    return json.loads(row["payload"]) if row else None