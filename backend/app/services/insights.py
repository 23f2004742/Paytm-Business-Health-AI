"""
Insight ranking engine.

Turns raw anomalies plus a few structural observations into a short, ranked
list a merchant can act on. Ranking is deterministic: the same data always
produces the same order.

Impact score = severity weight x magnitude x business relevance

  severity     how far outside normal the signal is
  magnitude    log-damped size of the change, so a 200% blip does not bury
               a sustained 30% decline in the merchant's main trading window
  relevance    how directly the metric drives revenue

Returns 3-5 insights: problems first, then opportunities, then wins.
"""

from __future__ import annotations

import math

from .transaction_analytics import AnalyticsContext, AFTERNOON_HOURS, hour_range_label
from .anomaly_detection import detect

SEVERITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}

# How directly each metric drives revenue for an F&B merchant.
RELEVANCE = {
    "evening_sales_drop": 1.00,
    "evening_sales_surge": 0.85,
    "repeat_customer_drop": 0.90,
    "repeat_customer_growth": 0.75,
    "weekend_revenue_growth": 0.70,
    "weekend_revenue_drop": 0.80,
    "average_ticket_growth": 0.55,
    "average_ticket_drop": 0.65,
}
DEFAULT_RELEVANCE = 0.60          # single-day revenue anomalies land here

MAX_INSIGHTS = 5


def _magnitude(change_percent: float) -> float:
    """Log damping: big changes matter more, but not linearly more."""
    return math.log1p(abs(change_percent)) / math.log1p(100.0)


def _impact(anomaly: dict) -> float:
    severity = SEVERITY_WEIGHT.get(anomaly["severity"], 1.0)
    relevance = RELEVANCE.get(anomaly["id"], DEFAULT_RELEVANCE)
    return round(severity * _magnitude(anomaly["change_percent"]) * relevance * 100, 1)


def _from_anomaly(anomaly: dict) -> dict:
    return {
        "id": anomaly["id"],
        "kind": "negative" if anomaly["type"] == "negative" else "positive",
        "title": anomaly["metric"],
        "change_percent": anomaly["change_percent"],
        "severity": anomaly["severity"],
        "description": anomaly["description"],
        "impact_score": _impact(anomaly),
        "detail": anomaly.get("detail", {}),
    }


def _afternoon_opportunity(ctx: AnalyticsContext) -> dict | None:
    """
    The structural gap between peak and quietest trading hours. Not an anomaly
    (nothing changed), but it is the largest untapped block of the day, so it
    belongs in the ranked list as an opportunity.
    """
    peaks = ctx.peak_hours(3)
    weak = [h for h in ctx.hourly_distribution() if AFTERNOON_HOURS[0] <= h["hour"] <= AFTERNOON_HOURS[1]]
    if not peaks or not weak:
        return None

    peak_avg = sum(p["baseline"] for p in peaks) / len(peaks)
    weak_avg = sum(w["baseline"] for w in weak) / len(weak)
    if peak_avg <= 0:
        return None

    gap = (1.0 - weak_avg / peak_avg) * 100.0
    if gap < 40.0:
        return None

    window = hour_range_label(*AFTERNOON_HOURS)
    return {
        "id": "afternoon_lull_opportunity",
        "kind": "opportunity",
        "title": "Quiet afternoon window",
        "change_percent": round(-gap, 1),
        "severity": "low",
        "description": (
            f"Between {window} you average {weak_avg:.0f} transactions an hour against "
            f"{peak_avg:.0f} at peak, the quietest stretch of your trading day."
        ),
        "impact_score": round(1.4 * _magnitude(gap) * 0.65 * 100, 1),
        "detail": {
            "window": window,
            "per_hour": round(weak_avg, 1),
            "peak_per_hour": round(peak_avg, 1),
        },
    }


WEEKEND_DAYS = ("saturday", "sunday")


def _dedupe(insights: list[dict]) -> list[dict]:
    """
    Drop single-day weekend spikes when the general weekend trend is already
    present. They are the same story told twice, and the trend is the more
    useful framing for a merchant.
    """
    has_weekend_trend = any(i["id"] == "weekend_revenue_growth" for i in insights)
    if not has_weekend_trend:
        return insights
    return [
        i for i in insights
        if not (i["kind"] == "positive" and i["id"].startswith(WEEKEND_DAYS))
    ]


def build_insights(ctx: AnalyticsContext) -> list[dict]:
    insights = _dedupe([_from_anomaly(a) for a in detect(ctx)])

    opportunity = _afternoon_opportunity(ctx)
    if opportunity:
        insights.append(opportunity)

    # Rank by impact, then present problems before opportunities and wins so
    # the merchant reads the thing that needs a decision first.
    insights.sort(key=lambda i: -i["impact_score"])
    order = {"negative": 0, "opportunity": 1, "positive": 2}

    selected = insights[:MAX_INSIGHTS]

    # Guarantee at least one positive makes the cut. A screen of pure bad news
    # is neither accurate nor useful here.
    if not any(i["kind"] == "positive" for i in selected):
        positives = [i for i in insights if i["kind"] == "positive"]
        if positives:
            selected = selected[: MAX_INSIGHTS - 1] + [positives[0]]

    selected.sort(key=lambda i: (order.get(i["kind"], 3), -i["impact_score"]))
    return selected


def insights_payload(ctx: AnalyticsContext) -> dict:
    items = build_insights(ctx)
    return {
        "insights": items,
        "negative": [i for i in items if i["kind"] == "negative"],
        "positive": [i for i in items if i["kind"] == "positive"],
        "opportunities": [i for i in items if i["kind"] == "opportunity"],
        "headline": items[0]["description"] if items else "No significant changes this week.",
    }
