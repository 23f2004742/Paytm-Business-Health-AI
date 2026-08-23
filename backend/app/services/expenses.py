"""
Expense store: the money-out half of the ledger.

Backed by SQLite (see db.py). The function signatures are unchanged from the
JSON version, so nothing above this module knows or cares.

Why this exists
------------------------------------------------------------------------------
Payments data knows everything about money coming IN and nothing at all about
money going OUT. A shop's books are not one column. The wholesaler paid in
cash, the electricity bill, the tempo that brought the stock, the boy who
helps on Sundays: none of it touches a Paytm QR, so none of it is anywhere in
the transaction dataset.

A munim keeps all three columns. That is the difference between a payments
dashboard and a shop's books, so money out is recorded here the only way it
realistically can be on a shop floor: the merchant says it out loud.

Nothing in this module computes a health score or an insight. It stores what
was said, with the transcript kept alongside every row so a merchant can see
why a number is what it is.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from . import db

# The spending a kirana actually has. Used to label a row, never to guess an
# amount: the amount always comes from what the merchant said.
CATEGORIES = {
    "stock": "Stock & supplier",
    "utilities": "Bills & utilities",
    "rent": "Rent",
    "salary": "Staff",
    "transport": "Transport",
    "other": "Other",
}

# Ordered: the first match wins, so the more specific words come first.
CATEGORY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("utilities", ("bijli", "electricity", "light bill", "phone bill", "recharge",
                   "internet", "wifi", "gas", "cylinder", "pani", "water bill")),
    ("rent", ("kiraya", "kirya", "rent", "dukaan ka kiraya", "shop rent")),
    ("salary", ("salary", "tankhwah", "tankha", "pagar", "staff", "naukar",
                "helper", "ladke ko", "labour")),
    ("transport", ("tempo", "transport", "auto", "delivery charge", "petrol",
                   "diesel", "bhada", "freight", "loading")),
    ("stock", ("supplier", "wholesale", "wholesaler", "maal", "stock", "godown",
               "distributor", "agency", "mandi", "purchase", "kharida", "order")),
)


def categorise(text: str) -> str:
    """Label a spend from the words used. Falls back to `other`, never guesses."""
    lower = text.lower()
    for category, markers in CATEGORY_MARKERS:
        if any(marker in lower for marker in markers):
            return category
    return "other"


def record(
    amount: float,
    *,
    transcript: str,
    merchant_id: str,
    payee: Optional[str] = None,
    category: Optional[str] = None,
    source: str = "voice",
) -> dict:
    """One spend, as spoken. The transcript is kept so the row can be audited."""
    row = {
        "expense_id": f"EXP_{uuid.uuid4().hex[:10]}",
        "merchant_id": merchant_id,
        "amount": round(float(amount), 2),
        "category": category or categorise(transcript),
        "payee": payee,
        "transcript": transcript,
        "source": source,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO expenses(expense_id, merchant_id, amount, category, payee,"
            " transcript, source, recorded_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                row["expense_id"], row["merchant_id"], row["amount"], row["category"],
                row["payee"], row["transcript"], row["source"], row["recorded_at"],
            ),
        )
    return row


def list_expenses(merchant_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        if merchant_id:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE merchant_id = ?"
                " ORDER BY recorded_at DESC LIMIT ?",
                (merchant_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses ORDER BY recorded_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return db.rows_to_dicts(rows)


def totals(merchant_id: Optional[str] = None) -> dict:
    """
    Money out, split the way a merchant asks about it: today, and all of it.

    `by_category` is sorted biggest first, because the useful question is
    always "where is it going", and the answer is the top row.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    where = "WHERE merchant_id = ?" if merchant_id else ""
    args: tuple = (merchant_id,) if merchant_id else ()

    with db.connect() as conn:
        overall = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) total, COUNT(*) count FROM expenses {where}",
            args,
        ).fetchone()

        # substr(recorded_at, 1, 10) is the ISO date. Comparing the prefix keeps
        # this a plain index-friendly string compare instead of date parsing.
        today_row = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) total, COUNT(*) count FROM expenses"
            f" {where}{' AND' if where else ' WHERE'} substr(recorded_at, 1, 10) = ?",
            (*args, today),
        ).fetchone()

        grouped = conn.execute(
            f"SELECT category, SUM(amount) amount FROM expenses {where}"
            " GROUP BY category ORDER BY amount DESC",
            args,
        ).fetchall()

        largest = conn.execute(
            f"SELECT * FROM expenses {where} ORDER BY amount DESC LIMIT 1", args
        ).fetchone()

    return {
        "total": round(float(overall["total"]), 2),
        "today": round(float(today_row["total"]), 2),
        "count": int(overall["count"]),
        "count_today": int(today_row["count"]),
        "by_category": [
            {
                "category": row["category"],
                "label": CATEGORIES.get(row["category"], row["category"]),
                "amount": round(float(row["amount"]), 2),
            }
            for row in grouped
        ],
        "largest": dict(largest) if largest else None,
        "recent": list_expenses(merchant_id, limit=5),
    }


def reset() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM expenses")
