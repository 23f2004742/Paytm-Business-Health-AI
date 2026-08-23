"""
Recommendation engine.

Picks the single action with the best expected return, and sizes it from the
merchant's own transaction history rather than from a fixed template:

  * the offer window is the weakest trading block relative to its own baseline
  * the minimum spend sits just under the average basket in that window, so a
    normal customer clears it with one small addition
  * the cashback is scaled to the gap being closed, then rounded to a value
    that reads well on a storefront sign

Projected impact is explicitly a projection. It is derived from the size of
the gap and a deliberately conservative recapture assumption, and every
payload it appears in is labelled as simulated.
"""

from __future__ import annotations

from .transaction_analytics import AnalyticsContext, EVENING_HOURS, hour_range_label
from .anomaly_detection import detect

# Share of the lost trading activity a well-targeted offer is assumed to win
# back. Conservative on purpose: this is a projection shown to a merchant.
RECAPTURE_RATE = 0.60

CASHBACK_STEPS = [10, 20, 25, 30, 40, 50]


def _round_to_step(value: float, steps: list[int]) -> int:
    return min(steps, key=lambda s: (abs(s - value), s))


def _round_currency(value: float, step: int = 50) -> int:
    return max(step, int(round(value / step) * step))


def build_recommendation(ctx: AnalyticsContext) -> dict:
    anomaly_map = {a["id"]: a for a in detect(ctx)}
    evening = anomaly_map.get("evening_sales_drop")

    window_label = hour_range_label(*EVENING_HOURS)
    avg_evening_ticket = ctx.evening_avg_ticket
    gap_per_day = ctx.evening_revenue_gap_per_day

    # Minimum spend: just under the typical evening basket, so most customers
    # clear it by adding one item rather than changing what they buy.
    minimum_transaction = _round_currency(avg_evening_ticket * 0.95, 50)
    qualifying_share = ctx.evening_share_above(minimum_transaction)

    # Cashback scaled to the gap, held between 8% and 12% of the minimum spend.
    raw_cashback = minimum_transaction * 0.10
    cashback = _round_to_step(raw_cashback, CASHBACK_STEPS)
    cashback = max(10, min(cashback, int(minimum_transaction * 0.15)))

    lost_txns_per_day = max(
        0.0, ctx.evening_baseline_per_day - ctx.evening_current_per_day
    )
    recaptured_per_day = lost_txns_per_day * RECAPTURE_RATE
    projected_txn_lift = (
        round((recaptured_per_day / ctx.evening_current_per_day) * 100, 1)
        if ctx.evening_current_per_day
        else 0.0
    )
    projected_revenue_per_day = recaptured_per_day * avg_evening_ticket
    projected_cashback_cost = recaptured_per_day * cashback * (qualifying_share / 100.0)

    rationale = []
    if evening:
        rationale.append(evening["description"])
    rationale.append(
        f"Your average evening sale is Rs {avg_evening_ticket:,.0f}, so a Rs {minimum_transaction:,} "
        f"minimum is within reach for most customers. {qualifying_share:.0f}% of evening "
        f"transactions already clear it."
    )
    rationale.append(
        f"Recovering even part of the {lost_txns_per_day:.0f} transactions a day you have lost in "
        f"this window would close most of the Rs {gap_per_day:,.0f} daily revenue gap."
    )

    return {
        "id": "evening_boost",
        "name": "Evening Boost",
        "headline": f"Rs {cashback} cashback on evening orders",
        "objective": "Recover lost transactions in your weakest trading window",
        "config": {
            "cashback_amount": cashback,
            "minimum_transaction": minimum_transaction,
            "start_time": f"{EVENING_HOURS[0]:02d}:00",
            "end_time": f"{EVENING_HOURS[1] + 1:02d}:00",
            "window_label": window_label,
            "target_segment": "Customers who have bought from you before",
        },
        "why_now": (
            f"Transactions between {window_label} are down "
            f"{abs(ctx.evening_change):.0f}% against your 4-week average, the single largest "
            f"drop anywhere in your week."
            if evening
            else f"{window_label} is your weakest window relative to its own baseline."
        ),
        "rationale": rationale,
        "evidence": {
            "evening_change_percent": round(ctx.evening_change, 1),
            "current_transactions_per_day": round(ctx.evening_current_per_day, 1),
            "baseline_transactions_per_day": round(ctx.evening_baseline_per_day, 1),
            "lost_transactions_per_day": round(lost_txns_per_day, 1),
            "revenue_gap_per_day": round(gap_per_day, 2),
            "average_evening_ticket": round(avg_evening_ticket, 2),
            "qualifying_share_percent": qualifying_share,
        },
        "projection": {
            "label": "Simulated / Projected Impact",
            "disclaimer": (
                "Projected from your historical transaction patterns, assuming "
                f"{int(RECAPTURE_RATE * 100)}% of the lost evening activity returns. "
                "Actual results will vary."
            ),
            "recapture_rate": RECAPTURE_RATE,
            "evening_transaction_lift_percent": projected_txn_lift,
            "revenue_per_day": round(projected_revenue_per_day, 2),
            "revenue_per_week": round(projected_revenue_per_day * 7, 2),
            "estimated_cashback_cost_per_day": round(projected_cashback_cost, 2),
            "estimated_cashback_cost_per_week": round(projected_cashback_cost * 7, 2),
        },
        "cta": "Launch Campaign",
    }


