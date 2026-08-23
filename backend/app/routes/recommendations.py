"""
Recommendations and merchant actions.

Three action types: campaign, restock, and the combined sequence. Restock
alerts are created here; campaigns live in campaigns.py because they carry
their own lifecycle.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import RestockRequest
from ..services import campaigns, demand_analysis, notifications, restock
from ..services.recommendation_engine import build_action_plan
from .deps import contexts, demand_summary, merchant, scored_health, week_events

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendation")
def get_recommendation() -> dict:
    """
    The single campaign recommendation.

    Kept at its original path and shape so the campaign flow stays stable;
    /api/actions is the richer, multi-action view.
    """
    ctx, prev = contexts()
    health = scored_health(ctx, prev)
    demand = demand_summary(ctx)
    plan = build_action_plan(ctx, demand, health["overall_score"])

    recommendation = plan["campaign"]
    recommendation["already_active"] = bool(
        campaigns.active_campaign(merchant()["merchant_id"])
    )
    return recommendation


@router.get("/actions")
def get_actions() -> dict:
    """Every action available this week, with the primary one named."""
    ctx, prev = contexts()
    profile = merchant()
    health = scored_health(ctx, prev)
    events = week_events(ctx)
    demand = demand_summary(ctx, events)

    plan = build_action_plan(ctx, demand, health["overall_score"])
    open_alerts = restock.active_alerts(profile["merchant_id"])
    open_products = {a["product"].lower() for a in open_alerts}

    for action in plan["actions"]:
        if action["type"] == "restock":
            action["already_created"] = action["product"].lower() in open_products
        elif action["type"] == "campaign":
            action["already_active"] = bool(
                campaigns.active_campaign(profile["merchant_id"])
            )

    return {
        **plan,
        "current_score": health["overall_score"],
        "active_campaign": campaigns.active_campaign(profile["merchant_id"]),
        "open_restock_alerts": open_alerts,
    }


@router.get("/restock-alerts")
def get_restock_alerts() -> dict:
    merchant_id = merchant()["merchant_id"]
    return {
        "alerts": restock.list_alerts(merchant_id),
        "open": restock.active_alerts(merchant_id),
    }


@router.post("/restock-alerts", status_code=201)
def create_restock_alert(request: RestockRequest) -> dict:
    """
    Raise a restock alert for a product the shop floor says is missing.

    The request only names a product; the counts are re-read from the event
    store so a client cannot inflate the evidence behind an alert.
    """
    ctx, prev = contexts()
    profile = merchant()
    events = week_events(ctx)

    rows = demand_analysis.product_demand(events)
    needle = request.product.strip().lower()
    row = next(
        (
            r
            for r in rows
            if r["product"].lower() == needle or r["family"] == needle
        ),
        None,
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No shop-floor demand recorded for '{request.product}'.",
        )

    basket = round(ctx.current.avg_ticket, 2) if ctx.current.txns else None
    health = scored_health(ctx, prev)

    existing_ids = {a["alert_id"] for a in restock.list_alerts()}

    alert = restock.create_alert(
        {
            "merchant_id": request.merchant_id or profile["merchant_id"],
            "product": row["product"],
            "catalog_items": row["catalog_items"][:5],
            "requests": row["requests"],
            "unfulfilled_requests": row["unfulfilled_requests"],
            "estimated_lost_revenue": demand_analysis.estimate_lost_revenue(
                row["unfulfilled_requests"], basket
            ),
            "priority": "high" if row["unfulfilled_requests"] >= 8 else "medium",
        }
    )

    from ..services.recommendation_engine import project_restock_impact

    # create_alert is idempotent per product, so re-raising an open alert
    # returns the existing one. Texting the merchant again about a restock
    # they have already been told about is noise, so only a fresh alert sends.
    delivery = (
        notifications.notify_restock(alert)
        if alert.get("alert_id") not in existing_ids
        else {"sent": False, "reason": "Alert already open; merchant already notified."}
    )

    return {
        "status": alert["status"],
        "alert_id": alert["alert_id"],
        "message": f"Restock alert created for {alert['product']}.",
        "alert": alert,
        "projection": project_restock_impact(
            ctx, health["overall_score"], float(row["unfulfilled_requests"])
        ),
        "notification": delivery,
    }


@router.post("/restock-alerts/{alert_id}/resolve")
def resolve_restock_alert(alert_id: str) -> dict:
    alert = restock.resolve_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"No restock alert {alert_id}")
    return {"status": alert["status"], "alert": alert}
