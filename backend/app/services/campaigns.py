"""
Campaign store.

A simulated Paytm-native campaign action, persisted in SQLite (see db.py).
Function signatures are unchanged from the JSON version.

The full campaign is kept as a payload blob because the shape is defined by
the request model and the projection attached to it; only the fields actually
queried (merchant, status, created_at) are promoted to columns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import db


def _rows(merchant_id: Optional[str] = None) -> list[dict]:
    with db.connect() as conn:
        if merchant_id:
            rows = conn.execute(
                "SELECT payload FROM campaigns WHERE merchant_id = ?"
                " ORDER BY created_at DESC",
                (merchant_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM campaigns ORDER BY created_at DESC"
            ).fetchall()
    return [db.unpack(row) for row in rows]


def list_campaigns(merchant_id: Optional[str] = None) -> list[dict]:
    return _rows(merchant_id)


def active_campaign(merchant_id: Optional[str] = None) -> Optional[dict]:
    return next(
        (c for c in list_campaigns(merchant_id) if c.get("status") == "ACTIVE"),
        None,
    )


def create_campaign(payload: dict, projection: Optional[dict] = None) -> dict:
    with db.connect() as conn:
        # Counted inside the same transaction as the insert, so two concurrent
        # launches cannot both claim CMP_001.
        count = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
        campaign = {
            "campaign_id": f"CMP_{count + 1:03d}",
            "merchant_id": payload.get("merchant_id", "PAYTM_M_001"),
            "campaign_name": payload.get("campaign_name", "Evening Boost"),
            "cashback_amount": payload.get("cashback_amount"),
            "minimum_transaction": payload.get("minimum_transaction"),
            "start_time": payload.get("start_time"),
            "end_time": payload.get("end_time"),
            "target_segment": payload.get(
                "target_segment", "Customers who have bought from you before"
            ),
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "projection": projection or {},
        }
        conn.execute(
            "INSERT INTO campaigns(campaign_id, merchant_id, status, created_at, payload)"
            " VALUES(?,?,?,?,?)",
            (
                campaign["campaign_id"], campaign["merchant_id"], campaign["status"],
                campaign["created_at"], db.pack(campaign),
            ),
        )
    return campaign


def pause_campaign(campaign_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload FROM campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            return None

        campaign = db.unpack(row)
        campaign["status"] = "PAUSED"
        campaign["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE campaigns SET status = ?, payload = ? WHERE campaign_id = ?",
            ("PAUSED", db.pack(campaign), campaign_id),
        )
    return campaign


def reset_campaigns() -> None:
    """Clears the store so a demo can be run again from a clean slate."""
    with db.connect() as conn:
        conn.execute("DELETE FROM campaigns")
