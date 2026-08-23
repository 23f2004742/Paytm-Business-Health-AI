"""
Root cause analysis: "why did my score drop?"

The merchant does not want a number. They want to know what went wrong and
what to do. This module answers that, and its single most important job is to
keep two very different kinds of claim apart:

------------------------------------------------------------------------------
DIRECT EVIDENCE                      POSSIBLE CONTRIBUTING FACTORS
------------------------------------------------------------------------------
Measured in the transaction ledger.  Inferred from shop-floor conversation
Every rupee is recorded.             overlapping a decline in time.
"Evening transactions fell 28%"      "Maggi was refused 12 times in the
is a fact.                           same window; this may be contributing."

Confidence 0.90 - 0.98               Confidence 0.35 - 0.75
------------------------------------------------------------------------------

The separation is structural, not cosmetic: the two lists are built by
different functions, from different data, and are returned under different
keys so a UI cannot accidentally merge them. Nothing in this module emits
"caused by", "because of" or "due to" for a correlated factor.

Score attribution is arithmetic, not narrative. Each component's contribution
to the drop is its own change times its weight, so the parts add up to the
whole and a merchant can check the sum.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from .transaction_analytics import (
    AnalyticsContext,
    EVENING_HOURS,
    hour_range_label,
)

# Confidence bands, named so the UI and the AI layer describe them identically.
CONFIDENCE_HIGH = 0.95      # measured directly in the ledger
CONFIDENCE_MEDIUM = 0.70    # strong overlap, independent corroboration
CONFIDENCE_LOW = 0.45       # plausible, weakly supported

# A transaction metric must move at least this much to be called out.
MATERIAL_CHANGE = 8.0

# Unfilled requests needed before unmet demand is offered as a factor.
DEMAND_FACTOR_THRESHOLD = 3

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _band(confidence: float) -> str:
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _severity(points_lost: float, change_percent: float) -> str:
    if points_lost >= 3.0 or abs(change_percent) >= 25:
        return "high"
    if points_lost >= 1.0 or abs(change_percent) >= 12:
        return "medium"
    return "low"


# ------------------------------------------------------- score attribution

COMPONENT_LABELS = {
    "revenue_health": "Revenue Health",
    "customer_health": "Customer Health",
    "transaction_health": "Transaction Health",
    "stability": "Business Stability",
    "growth_potential": "Growth Potential",
    "demand_fulfillment": "Demand Fulfilment",
}


def attribute_score_change(health: dict, previous_components: dict) -> list[dict]:
    """
    Split the score movement across components.

    contribution = (component now - component before) x weight

    These sum to the total change, so the merchant can audit the arithmetic
    rather than trust a story about it.
    """
    weights = health.get("weights", {})
    now = health.get("components", {})

    rows = []
    for key, current in now.items():
        before = previous_components.get(key)
        if before is None:
            # A component that did not exist last week cannot be said to have
            # moved. Reporting a change here would be inventing history.
            continue
        weight = weights.get(key, 0.0)
        delta = current - before
        rows.append(
            {
                "component": key,
                "label": COMPONENT_LABELS.get(key, key.replace("_", " ").title()),
                "before": before,
                "after": current,
                "change": round(delta, 1),
                "weight": round(weight, 3),
                "points_contributed": round(delta * weight, 2),
            }
        )

    rows.sort(key=lambda r: r["points_contributed"])
    return rows


# ---------------------------------------------------------- direct evidence

def direct_causes(
    ctx: AnalyticsContext,
    anomalies: list[dict],
    attribution: list[dict],
) -> list[dict]:
    """
    Causes measured in the transaction ledger.

    Anchored on score attribution rather than on anomalies alone, so what the
    merchant reads is genuinely what moved their number, ranked by how much.
    """
    causes: list[dict] = []
    negatives = [a for a in anomalies if a.get("type") == "negative"]

    # An anomaly explains one component, not several. Without this, a single
    # weak Tuesday attaches to both Revenue Health and Business Stability and
    # the merchant reads the same story twice under two different headings.
    claimed: set[str] = set()

    for row in attribution:
        if row["points_contributed"] >= -0.2:
            continue   # flat or positive; not a cause of the drop

        component = row["component"]
        if component == "demand_fulfillment":
            continue   # conversation-derived: belongs in contributing factors

        supporting = [
            a
            for a in negatives
            if a["id"] not in claimed and _anomaly_supports(component, a)
        ]

        points_lost = abs(row["points_contributed"])

        if supporting:
            lead = supporting[0]
            claimed.add(lead["id"])
            # Name the signal the merchant recognises ("Evening transactions"),
            # not the internal component that happens to score it.
            title = lead["metric"]
            change_percent = lead["change_percent"]
            detail = lead["description"]
        else:
            title = row["label"]
            change_percent = row["change"]
            detail = (
                f"{row['label']} fell from {row['before']} to {row['after']} "
                f"out of 100."
            )

        causes.append(
            {
                "id": f"direct_{component}",
                "category": "direct_evidence",
                "title": title,
                "component": component,
                "component_label": row["label"],
                "component_before": row["before"],
                "component_after": row["after"],
                "change_percent": round(change_percent, 1),
                "points_lost": round(points_lost, 2),
                "severity": _severity(points_lost, change_percent),
                "confidence": CONFIDENCE_HIGH,
                "confidence_band": "high",
                "evidence_type": "Measured directly in transaction data",
                "detail": detail,
                "supporting_signals": [
                    {
                        "metric": a["metric"],
                        "change_percent": a["change_percent"],
                        "severity": a["severity"],
                        "description": a["description"],
                    }
                    for a in supporting[:3]
                ],
            }
        )

    # A sharp anomaly can exist without dragging a component (an offsetting
    # gain elsewhere), and it is still worth telling the merchant about.
    covered = {c["component"] for c in causes}
    for anomaly in negatives:
        if abs(anomaly["change_percent"]) < MATERIAL_CHANGE:
            continue
        if any(_anomaly_supports(component, anomaly) for component in covered):
            continue
        causes.append(
            {
                "id": f"direct_{anomaly['id']}",
                "category": "direct_evidence",
                "title": anomaly["metric"],
                "component": None,
                "change_percent": anomaly["change_percent"],
                "points_lost": 0.0,
                "severity": anomaly["severity"],
                "confidence": CONFIDENCE_HIGH,
                "confidence_band": "high",
                "evidence_type": "Measured directly in transaction data",
                "detail": anomaly["description"],
                "supporting_signals": [],
            }
        )

    causes.sort(key=lambda c: (SEVERITY_RANK.get(c["severity"], 3), -c["points_lost"]))
    return causes


# Which anomalies can explain which component. Ordered by how directly the
# signal drives that component, and claimed first-come so each anomaly is
# told once.
_COMPONENT_ANOMALIES = {
    "transaction_health": ("evening_sales_drop",),
    "customer_health": ("repeat_customer_drop",),
    "stability": ("_revenue_drop",),          # single-day outliers
    "revenue_health": ("weekend_revenue_drop", "_revenue_drop"),
    "growth_potential": ("weekend_revenue_drop", "average_ticket_drop"),
}


def _anomaly_supports(component: str, anomaly: dict) -> bool:
    keys = _COMPONENT_ANOMALIES.get(component, ())
    anomaly_id = anomaly.get("id", "")
    return any(key in anomaly_id for key in keys)


# ------------------------------------------------- possible contributing factors

def contributing_factors(
    ctx: AnalyticsContext,
    demand_products: list[dict],
    outcome_summary: dict,
    interactions: list[dict],
    direct: list[dict],
    demand_component: Optional[dict] = None,
) -> list[dict]:
    """
    Shop-floor signals that MAY be contributing.

    Every entry here is a correlation. The confidence ceiling is deliberately
    below the direct-evidence floor, so a contributing factor can never
    outrank a measured fact however dramatic it looks.
    """
    factors: list[dict] = []

    week_start = ctx.current.start.to_pydatetime()
    week_end = ctx.current.end.to_pydatetime() + timedelta(hours=23, minutes=59)

    # Which declines have a time window a shop signal could overlap?
    evening_decline = next(
        (
            c
            for c in direct
            if c.get("component") == "transaction_health"
            or "evening" in c.get("id", "")
        ),
        None,
    )

    for product in demand_products:
        unfulfilled = product.get("unfulfilled_requests", 0)
        if unfulfilled < DEMAND_FACTOR_THRESHOLD:
            continue

        # How much of this product's unmet demand sits inside the evening
        # window, which is where the ledger shows the decline.
        in_evening = sum(
            1
            for i in interactions
            if i.get("product_family") == product["family"]
            and i.get("potential_lost_sale")
            and EVENING_HOURS[0] <= int(i.get("hour", -1)) <= EVENING_HOURS[1]
        )
        overlap_share = in_evening / unfulfilled if unfulfilled else 0.0

        # Confidence rises with volume and with how much the shop signal
        # concentrates inside the window that actually declined.
        confidence = CONFIDENCE_LOW
        confidence += 0.15 * min(1.0, unfulfilled / 10.0)
        if evening_decline and overlap_share >= 0.4:
            confidence += 0.15 * overlap_share
        confidence = round(min(CONFIDENCE_MEDIUM + 0.05, confidence), 2)

        if evening_decline and in_evening >= 2:
            window = hour_range_label(*EVENING_HOURS)
            detail = (
                f"{product['product']} was requested {product['requests']} times "
                f"this week and was unavailable for {unfulfilled} of them. "
                f"{in_evening} of those refusals fell inside the {window} window, "
                f"where transactions are also down "
                f"{abs(evening_decline['change_percent']):.0f}%. The two coincide, "
                f"and the unmet demand may be contributing to the decline. The "
                f"transaction data alone cannot confirm that."
            )
        else:
            detail = (
                f"{product['product']} was requested {product['requests']} times "
                f"and was unavailable for {unfulfilled} of them. Each refusal is a "
                f"potential missed sale that leaves no record in payment data."
            )

        factors.append(
            {
                "id": f"factor_demand_{product['family']}",
                "category": "possible_contributing_factor",
                "title": f"Unmet demand for {product['product']}",
                "product": product["product"],
                "requests": product["requests"],
                "unfulfilled_requests": unfulfilled,
                "requests_in_declining_window": in_evening,
                "overlap_share_percent": round(overlap_share * 100, 1),
                "severity": "high" if unfulfilled >= 8 else "medium",
                "confidence": confidence,
                "confidence_band": _band(confidence),
                "evidence_type": "Inferred from shop-floor conversation",
                "detail": detail,
                "correlation_note": (
                    "Temporal co-occurrence only. Shop-floor demand and payment "
                    "activity are measured independently and no causal link is "
                    "claimed."
                ),
            }
        )

    # Fulfilment falling week over week is itself a factor worth naming.
    if demand_component and demand_component.get("fulfillment_rate") is not None:
        rate = demand_component["fulfillment_rate"]
        if rate < 80:
            factors.append(
                {
                    "id": "factor_fulfillment_rate",
                    "category": "possible_contributing_factor",
                    "title": "Customer requests are not being filled",
                    "product": None,
                    "requests": outcome_summary.get("decided_interactions", 0),
                    "unfulfilled_requests": outcome_summary.get("counts", {}).get(
                        "unfulfilled", 0
                    ),
                    "requests_in_declining_window": 0,
                    "overlap_share_percent": 0.0,
                    "severity": "high" if rate < 60 else "medium",
                    "confidence": CONFIDENCE_MEDIUM,
                    "confidence_band": "medium",
                    "evidence_type": "Inferred from shop-floor conversation",
                    "detail": (
                        f"Only {rate:.0f}% of customer requests heard this week ended "
                        f"in a sale. Customers turned away do not appear anywhere in "
                        f"your transaction data, so this may be depressing figures "
                        f"that otherwise look unexplained."
                    ),
                    "correlation_note": (
                        "Measured from a sample of shop-floor conversation, not a "
                        "census of every customer."
                    ),
                }
            )

    factors.sort(
        key=lambda f: (SEVERITY_RANK.get(f["severity"], 3), -f["confidence"])
    )
    return factors


# ---------------------------------------------------------------- narrative

def build_narrative(health: dict, direct: list[dict], factors: list[dict]) -> str:
    """One paragraph, with the two kinds of claim kept visibly apart."""
    change = health.get("change", 0)
    current = health.get("overall_score")
    previous = health.get("previous_score")

    if change >= 0:
        opening = (
            f"Your Business Health Score is {current} out of 100, "
            f"{'up' if change else 'level'} "
            f"{f'{change} points' if change else ''} on last week."
        )
    else:
        opening = (
            f"Your Business Health Score fell from {previous} to {current}, "
            f"a drop of {abs(change)} points."
        )

    parts = [opening]

    if direct:
        observed = "; ".join(
            f"{c['title'].lower()} {c['change_percent']:+.0f}%" for c in direct[:3]
        )
        parts.append(f"Directly observed in your payment data: {observed}.")

    if factors:
        lead = factors[0]
        parts.append(f"Possible contributing factor: {lead['detail']}")

    return " ".join(parts)


# ------------------------------------------------------------------- public

def analyse(
    ctx: AnalyticsContext,
    health: dict,
    anomalies: list[dict],
    previous_components: dict,
    demand_products: list[dict],
    outcome_summary: dict,
    interactions: list[dict],
    demand_component: Optional[dict] = None,
) -> dict:
    """The payload behind GET /api/root-cause-analysis."""
    attribution = attribute_score_change(health, previous_components)
    direct = direct_causes(ctx, anomalies, attribution)
    factors = contributing_factors(
        ctx, demand_products, outcome_summary, interactions, direct, demand_component
    )

    return {
        "score": {
            "current": health.get("overall_score"),
            "previous": health.get("previous_score"),
            "change": health.get("change"),
            "status": health.get("status"),
            "trend": health.get("trend"),
            "comparable_basis": health.get("comparable_basis", True),
        },
        "narrative": build_narrative(health, direct, factors),
        "direct_evidence": direct,
        "possible_contributing_factors": factors,
        "score_attribution": attribution,
        "counts": {
            "direct": len(direct),
            "contributing": len(factors),
        },
        "methodology": {
            "attribution": (
                "Each component's contribution is its own change multiplied by "
                "its weight, so the parts sum to the total score movement."
            ),
            "separation": (
                "Direct evidence is measured in the transaction ledger. "
                "Contributing factors are inferred from shop-floor conversation "
                "overlapping a decline in time, and are never presented as "
                "proven causes."
            ),
            "confidence": {
                "direct_evidence": CONFIDENCE_HIGH,
                "contributing_factor_ceiling": CONFIDENCE_MEDIUM + 0.05,
            },
        },
        "as_of": ctx.anchor.date().isoformat(),
    }
