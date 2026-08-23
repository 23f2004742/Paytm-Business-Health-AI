"""
Restock alert store.

The second merchant action, alongside launching a campaign. Persisted in
SQLite (see db.py); function signatures are unchanged from the JSON version.

A restock alert is a record that the merchant acknowledged unmet demand. It
does not place an order with anyone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import db


def _rows(merchant_id: Optional[str] = None) -> list[dict]:
    with db.connect() as conn:
        if merchant_id:
            rows = conn.execute(
                "SELECT payload FROM restock_alerts WHERE merchant_id = ?"
                " ORDER BY created_at DESC",
                (merchant_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM restock_alerts ORDER BY created_at DESC"
            ).fetchall()
    return [db.unpack(row) for row in rows]


def list_alerts(merchant_id: Optional[str] = None) -> list[dict]:
    return _rows(merchant_id)


def active_alerts(merchant_id: Optional[str] = None) -> list[dict]:
    return [a for a in list_alerts(merchant_id) if a.get("status") == "OPEN"]


def alert_for(product: str, merchant_id: Optional[str] = None) -> Optional[dict]:
    return next(
        (
            a
            for a in list_alerts(merchant_id)
            if a.get("product", "").lower() == product.lower() and a.get("status") == "OPEN"
        ),
        None,
    )


def create_alert(payload: dict) -> dict:
    """Idempotent per product: re-raising an open alert returns the existing one."""
    merchant_id = payload.get("merchant_id", "PAYTM_M_001")
    product = payload.get("product", "")

    with db.connect() as conn:
        # The uniqueness check and the insert share one transaction, so two
        # simultaneous alerts for the same product cannot both be created.
        existing = conn.execute(
            "SELECT payload FROM restock_alerts"
            " WHERE merchant_id = ? AND lower(product) = lower(?) AND status = 'OPEN'",
            (merchant_id, product),
        ).fetchone()
        if existing:
            return db.unpack(existing)

        count = conn.execute("SELECT COUNT(*) c FROM restock_alerts").fetchone()["c"]
        alert = {
            "alert_id": f"RSK_{count + 1:03d}",
            "merchant_id": merchant_id,
            "product": product,
            "catalog_items": payload.get("catalog_items", []),
            "requests": payload.get("requests", 0),
            "unfulfilled_requests": payload.get("unfulfilled_requests", 0),
            "estimated_lost_revenue": payload.get("estimated_lost_revenue"),
            "priority": payload.get("priority", "high"),
            "source": payload.get("source", "shop_intelligence"),
            "status": "OPEN",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        conn.execute(
            "INSERT INTO restock_alerts(alert_id, merchant_id, product, status,"
            " created_at, payload) VALUES(?,?,?,?,?,?)",
            (
                alert["alert_id"], merchant_id, product, "OPEN",
                alert["created_at"], db.pack(alert),
            ),
        )
    return alert


def resolve_alert(alert_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload FROM restock_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if row is None:
            return None

        alert = db.unpack(row)
        alert["status"] = "RESOLVED"
        alert["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE restock_alerts SET status = ?, payload = ? WHERE alert_id = ?",
            ("RESOLVED", db.pack(alert), alert_id),
        )
    return alert


def reset_alerts() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM restock_alerts")
