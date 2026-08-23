"""
Insights API.

Two levels, deliberately kept separate:

  /api/insights           transaction-only ranking (the original engine)
  /api/insights/unified   transaction + shop-floor, joined on time

and /api/ask-ai, which answers from a context containing both.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models.schemas import AskRequest
from ..services import ai_engine
from ..services.anomaly_detection import detect
from ..services.insights import insights_payload
from ..services.recommendation_engine import build_action_plan
from ..services.unified_insights import unified_payload
from .deps import contexts, demand_summary, scored_health, week_events

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/insights")
def get_insights() -> dict:
    ctx, prev = contexts()
    payload = insights_payload(ctx)
    payload["health"] = scored_health(ctx, prev)
    payload["hourly_distribution"] = ctx.hourly_distribution()
    payload["weekday_comparison"] = ctx.weekday_comparison()
    return payload


@router.get("/insights/unified")
def get_unified_insights() -> dict:
    ctx, prev = contexts()
    anomalies = detect(ctx)
    events = week_events(ctx)

    payload = unified_payload(ctx, anomalies, events)
    payload["health"] = scored_health(ctx, prev)
    payload["hourly_distribution"] = ctx.hourly_distribution()
    payload["demand"] = demand_summary(ctx, events)
    return payload


@router.post("/ask-ai")
def ask_ai(request: AskRequest) -> dict:
    ctx, prev = contexts()
    health = scored_health(ctx, prev)
    insights = insights_payload(ctx)
    events = week_events(ctx)
    demand = demand_summary(ctx, events)
    unified = unified_payload(ctx, detect(ctx), events)
    plan = build_action_plan(ctx, demand, health["overall_score"])

    context = ai_engine.build_ai_context(
        ctx, health, insights["insights"], plan["campaign"], demand, unified
    )
    result = ai_engine.answer(request.question, context)

    return {
        "question": request.question,
        **result,
        "context_used": {
            "health_score": health["overall_score"],
            "score_change": health["change"],
            "findings": len(insights["insights"]),
            "shop_requests": demand["total_requests"],
            "unfulfilled_requests": demand["unfulfilled_requests"],
        },
        "suggested_questions": ai_engine.SUGGESTED_QUESTIONS,
    }


@router.get("/ai/suggestions")
def ai_suggestions() -> dict:
    return {
        "questions": ai_engine.SUGGESTED_QUESTIONS,
        "provider": ai_engine.provider_status(),
    }
