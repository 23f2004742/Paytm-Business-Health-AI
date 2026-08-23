"""
Dashboard API.

One payload for the unified home screen: payment intelligence and shop-floor
intelligence side by side, plus the joined narrative that neither source
could produce alone.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..services import (
    ai_engine,
    campaigns,
    money_flow,
    notifications,
    restock,
    shop_intelligence,
)
from ..services.anomaly_detection import detect
from ..services.insights import insights_payload
from ..services.transaction_analytics import today_snapshot
from ..services.unified_insights import unified_payload
from .deps import contexts, demand_summary, merchant, scored_health, week_events

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/merchant")
def get_merchant() -> dict:
    return merchant()


@router.get("/dashboard")
def get_dashboard() -> dict:
    ctx, prev = contexts()
    profile = merchant()

    health = scored_health(ctx, prev)
    insights = insights_payload(ctx)
    anomalies = detect(ctx)

    events = week_events(ctx)
    demand = demand_summary(ctx, events)
    unified = unified_payload(ctx, anomalies, events)

    top_shop = demand["high_demand_products"][:1]
    out_of_stock = demand["out_of_stock_requests"][:3]

    return {
        "merchant": profile,
        "health": health,

        # The three columns a munim keeps. Two of them exist only because the
        # merchant said them out loud; neither is in the payments data.
        "money": money_flow.money_flow(ctx, demand, profile["merchant_id"]),
        "today": today_snapshot(ctx),
        "week": {
            "revenue": round(ctx.current.revenue, 2),
            "revenue_change": ctx.revenue_growth_wow,
            "transactions": ctx.current.txns,
            "transactions_change": ctx.txn_growth_wow,
            "average_transaction": round(ctx.current.avg_ticket, 2),
            "average_transaction_change": ctx.avg_ticket_vs_baseline,
            "customers": ctx.customers_current["total_customers"],
        },
        "revenue_trend": ctx.revenue_trend(30),
        "what_changed": insights["insights"][:3],

        # Shop-floor block: the half of the story the ledger cannot see.
        "shop_floor": {
            "total_requests": demand["total_requests"],
            "conversations_captured": demand["conversations_captured"],
            "unfulfilled_requests": demand["unfulfilled_requests"],
            "unique_products": demand["unique_products"],
            "top_demand": top_shop[0] if top_shop else None,
            "out_of_stock": out_of_stock,
            "estimated_lost_revenue": demand["estimated_lost_revenue"],
            "fraud_signals": len(demand["fraud_signals"]),
            "demo_mode": shop_intelligence.demo_mode_enabled(),
        },

        # The joined narrative.
        "ai_summary": unified["headline"],
        "unified_insights": unified["insights"][:3],
        "unified_counts": unified["counts"],

        "active_campaign": campaigns.active_campaign(profile["merchant_id"]),
        "open_restock_alerts": restock.active_alerts(profile["merchant_id"]),
        "ai_provider": ai_engine.provider_status(),
        "notifications": notifications.status(),
    }
