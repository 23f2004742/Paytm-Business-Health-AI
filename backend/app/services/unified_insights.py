"""
The unified business brain.

This is the component that makes Paytm Vyapaar AI one product rather than two
dashboards. It joins:

    transaction intelligence   what customers actually bought
    shop-floor intelligence    what customers asked for
    availability signals       what they asked for and could not get

The join is **temporal**. Every transaction anomaly carries a window (hours of
the day, and a date range). Every shop event carries a full ISO timestamp. A
unified insight exists when unfulfilled demand falls inside the same window as
a transaction decline.

------------------------------------------------------------------------------
On causation
------------------------------------------------------------------------------
Co-occurrence in a window is not proof of anything. Two signals overlapping in
time is exactly as much as this system knows, and the language it uses says
exactly that much:

    "coincides with"   "may be contributing"   "potential missed sale"

There is no path through this module that emits "caused by", "because of" or
"as a result of". Confidence is published alongside every insight, is derived
from the overlap rather than asserted, and is capped below certainty: a
correlation this thin should never read as a proven fact, however convenient
that would be for a demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from . import demand_analysis
from .transaction_analytics import (
    AFTERNOON_HOURS,
    AnalyticsContext,
    EVENING_HOURS,
    hour_range_label,
)

# The strongest claim this engine is allowed to make.
MAX_CONFIDENCE = 0.90
MIN_CONFIDENCE = 0.35

# An anomaly needs at least this many unfulfilled requests inside its window
# before the overlap is worth reporting as a joint signal.
MIN_OVERLAP_REQUESTS = 2

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SEVERITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}


# ------------------------------------------------------- anomaly -> window

def anomaly_window(
    anomaly: dict, ctx: AnalyticsContext
) -> Optional[tuple[tuple[int, int], datetime, datetime, str]]:
    """
    The slice of time an anomaly describes: (hours, start, end, label).

    Returns None for anomalies with no meaningful time window, which simply
    means they cannot participate in a temporal join.
    """
    anomaly_id = anomaly.get("id", "")
    week_start = ctx.current.start.to_pydatetime()
    week_end = ctx.current.end.to_pydatetime() + timedelta(hours=23, minutes=59)

    if anomaly_id.startswith("evening_sales"):
        return EVENING_HOURS, week_start, week_end, hour_range_label(*EVENING_HOURS)

    if anomaly_id == "afternoon_lull_opportunity":
        return AFTERNOON_HOURS, week_start, week_end, hour_range_label(*AFTERNOON_HOURS)

    # Single-day revenue anomalies: the whole trading day, that date only.
    detail = anomaly.get("detail") or {}
    if "date" in detail:
        try:
            day = datetime.fromisoformat(str(detail["date"]))
        except ValueError:
            return None
        return (
            (0, 23),
            day.replace(hour=0, minute=0, second=0),
            day.replace(hour=23, minute=59, second=59),
            day.strftime("%A %d %b"),
        )

    # Anomalies with no time structure (repeat-customer behaviour spans the
    # whole week) are deliberately excluded from the join. A window that
    # covers everything overlaps everything, so the "correlation" would be an
    # artefact of the window rather than a finding. They still surface on
    # their own.
    return None


# -------------------------------------------------------------- confidence

def _confidence(
    *,
    overlap_requests: int,
    total_unfulfilled: int,
    change_percent: float,
    signal_confidence: float,
) -> float:
    """
    How much the overlap is worth believing.

    Four contributions, each capped, then held below MAX_CONFIDENCE:

      overlap    how much of the product's unmet demand sits in this window
      volume     how many unfilled requests there are at all
      deviation  how far the transaction metric moved
      extraction how sure the pipeline is it heard the product correctly
    """
    overlap = (overlap_requests / total_unfulfilled) if total_unfulfilled else 0.0
    volume = min(1.0, overlap_requests / 10.0)
    deviation = min(1.0, abs(change_percent) / 30.0)

    score = (
        MIN_CONFIDENCE
        + 0.20 * overlap
        + 0.18 * volume
        + 0.15 * deviation
        + 0.12 * min(1.0, signal_confidence)
    )
    return round(min(MAX_CONFIDENCE, score), 2)


def _impact(severity: str, change_percent: float, requests: int) -> float:
    """Ranking weight: how bad, how big, how often."""
    magnitude = min(1.0, abs(change_percent) / 40.0)
    frequency = min(1.0, requests / 15.0)
    return round(
        SEVERITY_WEIGHT.get(severity, 1.0) * (0.5 * magnitude + 0.5 * frequency) * 100,
        1,
    )


# ----------------------------------------------------------------- builders

def _joint_insight(
    anomaly: dict,
    window: tuple[tuple[int, int], datetime, datetime, str],
    product: dict,
    overlap_requests: int,
    *,
    basket_value: Optional[float],
) -> dict:
    hours, start, end, window_label = window
    change = float(anomaly.get("change_percent", 0.0))
    name = product["product"]
    total_unfulfilled = product["unfulfilled_requests"]

    confidence = _confidence(
        overlap_requests=overlap_requests,
        total_unfulfilled=total_unfulfilled,
        change_percent=change,
        signal_confidence=product.get("average_confidence", 0.7),
    )

    severity = anomaly.get("severity", "medium")
    if overlap_requests >= 8 and severity != "high":
        severity = "high"

    lost_revenue = demand_analysis.estimate_lost_revenue(overlap_requests, basket_value)

    explanation = (
        f"{anomaly['metric']} in the {window_label} window "
        f"{'fell' if change < 0 else 'rose'} {abs(change):.0f}% against its 4-week "
        f"average. During that same window customers asked for {name} "
        f"{overlap_requests} time{'s' if overlap_requests != 1 else ''} while it was "
        f"unavailable. The two signals coincide, and the unmet requests may be "
        f"contributing to the drop, though the transaction data alone cannot "
        f"confirm that."
    )

    return {
        "id": f"unified_{anomaly.get('id', 'signal')}_{product['family']}",
        "kind": "unified",
        "title": f"Potential lost sales during {window_label.lower()}",
        "severity": severity,
        "confidence": confidence,
        "impact_score": _impact(severity, change, overlap_requests),
        "transaction_signal": {
            "metric": anomaly.get("metric"),
            "change_percent": round(change, 1),
            "window": window_label,
            "description": anomaly.get("description"),
        },
        "shop_signal": {
            "product": name,
            "requests": product["requests"],
            "requests_in_window": overlap_requests,
            "unfulfilled_requests": total_unfulfilled,
            "availability": product["availability"],
            "catalog_items": product["catalog_items"][:3],
        },
        "explanation": explanation,
        "recommended_actions": [
            f"Restock {name}",
            f"Launch an engagement campaign for the {window_label} window",
        ],
        "evidence": {
            "window_hours": list(hours),
            "window_start": start.isoformat(timespec="seconds"),
            "window_end": end.isoformat(timespec="seconds"),
            "overlap_requests": overlap_requests,
            "estimated_lost_revenue": lost_revenue,
        },
        "correlation_note": (
            "Temporal co-occurrence only. Shop-floor demand and transaction "
            "activity are measured independently and no causal link is claimed."
        ),
    }


def _shop_only_insight(product: dict, *, basket_value: Optional[float]) -> dict:
    """Unmet demand that does not line up with any transaction anomaly."""
    name = product["product"]
    unfulfilled = product["unfulfilled_requests"]
    severity = "high" if unfulfilled >= 8 else "medium" if unfulfilled >= 3 else "low"

    return {
        "id": f"shop_demand_{product['family']}",
        "kind": "shop",
        "title": f"{name} is in demand and out of stock",
        "severity": severity,
        "confidence": round(min(MAX_CONFIDENCE, product.get("average_confidence", 0.7)), 2),
        "impact_score": _impact(severity, 0.0, unfulfilled),
        "transaction_signal": None,
        "shop_signal": {
            "product": name,
            "requests": product["requests"],
            "requests_in_window": unfulfilled,
            "unfulfilled_requests": unfulfilled,
            "availability": product["availability"],
            "catalog_items": product["catalog_items"][:3],
        },
        "explanation": (
            f"Customers asked for {name} {product['requests']} times, and "
            f"{unfulfilled} of those requests could not be filled. Each one is a "
            f"potential missed sale that never reaches your transaction data, "
            f"because a sale that does not happen leaves no record."
        ),
        "recommended_actions": [f"Restock {name}"],
        "evidence": {
            "unfulfilled_share_percent": product["unfulfilled_share"],
            "peak_hour": product["peak_hour"],
            "estimated_lost_revenue": demand_analysis.estimate_lost_revenue(
                unfulfilled, basket_value
            ),
        },
        "correlation_note": (
            "Measured from shop-floor conversation only. No transaction signal "
            "is linked to this finding."
        ),
    }


def _transaction_only_insight(anomaly: dict) -> dict:
    """A transaction anomaly with no shop-floor signal to pair it with."""
    change = float(anomaly.get("change_percent", 0.0))
    severity = anomaly.get("severity", "medium")

    return {
        "id": f"txn_{anomaly.get('id', 'signal')}",
        "kind": "transaction",
        "title": anomaly.get("metric", "Transaction signal"),
        "severity": severity,
        "confidence": 0.95,   # measured directly from the ledger, not inferred
        "impact_score": _impact(severity, change, 0),
        "transaction_signal": {
            "metric": anomaly.get("metric"),
            "change_percent": round(change, 1),
            "window": (anomaly.get("detail") or {}).get("window"),
            "description": anomaly.get("description"),
        },
        "shop_signal": None,
        "explanation": anomaly.get("description", ""),
        "recommended_actions": [],
        "evidence": anomaly.get("detail") or {},
        "correlation_note": "Measured directly from transaction data.",
    }


# -------------------------------------------------------------------- build

def build_unified_insights(
    ctx: AnalyticsContext,
    anomalies: list[dict],
    events: list[dict],
    *,
    max_insights: int = 6,
) -> list[dict]:
    """
    Rank every signal the product holds, joined where the timing lines up.

    Joint insights are placed first regardless of raw impact score: a signal
    corroborated by two independent sources is more actionable than a larger
    one seen from a single angle, and it is the only kind of finding neither
    source could have produced alone.
    """
    basket_value = round(ctx.current.avg_ticket, 2) if ctx.current.txns else None
    all_products = {p["family"]: p for p in demand_analysis.product_demand(events)}

    negatives = [a for a in anomalies if a.get("type") == "negative"]

    def sort_key(insight: dict) -> tuple:
        return (
            0 if insight["kind"] == "unified" else 1,
            SEVERITY_RANK.get(insight["severity"], 3),
            -insight["impact_score"],
            -insight["confidence"],
        )

    # ---- 1. Joint candidates: a shortage inside an anomaly's own window ----
    candidates: list[tuple[dict, str, str]] = []   # (insight, family, anomaly_id)

    for anomaly in negatives:
        window = anomaly_window(anomaly, ctx)
        if window is None:
            continue
        hours, start, end, _label = window

        in_window = demand_analysis.filter_events(
            events, hours=hours, start=start, end=end
        )
        for product in demand_analysis.product_demand(in_window):
            overlap = product["unfulfilled_requests"]
            if overlap < MIN_OVERLAP_REQUESTS:
                continue
            family = product["family"]
            # Report the product's full weekly demand, but score the overlap.
            full = all_products.get(family, product)
            candidates.append(
                (
                    _joint_insight(anomaly, window, full, overlap, basket_value=basket_value),
                    family,
                    anomaly.get("id", ""),
                )
            )

    # One joint insight per product: the same shortage can overlap several
    # anomalies, and telling that story three times is noise. The strongest
    # framing wins.
    candidates.sort(key=lambda c: sort_key(c[0]))

    insights: list[dict] = []
    joined_families: set[str] = set()
    joined_anomalies: set[str] = set()

    for insight, family, anomaly_id in candidates:
        if family in joined_families:
            continue
        joined_families.add(family)
        # Only an anomaly whose joint insight actually survived counts as
        # told. Otherwise a deduplicated pairing would silently erase a real
        # transaction signal from the merchant's view.
        joined_anomalies.add(anomaly_id)
        insights.append(insight)

    # ---- 2. Unmet demand that nothing in the ledger corroborates ----------
    for family, product in all_products.items():
        if family in joined_families or product["unfulfilled_requests"] <= 0:
            continue
        insights.append(_shop_only_insight(product, basket_value=basket_value))

    # ---- 3. Transaction signals with no shop-floor counterpart -----------
    for anomaly in negatives:
        if anomaly.get("id", "") in joined_anomalies:
            continue
        insights.append(_transaction_only_insight(anomaly))

    insights.sort(key=sort_key)
    return insights[:max_insights]


def headline(insights: list[dict], positives: list[dict]) -> str:
    """The one paragraph the dashboard leads with."""
    if not insights:
        return (
            "Nothing significant changed this week, and no unmet demand was heard "
            "on the shop floor."
        )

    lead = insights[0]
    text = lead["explanation"]

    if positives:
        best = positives[0]
        text += f" On the positive side, {best['description'][0].lower()}{best['description'][1:]}"
    return text


def unified_payload(
    ctx: AnalyticsContext,
    anomalies: list[dict],
    events: list[dict],
    positives: Optional[list[dict]] = None,
) -> dict:
    """The payload behind GET /api/insights/unified."""
    insights = build_unified_insights(ctx, anomalies, events)
    positives = positives or [a for a in anomalies if a.get("type") == "positive"]

    return {
        "insights": insights,
        "headline": headline(insights, positives),
        "positive_signals": positives[:3],
        "counts": {
            "total": len(insights),
            "unified": sum(1 for i in insights if i["kind"] == "unified"),
            "shop_only": sum(1 for i in insights if i["kind"] == "shop"),
            "transaction_only": sum(1 for i in insights if i["kind"] == "transaction"),
        },
        "methodology": {
            "join": "Temporal overlap between transaction anomaly windows and shop events.",
            "causation": (
                "No causal claim is made. Overlap is reported as co-occurrence and "
                "confidence is capped at "
                f"{int(MAX_CONFIDENCE * 100)}%."
            ),
            "max_confidence": MAX_CONFIDENCE,
        },
        "as_of": ctx.anchor.date().isoformat(),
    }
