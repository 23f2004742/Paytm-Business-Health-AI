"""
Shared route dependencies.

Every router needs the same picture: the merchant, an analytics context
anchored on the dataset's 'today', the shop-floor interactions for that same
week, and the demand-fulfilment component derived from them. Building them
here keeps the routers thin and guarantees all of them join against an
identical window.

The previous week is built the same way, deliberately. Scoring a week that
has conversation data against one that does not would move the health score
for no reason other than the feature being switched on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
from fastapi import HTTPException

from ..services import demand_analysis, demand_fulfillment, shop_intelligence
from ..services.data_loader import DatasetMissingError, load_meta
from ..services.interaction_outcome_engine import summarise_outcomes
from ..services.transaction_analytics import AnalyticsContext, build_context


def contexts() -> tuple[AnalyticsContext, AnalyticsContext]:
    """Current context plus the same analysis run a week earlier."""
    try:
        current = build_context()
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    previous = build_context(current.anchor - pd.Timedelta(days=7))
    return current, previous


@lru_cache(maxsize=1)
def merchant() -> dict:
    meta = load_meta()
    return {
        "merchant_id": meta["merchant_id"],
        "name": meta["merchant_name"],
        "owner_name": meta["owner_name"],
        "category": meta["category"],
        "location": meta["location"],
        "business_hours": meta["business_hours"],
        "as_of": meta["as_of_date"],
    }


def merchant_id() -> str:
    return merchant()["merchant_id"]


def _window_bounds(ctx: AnalyticsContext) -> tuple[datetime, datetime]:
    start = ctx.current.start.to_pydatetime().replace(hour=0, minute=0, second=0)
    end = ctx.current.end.to_pydatetime().replace(hour=23, minute=59, second=59)
    return start, end


def _ensure_seeded(ctx: AnalyticsContext) -> None:
    """Seed the scripted shop week once, on first read, when DEMO_MODE is on."""
    anchor = ctx.anchor.to_pydatetime().replace(hour=23, minute=59, second=59)
    shop_intelligence.ensure_demo_events(merchant_id(), anchor)


def week_events(ctx: AnalyticsContext) -> list[dict]:
    """Shop events for the same days the transaction analysis covers."""
    _ensure_seeded(ctx)
    start, end = _window_bounds(ctx)
    return shop_intelligence.event_store().between(start, end, merchant_id())


def week_interactions(ctx: AnalyticsContext) -> list[dict]:
    """Buyer/seller exchanges for the same window."""
    _ensure_seeded(ctx)
    start, end = _window_bounds(ctx)
    return shop_intelligence.interaction_store().between(start, end, merchant_id())


def demand_summary(ctx: AnalyticsContext, events: list[dict] | None = None) -> dict:
    events = week_events(ctx) if events is None else events
    basket = round(ctx.current.avg_ticket, 2) if ctx.current.txns else None
    return demand_analysis.summarise(events, basket_value=basket)


def outcome_summary(ctx: AnalyticsContext, interactions: list[dict] | None = None) -> dict:
    interactions = week_interactions(ctx) if interactions is None else interactions
    return summarise_outcomes(interactions)


def demand_component(
    ctx: AnalyticsContext,
    outcomes: dict | None = None,
    demand: dict | None = None,
) -> dict | None:
    """
    The Demand Fulfilment health component, or None when the week has too
    little conversation to score it honestly.
    """
    outcomes = outcome_summary(ctx) if outcomes is None else outcomes
    demand = demand_summary(ctx) if demand is None else demand
    return demand_fulfillment.compute(outcomes, demand.get("products", []))


def scored_health(ctx: AnalyticsContext, previous_ctx: AnalyticsContext) -> dict:
    """
    The health payload, with both weeks scored on the same basis.

    This is the single entry point every router uses, so the score can never
    differ between two screens of the same app.
    """
    from ..services.health_score import health_score_payload

    current_component = demand_component(ctx)
    previous_component = _previous_demand_component(previous_ctx)

    return health_score_payload(
        ctx, previous_ctx, current_component, previous_component
    )


def _previous_demand_component(previous_ctx: AnalyticsContext) -> dict | None:
    """Demand fulfilment for the week before, from that week's own exchanges."""
    start, end = _window_bounds(previous_ctx)
    merchant = merchant_id()

    interactions = shop_intelligence.interaction_store().between(start, end, merchant)
    events = shop_intelligence.event_store().between(start, end, merchant)
    if not interactions:
        return None

    return demand_fulfillment.compute(
        summarise_outcomes(interactions), demand_analysis.product_demand(events)
    )


def previous_components(previous_ctx: AnalyticsContext) -> dict:
    """
    Last week's component scores, for root-cause attribution.

    Built on the same basis as this week so the deltas mean something.
    """
    from ..services.health_score import compute_components

    component = _previous_demand_component(previous_ctx)
    return {
        c.key: round(c.score) for c in compute_components(previous_ctx, component)
    }


def all_events(limit: int | None = None) -> list[dict]:
    events = shop_intelligence.event_store().all(merchant_id())
    return events[:limit] if limit else events


def all_interactions(limit: int | None = None) -> list[dict]:
    interactions = shop_intelligence.interaction_store().all(merchant_id())
    return interactions[:limit] if limit else interactions
