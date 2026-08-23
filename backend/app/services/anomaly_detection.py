"""
Anomaly detection.

Deliberately simple and explainable: a merchant should be able to check any
flag by hand. Two mechanisms:

  1. Percentage deviation against a 4-week baseline, with a 20% threshold.
  2. Z-score on daily revenue, flagging days beyond 2 standard deviations.

Both positive and negative anomalies are returned; the insight engine needs
the good news as much as the bad.
"""

from __future__ import annotations

from .transaction_analytics import AnalyticsContext, EVENING_HOURS, hour_range_label

DEVIATION_THRESHOLD = 20.0   # percent
HIGH_SEVERITY = 25.0         # percent; beyond this a deviation is "high"
ZSCORE_THRESHOLD = 2.0


def _severity(change_percent: float) -> str:
    magnitude = abs(change_percent)
    if magnitude >= HIGH_SEVERITY:
        return "high"
    if magnitude >= DEVIATION_THRESHOLD:
        return "medium"
    return "low"


def _anomaly(
    anomaly_id: str,
    kind: str,
    metric: str,
    change_percent: float,
    description: str,
    *,
    severity: str | None = None,
    detail: dict | None = None,
) -> dict:
    return {
        "id": anomaly_id,
        "type": kind,                       # "negative" | "positive"
        "severity": severity or _severity(change_percent),
        "metric": metric,
        "change_percent": round(change_percent, 1),
        "description": description,
        "detail": detail or {},
    }


def detect(ctx: AnalyticsContext) -> list[dict]:
    found: list[dict] = []

    # ---- 1. Evening trading window ---------------------------------------
    evening_change = ctx.evening_change
    if abs(evening_change) >= DEVIATION_THRESHOLD:
        window = hour_range_label(*EVENING_HOURS)
        direction = "below" if evening_change < 0 else "above"
        found.append(
            _anomaly(
                "evening_sales_drop" if evening_change < 0 else "evening_sales_surge",
                "negative" if evening_change < 0 else "positive",
                "Evening transactions",
                evening_change,
                f"Transaction activity between {window} is running "
                f"{abs(evening_change):.0f}% {direction} its 4-week average "
                f"({ctx.evening_current_per_day:.0f} a day now vs "
                f"{ctx.evening_baseline_per_day:.0f} before).",
                detail={
                    "window": window,
                    "current_per_day": round(ctx.evening_current_per_day, 1),
                    "baseline_per_day": round(ctx.evening_baseline_per_day, 1),
                    "revenue_gap_per_day": round(ctx.evening_revenue_gap_per_day, 2),
                },
            )
        )

    # ---- 2. Repeat-customer activity -------------------------------------
    repeat_change = ctx.repeat_txn_change
    if abs(repeat_change) >= 10.0:
        cur = ctx.customers_current
        direction = "fewer" if repeat_change < 0 else "more"
        found.append(
            _anomaly(
                "repeat_customer_drop" if repeat_change < 0 else "repeat_customer_growth",
                "negative" if repeat_change < 0 else "positive",
                "Repeat customers",
                repeat_change,
                f"Returning customers made {abs(repeat_change):.0f}% {direction} purchases "
                f"than last week. {cur['repeat_customers']} of {cur['total_customers']} "
                f"customers this week had bought from you before.",
                severity="medium" if abs(repeat_change) < HIGH_SEVERITY else "high",
                detail={
                    "repeat_customers": cur["repeat_customers"],
                    "total_customers": cur["total_customers"],
                    "repeat_rate": cur["repeat_customer_rate"],
                },
            )
        )

    # ---- 3. Individual weak / strong days (z-score + weekday baseline) ----
    zscores = ctx.daily_revenue_zscores()
    by_date = {row["date"]: row for row in ctx.weekday_comparison()}

    for timestamp, z in zscores.items():
        if abs(float(z)) <= ZSCORE_THRESHOLD:
            continue
        iso = timestamp.date().isoformat()
        row = by_date.get(iso)
        if not row:
            continue

        change = row["change_percent"]
        negative = change < 0
        found.append(
            _anomaly(
                f"{row['day'].lower()}_revenue_{'drop' if negative else 'spike'}",
                "negative" if negative else "positive",
                f"{row['day']} revenue",
                change,
                f"{row['day']} {timestamp.strftime('%d %b')} took Rs {row['revenue']:,.0f} against a "
                f"{row['day']} average of Rs {row['historical_average']:,.0f} "
                f"({abs(change):.0f}% {'below' if negative else 'above'} normal).",
                severity="high" if abs(float(z)) > 2.5 else "medium",
                detail={
                    "date": iso,
                    "revenue": row["revenue"],
                    "historical_average": row["historical_average"],
                    "z_score": round(float(z), 2),
                },
            )
        )

    # ---- 4. Weekend performance ------------------------------------------
    weekend_change = ctx.weekend_change
    if abs(weekend_change) >= 8.0:
        found.append(
            _anomaly(
                "weekend_revenue_growth" if weekend_change > 0 else "weekend_revenue_drop",
                "positive" if weekend_change > 0 else "negative",
                "Weekend revenue",
                weekend_change,
                f"Weekend takings are {abs(weekend_change):.0f}% "
                f"{'above' if weekend_change > 0 else 'below'} their 4-week average.",
                severity="medium",
            )
        )

    # ---- 5. Average basket size ------------------------------------------
    aov_change = ctx.avg_ticket_vs_baseline
    if abs(aov_change) >= 2.0:
        found.append(
            _anomaly(
                "average_ticket_growth" if aov_change > 0 else "average_ticket_drop",
                "positive" if aov_change > 0 else "negative",
                "Average transaction value",
                aov_change,
                f"Customers are spending Rs {ctx.current.avg_ticket:,.0f} per visit, "
                f"{abs(aov_change):.0f}% {'more' if aov_change > 0 else 'less'} than your 4-week average.",
                severity="low",
            )
        )

    order = {"high": 0, "medium": 1, "low": 2}
    found.sort(key=lambda a: (order.get(a["severity"], 3), -abs(a["change_percent"])))
    return found


def anomalies_payload(ctx: AnalyticsContext) -> dict:
    found = detect(ctx)
    return {
        "anomalies": found,
        "counts": {
            "total": len(found),
            "negative": sum(1 for a in found if a["type"] == "negative"),
            "positive": sum(1 for a in found if a["type"] == "positive"),
            "high_severity": sum(1 for a in found if a["severity"] == "high"),
        },
        "thresholds": {
            "deviation_percent": DEVIATION_THRESHOLD,
            "z_score": ZSCORE_THRESHOLD,
        },
    }
