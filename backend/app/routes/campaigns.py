"""Campaign lifecycle and demo reset."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import CampaignRequest
from ..services import campaigns, expenses, notifications, restock, shop_intelligence
from ..services.recommendation_engine import project_score_after
from .deps import contexts, merchant, scored_health

router = APIRouter(prefix="/api", tags=["campaigns"])


@router.get("/campaigns")
def get_campaigns() -> dict:
    merchant_id = merchant()["merchant_id"]
    return {
        "campaigns": campaigns.list_campaigns(merchant_id),
        "active": campaigns.active_campaign(merchant_id),
    }


@router.post("/campaigns", status_code=201)
def post_campaign(request: CampaignRequest) -> dict:
    ctx, prev = contexts()
    health = scored_health(ctx, prev)
    projection = project_score_after(ctx, health["overall_score"])

    campaign = campaigns.create_campaign(request.model_dump(), projection)

    # Announcing the campaign must never be able to fail creating it, so this
    # returns a report rather than raising. See services/notifications.py.
    delivery = notifications.notify_campaign(campaign, projection)

    return {
        "status": campaign["status"],
        "campaign_id": campaign["campaign_id"],
        "message": f"{campaign['campaign_name']} campaign is now active.",
        "campaign": campaign,
        "projection": projection,
        "notification": delivery,
    }


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str) -> dict:
    campaign = campaigns.pause_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail=f"No campaign {campaign_id}")
    return {"status": campaign["status"], "campaign": campaign}


@router.post("/demo/reset")
def reset_demo() -> dict:
    """
    Back to a clean slate: no campaigns, no restock alerts, and the scripted
    shop day re-seeded so the demo can be run again from the top.
    """
    ctx, _ = contexts()
    campaigns.reset_campaigns()
    restock.reset_alerts()
    expenses.reset()

    seeded = 0
    if shop_intelligence.demo_mode_enabled():
        anchor = ctx.anchor.to_pydatetime().replace(hour=23, minute=59, second=59)
        seeded = shop_intelligence.seed_demo_events(
            merchant()["merchant_id"], anchor, replace=True
        )

    return {
        "status": "ok",
        "message": "Demo state reset.",
        "interactions_seeded": shop_intelligence.interaction_store().count(),
        "shop_events_seeded": seeded,
        "demo_mode": shop_intelligence.demo_mode_enabled(),
    }
