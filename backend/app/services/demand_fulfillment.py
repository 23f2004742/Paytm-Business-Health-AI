"""
Demand Fulfilment Health: the sixth Business Health component.

Every other component measures what the shop *did*. This one measures what
the shop *failed to do* — customers who asked for something and left without
it. That is invisible to payment analytics by construction, because a sale
that does not happen produces no transaction.

Scoring, in order of severity:

  base            the fulfilment rate itself (served / decided exchanges)
  repeat penalty  the same product refused again and again is an inventory
                  failure, not bad luck, and is penalised beyond its share
  breadth penalty several different products short at once is a supply problem

------------------------------------------------------------------------------
Why this component is capped and gated
------------------------------------------------------------------------------
The shop-floor signal comes from one microphone sampling a fraction of the
day's conversations. It is the least complete input the product has, so:

  * with too few interactions to be meaningful, the component returns None and
    its weight is redistributed across the other five. A quiet afternoon must
    not look like a business collapse.
  * the score floor is 25 rather than 0. Even a shop that refused everything
    it was asked for in a small sample has not earned a zero from this
    evidence.
"""

from __future__ import annotations

import os
from typing import Optional

# Fewer decided exchanges than this and the sample is not worth scoring.
MIN_INTERACTIONS_TO_SCORE = 4

SCORE_FLOOR = 25.0

# A product refused this many times has moved from unlucky to mismanaged.
REPEAT_SHORTAGE_THRESHOLD = 5
REPEAT_PENALTY_PER_PRODUCT = 6.0
MAX_REPEAT_PENALTY = 22.0

BREADTH_PENALTY_PER_PRODUCT = 3.0
MAX_BREADTH_PENALTY = 12.0


def is_enabled() -> bool:
    """`DEMAND_FULFILLMENT_ENABLED=false` restores the original 5-component score."""
    return os.environ.get("DEMAND_FULFILLMENT_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def compute(outcome_summary: dict, demand_products: list[dict]) -> Optional[dict]:
    """
    Score demand fulfilment, or return None when there is not enough evidence.

    None is meaningful: it tells the health score to redistribute this
    component's weight rather than to score it as zero.
    """
    if not is_enabled():
        return None

    decided = outcome_summary.get("decided_interactions", 0)
    rate = outcome_summary.get("fulfillment_rate")

    if decided < MIN_INTERACTIONS_TO_SCORE or rate is None:
        return None

    counts = outcome_summary.get("counts", {})
    unfulfilled = counts.get("unfulfilled", 0)

    # Products the shop was short of, and how badly.
    short = [p for p in demand_products if p.get("unfulfilled_requests", 0) > 0]
    chronic = [
        p for p in short if p["unfulfilled_requests"] >= REPEAT_SHORTAGE_THRESHOLD
    ]

    repeat_penalty = min(
        MAX_REPEAT_PENALTY, REPEAT_PENALTY_PER_PRODUCT * len(chronic)
    )
    breadth_penalty = min(
        MAX_BREADTH_PENALTY, BREADTH_PENALTY_PER_PRODUCT * max(0, len(short) - 1)
    )

    score = max(SCORE_FLOOR, min(100.0, rate - repeat_penalty - breadth_penalty))

    drivers = [
        {
            "label": "Requests fulfilled",
            "value": f"{rate:.0f}%",
            "tone": "positive" if rate >= 80 else "negative" if rate < 60 else "neutral",
        },
        {
            "label": "Unfilled requests",
            "value": str(unfulfilled),
            "tone": "negative" if unfulfilled else "positive",
        },
        {
            "label": "Products short",
            "value": str(len(short)),
            "tone": "negative" if short else "positive",
        },
    ]

    if chronic:
        worst = max(chronic, key=lambda p: p["unfulfilled_requests"])
        summary = (
            f"{worst['product']} was asked for {worst['requests']} times and "
            f"unavailable for {worst['unfulfilled_requests']} of them. Only "
            f"{rate:.0f}% of customer requests this week were filled."
        )
    elif short:
        summary = (
            f"{rate:.0f}% of customer requests were filled. "
            f"{len(short)} product{'s were' if len(short) > 1 else ' was'} "
            f"unavailable at least once."
        )
    else:
        summary = (
            f"Every customer request heard this week was filled "
            f"({decided} exchanges)."
        )

    return {
        "score": round(score, 1),
        "fulfillment_rate": rate,
        "decided_interactions": decided,
        "unfulfilled": unfulfilled,
        "products_short": len(short),
        "chronic_shortages": [
            {
                "product": p["product"],
                "requests": p["requests"],
                "unfulfilled_requests": p["unfulfilled_requests"],
            }
            for p in sorted(chronic, key=lambda p: -p["unfulfilled_requests"])
        ],
        "penalties": {
            "repeat_shortage": round(repeat_penalty, 1),
            "breadth": round(breadth_penalty, 1),
        },
        "summary": summary,
        "drivers": drivers,
        "method": (
            "Base score is the share of decided exchanges that ended in a sale "
            "(a suggested alternative counts as half). Products refused "
            f"{REPEAT_SHORTAGE_THRESHOLD}+ times carry an extra penalty, as does "
            "being short of several products at once."
        ),
        "sampling_caveat": (
            "Measured from shop-floor audio, which samples a fraction of the "
            "day's conversations. Treat it as a strong indicator, not a census."
        ),
    }


def projected_score(current: dict, restocked_products: list[str]) -> dict:
    """
    What this component would look like once the named products are back.

    Used for the Simulated / Projected panel. Assumes the restocked products
    stop generating refusals and nothing else changes.
    """
    if not current:
        return {}

    remaining = [
        p
        for p in current.get("chronic_shortages", [])
        if p["product"].lower() not in {r.lower() for r in restocked_products}
    ]

    recovered = sum(
        p["unfulfilled_requests"]
        for p in current.get("chronic_shortages", [])
        if p["product"].lower() in {r.lower() for r in restocked_products}
    )

    decided = current.get("decided_interactions", 0)
    if not decided:
        return {}

    rate = current.get("fulfillment_rate", 0)
    new_rate = min(100.0, rate + (recovered / decided * 100.0))

    repeat_penalty = min(MAX_REPEAT_PENALTY, REPEAT_PENALTY_PER_PRODUCT * len(remaining))
    products_short = max(0, current.get("products_short", 0) - len(restocked_products))
    breadth_penalty = min(
        MAX_BREADTH_PENALTY, BREADTH_PENALTY_PER_PRODUCT * max(0, products_short - 1)
    )

    new_score = max(SCORE_FLOOR, min(100.0, new_rate - repeat_penalty - breadth_penalty))

    return {
        "label": "Simulated / Projected Impact",
        "current_score": round(current["score"]),
        "projected_score": round(new_score),
        "delta": round(new_score - current["score"]),
        "current_fulfillment_rate": rate,
        "projected_fulfillment_rate": round(new_rate, 1),
        "restocked": restocked_products,
        "assumptions": [
            f"Restocking removes all {recovered} unfilled requests for "
            f"{', '.join(restocked_products)}",
            "Demand continues at the rate heard this week",
            "No new shortages appear",
        ],
    }
