"""
Root cause analysis and the merchant copilot.

The two endpoints that answer the merchant's actual questions:
"why did my score drop?" and anything else they want to ask.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models.schemas import AskRequest
from ..services import (
    ai_engine,
    demand_analysis,
    root_cause_analysis,
    transaction_correlation,
)
from ..services.anomaly_detection import detect
from ..services.data_loader import load_transactions
from ..services.insights import insights_payload
from ..services.interaction_outcome_engine import summarise_outcomes
from ..services.recommendation_engine import build_action_plan
from ..services.unified_insights import unified_payload
from .deps import (
    contexts,
    demand_component,
    demand_summary,
    previous_components,
    scored_health,
    week_events,
    week_interactions,
)

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/root-cause-analysis")
def get_root_cause_analysis() -> dict:
    """
    Why the score moved, with direct evidence kept apart from correlation.

    The two lists are returned under separate keys and built from separate
    data, so a client cannot merge a measured fact with an inferred one by
    accident.
    """
    ctx, prev = contexts()

    events = week_events(ctx)
    interactions = week_interactions(ctx)
    demand = demand_summary(ctx, events)
    outcomes = summarise_outcomes(interactions)
    component = demand_component(ctx, outcomes, demand)

    health = scored_health(ctx, prev)

    payload = root_cause_analysis.analyse(
        ctx,
        health,
        detect(ctx),
        previous_components(prev),
        demand.get("products", []),
        outcomes,
        interactions,
        component,
    )
    payload["demand_fulfillment"] = component
    payload["outcomes"] = outcomes
    return payload


@router.get("/business-health")
def get_business_health() -> dict:
    """
    The score plus everything that explains it, in one call.

    A convenience aggregate for the dashboard: the same figures as
    /api/health-score and /api/root-cause-analysis, fetched together so the
    two can never disagree on screen.
    """
    ctx, prev = contexts()

    events = week_events(ctx)
    interactions = week_interactions(ctx)
    demand = demand_summary(ctx, events)
    outcomes = summarise_outcomes(interactions)
    component = demand_component(ctx, outcomes, demand)
    health = scored_health(ctx, prev)

    return {
        "health": health,
        "demand_fulfillment": component,
        "outcomes": outcomes,
        "root_cause": root_cause_analysis.analyse(
            ctx,
            health,
            detect(ctx),
            previous_components(prev),
            demand.get("products", []),
            outcomes,
            interactions,
            component,
        ),
    }


@router.get("/transaction-correlation")
def get_transaction_correlation(limit: int = 25) -> dict:
    """
    Fulfilled conversations checked against the payment ledger.

    Never returns `confirmed`: the dataset has no line items, so a payment can
    be matched in time but never to a product.
    """
    ctx, _ = contexts()
    interactions = week_interactions(ctx)

    expecting = [i for i in interactions if i.get("expects_transaction")][
        : max(1, min(limit, 100))
    ]
    return transaction_correlation.correlate_all(expecting, load_transactions())


@router.post("/ai/ask")
def ai_ask(request: AskRequest) -> dict:
    """
    The merchant copilot.

    Answers from the merchant's own structured data and returns the evidence
    alongside the prose, so every claim can be checked against a number.
    Works in any language the configured provider handles; with no provider
    it answers deterministically in English.
    """
    ctx, prev = contexts()

    health = scored_health(ctx, prev)
    events = week_events(ctx)
    interactions = week_interactions(ctx)
    demand = demand_summary(ctx, events)
    outcomes = summarise_outcomes(interactions)
    component = demand_component(ctx, outcomes, demand)
    insights = insights_payload(ctx)
    unified = unified_payload(ctx, detect(ctx), events)
    plan = build_action_plan(ctx, demand, health["overall_score"])

    root_cause = root_cause_analysis.analyse(
        ctx,
        health,
        detect(ctx),
        previous_components(prev),
        demand.get("products", []),
        outcomes,
        interactions,
        component,
    )

    context = ai_engine.build_ai_context(
        ctx, health, insights["insights"], plan["campaign"], demand, unified
    )
    context["root_cause"] = {
        "narrative": root_cause["narrative"],
        "direct_evidence": [
            {
                "title": c["title"],
                "change_percent": c["change_percent"],
                "points_lost": c["points_lost"],
            }
            for c in root_cause["direct_evidence"]
        ],
        "possible_contributing_factors": [
            {
                "title": f["title"],
                "product": f["product"],
                "unfulfilled_requests": f["unfulfilled_requests"],
                "confidence": f["confidence"],
            }
            for f in root_cause["possible_contributing_factors"]
        ],
    }
    if component:
        context["demand_fulfillment"] = {
            "score": component["score"],
            "fulfillment_rate_percent": component["fulfillment_rate"],
            "unfilled_requests": component["unfulfilled"],
        }

    result = ai_engine.answer(request.question, context)

    return {
        "question": request.question,
        "answer": result["answer"],
        "evidence": _evidence(health, root_cause, demand, component),
        "provider": result["provider"],
        "model": result["model"],
        "fallback_used": result.get("fallback_used", False),
        "fallback_reason": result.get("fallback_reason"),
        "suggested_questions": ai_engine.SUGGESTED_QUESTIONS,
        "disclaimer": (
            "Observed figures come from your transaction and shop-floor data. "
            "Contributing factors are correlations, not proven causes."
        ),
    }


def _evidence(
    health: dict, root_cause: dict, demand: dict, component: dict | None
) -> list[dict]:
    """
    The numbers behind the answer, each tagged by how firmly it is known.

    This is what stops the copilot being a chatbot: every sentence it writes
    can be traced to one of these rows.
    """
    rows: list[dict] = [
        {
            "metric": "Business Health Score",
            "value": f"{health['overall_score']}/100",
            "change": f"{health['change']:+d} pts",
            "evidence_type": "observed",
        }
    ]

    for cause in root_cause["direct_evidence"][:3]:
        rows.append(
            {
                "metric": cause["title"],
                "value": f"{cause['change_percent']:+.0f}%",
                "change": f"-{cause['points_lost']:.1f} pts",
                "evidence_type": "observed",
            }
        )

    if component:
        rows.append(
            {
                "metric": "Demand fulfilment",
                "value": f"{component['fulfillment_rate']:.0f}%",
                "change": f"{component['unfulfilled']} requests unfilled",
                "evidence_type": "observed",
            }
        )

    for shortage in demand.get("out_of_stock_requests", [])[:2]:
        rows.append(
            {
                "metric": f"{shortage['product']} unfilled requests",
                "value": str(shortage["unfulfilled_requests"]),
                "change": f"of {shortage['requests']} asked for",
                "evidence_type": "observed",
            }
        )

    for factor in root_cause["possible_contributing_factors"][:2]:
        rows.append(
            {
                "metric": factor["title"],
                "value": f"{factor['unfulfilled_requests']} unfilled",
                "change": f"confidence {factor['confidence']:.0%}",
                "evidence_type": "possible_contributing_factor",
            }
        )

    return rows