def project_score_after(ctx: AnalyticsContext, current_score: int) -> dict:
    """
    Projected Business Health Score once the campaign closes part of the gap.

    Recomputed through the real scoring weights rather than invented: we work
    out how much the evening recovery lifts revenue and transactions, feed
    those improved deltas back through the same component formulas, and report
    the difference.
    """
    from .health_score import (
        ANOMALY_PENALTY,
        ANOMALY_Z,
        WEIGHTS,
        _asym,
        _clamp,
        _soften,
        compute_components,
        status_for,
    )

    components = {c.key: c.score for c in compute_components(ctx)}

    lost_per_day = max(0.0, ctx.evening_baseline_per_day - ctx.evening_current_per_day)
    recaptured_per_day = lost_per_day * RECAPTURE_RATE
    recaptured_week = recaptured_per_day * 7

    # How much better revenue and volume would have looked with that recovery.
    extra_revenue = recaptured_week * ctx.evening_avg_ticket
    new_revenue = ctx.current.revenue + extra_revenue
    new_txns = ctx.current.txns + recaptured_week

    def pct(cur: float, prev: float) -> float:
        return ((cur - prev) / prev * 100.0) if prev else 0.0

    new_rev_wow = pct(new_revenue, ctx.previous.revenue)
    new_rev_base = pct(new_revenue / 7.0, ctx.baseline.revenue_per_day)
    new_txn_wow = pct(new_txns, ctx.previous.txns)
    new_txn_base = pct(new_txns / 7.0, ctx.baseline.txns_per_day)

    projected = dict(components)
    projected["revenue_health"] = _soften(
        _clamp(78.0 + _asym(new_rev_wow, 0.50, 0.25) + _asym(new_rev_base, 0.34, 0.17))
    )
    projected["transaction_health"] = _soften(
        _clamp(
            87.0
            + _asym(new_txn_wow, 0.70, 0.35)
            + _asym(new_txn_base, 0.50, 0.25)
            + 0.40 * ctx.avg_ticket_vs_baseline
        )
    )

    # The offer is aimed at customers who have bought before, so the same
    # recapture assumption is applied to the repeat-purchase decline.
    cur_cust = ctx.customers_current
    new_repeat_change = ctx.repeat_txn_change * (1.0 - RECAPTURE_RATE)
    level = _clamp(cur_cust["repeat_customer_rate"] / 40.0 * 100.0)
    momentum = _clamp(68.0 + 1.2 * new_repeat_change + 0.5 * ctx.new_customer_change)
    projected["customer_health"] = _soften(_clamp(0.45 * level + 0.55 * momentum))

    # Recovering the evening window lifts the weakest days back toward normal,
    # so the worst revenue outlier is assumed to stop reading as an anomaly.
    zscores = ctx.daily_revenue_zscores()
    anomaly_days = int((zscores.abs() > ANOMALY_Z).sum())
    projected["stability"] = _soften(
        _clamp(
            100.0
            - max(0.0, ctx.revenue_cv - 0.12) * 250.0
            - ANOMALY_PENALTY * max(0, anomaly_days - 1)
        )
    )

    projected_total = _clamp(sum(projected[k] * w for k, w in WEIGHTS.items()))
    projected_score = round(projected_total)

    return {
        "label": "Simulated / Projected Impact",
        "current_score": current_score,
        "projected_score": projected_score,
        "delta": projected_score - current_score,
        "projected_status": status_for(projected_total),
        "components_before": {k: round(v) for k, v in components.items()},
        "components_after": {k: round(v) for k, v in projected.items()},
        "disclaimer": (
            "A projection based on your own transaction history, not a guarantee. "
            f"It assumes the campaign recovers {int(RECAPTURE_RATE * 100)}% of the "
            "transactions lost in your evening window, that returning customers come "
            "back at the same rate, and that recovering those evenings lifts your "
            "weakest day back inside its normal range."
        ),
        "assumptions": [
            f"{int(RECAPTURE_RATE * 100)}% of lost evening transactions are recovered",
            "Recovered customers spend at your current average evening basket",
            f"The repeat-purchase decline narrows by {int(RECAPTURE_RATE * 100)}%",
            "One fewer day falls outside your normal revenue range",
        ],
    }


# ===========================================================================
#  Action plan
#
#  The transaction-only product had exactly one action: launch a campaign.
#  With shop-floor demand in the picture there are three, and the third is
#  the one that needs the other two to exist:
#
#    CAMPAIGN   recover a weak trading window with a targeted offer
#    RESTOCK    put back what customers asked for and could not buy
#    COMBINED   restock first, then run the campaign into restored stock
#
#  Ordering matters and is not cosmetic. Driving traffic at an empty shelf
#  spends cashback to reproduce the original disappointment, so whenever both
#  actions apply the combined action becomes the recommendation, with the
#  campaign explicitly sequenced behind the restock.
# ===========================================================================

# Share of unmet requests assumed to convert once the product is back on the
# shelf. Below the campaign recapture rate on purpose: a customer who was
# turned away may already have bought it somewhere else.
RESTOCK_CONVERSION_RATE = 0.50


def project_restock_impact(
    ctx: AnalyticsContext, current_score: int, unfulfilled_per_week: float
) -> dict:
    """
    Projected score once unmet demand is served, run through the real weights.

    Each recovered request is modelled as one extra transaction at the
    merchant's current average basket. Nothing is invented: the request count
    is measured on the shop floor, the basket value comes from the ledger.
    """
    from .health_score import (
        WEIGHTS,
        _asym,
        _clamp,
        _soften,
        compute_components,
        status_for,
    )

    components = {c.key: c.score for c in compute_components(ctx)}
    recovered = unfulfilled_per_week * RESTOCK_CONVERSION_RATE

    basket = ctx.current.avg_ticket
    new_revenue = ctx.current.revenue + recovered * basket
    new_txns = ctx.current.txns + recovered

    def pct(cur: float, prev: float) -> float:
        return ((cur - prev) / prev * 100.0) if prev else 0.0

    projected = dict(components)
    projected["revenue_health"] = _soften(
        _clamp(
            78.0
            + _asym(pct(new_revenue, ctx.previous.revenue), 0.50, 0.25)
            + _asym(pct(new_revenue / 7.0, ctx.baseline.revenue_per_day), 0.34, 0.17)
        )
    )
    projected["transaction_health"] = _soften(
        _clamp(
            87.0
            + _asym(pct(new_txns, ctx.previous.txns), 0.70, 0.35)
            + _asym(pct(new_txns / 7.0, ctx.baseline.txns_per_day), 0.50, 0.25)
            + 0.40 * ctx.avg_ticket_vs_baseline
        )
    )

    total = _clamp(sum(projected[k] * w for k, w in WEIGHTS.items()))
    projected_score = round(total)

    return {
        "label": "Simulated / Projected Impact",
        "current_score": current_score,
        "projected_score": projected_score,
        "delta": projected_score - current_score,
        "projected_status": status_for(total),
        "components_before": {k: round(v) for k, v in components.items()},
        "components_after": {k: round(v) for k, v in projected.items()},
        "recovered_transactions_per_week": round(recovered, 1),
        "recovered_revenue_per_week": round(recovered * basket, 2),
        "disclaimer": (
            "A projection from your own data, not a guarantee. It assumes "
            f"{int(RESTOCK_CONVERSION_RATE * 100)}% of the requests you could not "
            "fill this week would have converted with the product in stock, each "
            "at your current average basket."
        ),
        "assumptions": [
            f"{int(RESTOCK_CONVERSION_RATE * 100)}% of unfilled requests convert once restocked",
            f"Each recovered sale is worth your average basket of Rs {basket:,.0f}",
            "Demand continues at the rate heard on the shop floor this week",
        ],
    }


def build_restock_action(
    product: dict, ctx: AnalyticsContext, current_score: int
) -> dict:
    """A restock alert sized from measured, unfilled demand."""
    unfulfilled = product["unfulfilled_requests"]
    name = product["product"]
    priority = "high" if unfulfilled >= 8 else "medium" if unfulfilled >= 3 else "low"

    return {
        "type": "restock",
        "id": f"restock_{product['family']}",
        "family": product["family"],
        "name": f"Restock {name}",
        "headline": f"{name}: {unfulfilled} unfilled requests this week",
        "objective": "Put back what customers are actively asking for",
        "priority": priority,
        "product": name,
        "catalog_items": product["catalog_items"][:5],
        "evidence": {
            "requests": product["requests"],
            "unfulfilled_requests": unfulfilled,
            "unfulfilled_share_percent": product["unfulfilled_share"],
            "availability": product["availability"],
            "peak_hour": product["peak_hour"],
            "average_confidence": product["average_confidence"],
        },
        "rationale": [
            f"{name} was requested {product['requests']} times on the shop floor "
            f"this week and was unavailable for {unfulfilled} of them.",
            "None of these appear in your transaction data: a sale that does not "
            "happen leaves no record, which is exactly the gap shop-floor audio fills.",
        ],
        "projection": project_restock_impact(ctx, current_score, float(unfulfilled)),
        "cta": "Create restock alert",
    }


def build_combined_action(
    restock: dict, campaign: dict, current_score: int
) -> dict:
    """
    Restock, then campaign. Sequenced, not merged.

    The projection is deliberately *not* the sum of the two. Both actions
    recover transactions in the same evening window, so adding them would
    count the same customers twice. The larger gain is taken in full and the
    smaller is discounted heavily.
    """
    from .health_score import status_for

    restock_delta = restock["projection"]["delta"]
    campaign_delta = campaign["score_projection"]["delta"]

    larger = max(restock_delta, campaign_delta)
    smaller = min(restock_delta, campaign_delta)
    combined_delta = larger + round(smaller * 0.4)
    projected_score = min(100, current_score + combined_delta)

    return {
        "type": "combined",
        "id": "restock_then_boost",
        "name": f"Restock {restock['product']}, then {campaign['name']}",
        "headline": "Fix the gap first, then drive traffic into it",
        "objective": "Recover unmet demand, then rebuild the trading window",
        "priority": "high",
        "steps": [
            {
                "order": 1,
                "action": "restock",
                "title": restock["name"],
                "detail": (
                    f"{restock['evidence']['unfulfilled_requests']} customers asked "
                    f"for {restock['product']} this week and left without it."
                ),
            },
            {
                "order": 2,
                "action": "campaign",
                "title": f"Launch {campaign['name']}",
                "detail": (
                    f"Rs {campaign['config']['cashback_amount']} cashback on orders "
                    f"above Rs {campaign['config']['minimum_transaction']}, "
                    f"{campaign['config']['window_label']}."
                ),
            },
        ],
        "sequencing_note": (
            "Order matters. Running the campaign before restocking spends cashback "
            "bringing customers back to the same empty shelf, so the restock "
            "comes first."
        ),
        "projection": {
            "label": "Simulated / Projected Impact",
            "current_score": current_score,
            "projected_score": projected_score,
            "delta": combined_delta,
            "projected_status": status_for(projected_score),
            "disclaimer": (
                "Not the sum of the two actions. Both recover transactions in the "
                "same evening window, so counting them separately would count the "
                "same customers twice. The larger effect is taken in full and the "
                "smaller discounted to 40%."
            ),
            "assumptions": [
                *restock["projection"]["assumptions"],
                *campaign["score_projection"]["assumptions"][:2],
                "The two actions overlap, so their combined effect is below their sum",
            ],
        },
        "cta": "Do both",
    }


def build_action_plan(
    ctx: AnalyticsContext, demand_summary: dict, current_score: int
) -> dict:
    """
    Every action available this week, ranked, with the primary one named.

    Degrades cleanly: with no shop-floor data the campaign is the whole plan,
    which is exactly how the transaction-only product behaved.
    """
    campaign = build_recommendation(ctx)
    campaign["score_projection"] = project_score_after(ctx, current_score)

    campaign_action = {
        "type": "campaign",
        "id": campaign["id"],
        "name": campaign["name"],
        "headline": campaign["headline"],
        "objective": campaign["objective"],
        "priority": "high",
        "config": campaign["config"],
        "why_now": campaign["why_now"],
        "rationale": campaign["rationale"],
        "evidence": campaign["evidence"],
        "projection": campaign["score_projection"],
        "campaign_projection": campaign["projection"],
        "cta": campaign["cta"],
    }

    short_products = [
        p for p in demand_summary.get("products", []) if p["unfulfilled_requests"] > 0
    ]

    actions: list[dict] = []
    lead_restock: dict | None = None

    if short_products:
        top = max(short_products, key=lambda p: (p["unfulfilled_requests"], p["requests"]))
        lead_restock = build_restock_action(top, ctx, current_score)
        actions.append(lead_restock)

    actions.append(campaign_action)

    # Every remaining shortage, so the merchant sees the full restock list.
    for product in short_products:
        if lead_restock and product["family"] == lead_restock["family"]:
            continue
        actions.append(build_restock_action(product, ctx, current_score))

    combined = None
    if lead_restock:
        combined = build_combined_action(lead_restock, campaign, current_score)
        actions.insert(0, combined)

    primary = combined or campaign_action

    return {
        "actions": actions,
        "primary": primary,
        "primary_type": primary["type"],
        "campaign": campaign,
        "restock_candidates": [
            {
                "product": p["product"],
                "family": p["family"],
                "requests": p["requests"],
                "unfulfilled_requests": p["unfulfilled_requests"],
                "catalog_items": p["catalog_items"][:5],
            }
            for p in short_products
        ],
    }
