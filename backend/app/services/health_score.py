"""
Business Health Score.

Fully deterministic: the same transactions always produce the same score.
No model is involved in producing the number; the AI layer only explains it.

Five components, each normalised to 0-100, combined with fixed weights:

    Revenue Health      25%
    Customer Health     20%
    Transaction Health  20%
    Business Stability  20%
    Growth Potential    15%

Two design choices worth knowing:

  * Losses are weighted more heavily than equivalent gains. A 10% revenue
    fall moves the score about twice as far as a 10% rise. That matches how
    a merchant actually experiences risk, and it stops a single strong week
    from masking a developing problem.

  * Component scores above SOFT_CEILING are compressed. Without it every
    healthy week pins at ~95 and the score loses resolution exactly where
    merchants need it: telling a good week from a great one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .transaction_analytics import AnalyticsContext

# The five transaction components. These still sum to 1.0 on their own, which
# keeps every existing caller (notably `project_score_after`) correct.
WEIGHTS = {
    "revenue_health": 0.25,
    "customer_health": 0.20,
    "transaction_health": 0.20,
    "stability": 0.20,
    "growth_potential": 0.15,
}


def demand_weight() -> float:
    """
    Weight given to Demand Fulfilment, the sixth component.

    Configurable because it trades off two real risks: too low and unmet
    demand never reaches the number a merchant actually looks at; too high
    and one microphone sampling a fraction of the day's conversations starts
    dominating a score built on a complete transaction ledger.

    Set DEMAND_FULFILLMENT_WEIGHT=0 to restore the original five-component
    score exactly.
    """
    import os

    try:
        value = float(os.environ.get("DEMAND_FULFILLMENT_WEIGHT", "0.15"))
    except ValueError:
        return 0.15
    return max(0.0, min(0.4, value))


def effective_weights(has_demand: bool) -> dict:
    """
    The weights actually applied.

    With no shop-floor evidence the demand weight is redistributed across the
    five transaction components in proportion. That is what makes the score
    comparable week to week: a quiet week with no captured conversation scores
    on exactly the same basis as before this component existed, rather than
    being punished for missing data.
    """
    weight = demand_weight()
    if not has_demand or weight <= 0:
        return dict(WEIGHTS)

    scale = 1.0 - weight
    weights = {key: value * scale for key, value in WEIGHTS.items()}
    weights["demand_fulfillment"] = weight
    return weights

SOFT_CEILING = 85.0
SOFT_CEILING_SLOPE = 0.5

# Z-score past which a day counts as a genuine revenue anomaly.
ANOMALY_Z = 2.0
ANOMALY_PENALTY = 4.0

STATUS_BANDS = [
    (80, "Excellent"),
    (65, "Stable"),
    (40, "Needs Attention"),
    (0, "Critical"),
]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _soften(score: float) -> float:
    """Compress the top of the range so strong weeks stay distinguishable."""
    if score <= SOFT_CEILING:
        return score
    return SOFT_CEILING + (score - SOFT_CEILING) * SOFT_CEILING_SLOPE


def _asym(value: float, down_weight: float, up_weight: float) -> float:
    """Weight a percentage change asymmetrically: declines count for more."""
    return (value * down_weight) if value < 0 else (value * up_weight)


def status_for(score: float) -> str:
    for threshold, label in STATUS_BANDS:
        if score >= threshold:
            return label
    return "Critical"


@dataclass
class ComponentScore:
    key: str
    label: str
    score: float
    weight: float
    summary: str
    drivers: list[dict]

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score),
            "weight": self.weight,
            "weighted_points": round(self.score * self.weight, 1),
            "status": status_for(self.score),
            "summary": self.summary,
            "drivers": self.drivers,
        }


def _driver(label: str, value: str, tone: str) -> dict:
    return {"label": label, "value": value, "tone": tone}


def _tone(pct: float, good_when_positive: bool = True) -> str:
    if abs(pct) < 1.5:
        return "neutral"
    positive = pct > 0 if good_when_positive else pct < 0
    return "positive" if positive else "negative"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


# --------------------------------------------------------------- components

def revenue_health(ctx: AnalyticsContext) -> ComponentScore:
    wow = ctx.revenue_growth_wow
    base = ctx.revenue_vs_baseline

    score = _clamp(78.0 + _asym(wow, 0.50, 0.25) + _asym(base, 0.34, 0.17))

    if wow <= -5:
        summary = (
            f"Weekly revenue fell {abs(wow):.1f}% against last week and is running "
            f"{abs(base):.1f}% below your 4-week average."
        )
    elif wow >= 5:
        summary = f"Weekly revenue grew {wow:.1f}% week-over-week and is holding above your 4-week average."
    else:
        summary = f"Weekly revenue is broadly flat ({_pct(wow)} week-over-week)."

    return ComponentScore(
        key="revenue_health",
        label="Revenue Health",
        score=_soften(score),
        weight=WEIGHTS["revenue_health"],
        summary=summary,
        drivers=[
            _driver("Week-over-week revenue", _pct(wow), _tone(wow)),
            _driver("Vs 4-week average", _pct(base), _tone(base)),
            _driver("This week", f"Rs {ctx.current.revenue:,.0f}", "neutral"),
        ],
    )


def customer_health(ctx: AnalyticsContext) -> ComponentScore:
    cur = ctx.customers_current
    repeat_rate = cur["repeat_customer_rate"]
    repeat_change = ctx.repeat_txn_change
    new_change = ctx.new_customer_change

    # Level: how loyal the base is right now (40% repeat rate reads as healthy).
    level = _clamp(repeat_rate / 40.0 * 100.0)
    # Momentum: which way that loyalty is moving.
    momentum = _clamp(68.0 + 1.2 * repeat_change + 0.5 * new_change)

    score = _clamp(0.45 * level + 0.55 * momentum)

    if repeat_change <= -8:
        summary = (
            f"Repeat customers made {abs(repeat_change):.1f}% fewer purchases than last week. "
            f"{cur['repeat_customers']} of {cur['total_customers']} customers this week were returning."
        )
    elif repeat_change >= 8:
        summary = f"Repeat purchases grew {repeat_change:.1f}%. Your regulars are coming back more often."
    else:
        summary = (
            f"{cur['repeat_customers']} of {cur['total_customers']} customers this week were returning "
            f"({repeat_rate:.0f}% repeat rate)."
        )

    return ComponentScore(
        key="customer_health",
        label="Customer Health",
        score=_soften(score),
        weight=WEIGHTS["customer_health"],
        summary=summary,
        drivers=[
            _driver("Repeat purchases", _pct(repeat_change), _tone(repeat_change)),
            _driver("Repeat customer rate", f"{repeat_rate:.0f}%", "neutral"),
            _driver("New customers", _pct(new_change), _tone(new_change)),
        ],
    )


def transaction_health(ctx: AnalyticsContext) -> ComponentScore:
    wow = ctx.txn_growth_wow
    base = ctx.txn_vs_baseline
    aov = ctx.avg_ticket_vs_baseline

    score = _clamp(87.0 + _asym(wow, 0.70, 0.35) + _asym(base, 0.50, 0.25) + 0.40 * aov)

    if wow <= -4:
        summary = (
            f"You handled {ctx.current.txns:,} transactions this week, {abs(wow):.1f}% fewer than last week, "
            f"though the average basket is up {aov:.1f}% against your 4-week average."
            if aov > 0 else
            f"You handled {ctx.current.txns:,} transactions this week, {abs(wow):.1f}% fewer than last week."
        )
    else:
        summary = (
            f"{ctx.current.txns:,} transactions this week at an average of "
            f"Rs {ctx.current.avg_ticket:,.0f} per sale."
        )

    return ComponentScore(
        key="transaction_health",
        label="Transaction Health",
        score=_soften(score),
        weight=WEIGHTS["transaction_health"],
        summary=summary,
        drivers=[
            _driver("Transaction volume", _pct(wow), _tone(wow)),
            _driver("Average sale", f"Rs {ctx.current.avg_ticket:,.0f}", _tone(aov)),
            _driver("Vs 4-week average", _pct(base), _tone(base)),
        ],
    )


def stability(ctx: AnalyticsContext) -> ComponentScore:
    cv = ctx.revenue_cv
    zscores = ctx.daily_revenue_zscores()
    anomaly_days = int((zscores.abs() > ANOMALY_Z).sum())

    # A CV up to 0.12 is normal day-to-day variation for an F&B merchant.
    score = _clamp(100.0 - max(0.0, cv - 0.12) * 250.0 - ANOMALY_PENALTY * anomaly_days)

    if anomaly_days:
        worst = zscores.idxmin()
        summary = (
            f"{anomaly_days} day{'s' if anomaly_days > 1 else ''} this week fell outside your normal range. "
            f"The largest was {worst.strftime('%A %d %b')}."
        )
    else:
        summary = "Daily takings stayed within your normal range all week."

    return ComponentScore(
        key="stability",
        label="Business Stability",
        score=_soften(score),
        weight=WEIGHTS["stability"],
        summary=summary,
        drivers=[
            _driver("Day-to-day consistency", f"{max(0.0, 100 - cv * 100):.0f}/100", _tone(-cv * 100)),
            _driver("Unusual days", str(anomaly_days), "negative" if anomaly_days else "positive"),
        ],
    )


def growth_potential(ctx: AnalyticsContext) -> ComponentScore:
    weekend = ctx.weekend_change
    aov = ctx.avg_ticket_vs_baseline

    # Headroom: the gap between peak and weakest trading hours is unrealised
    # capacity. A wide gap is an opportunity, so it scores positively.
    peaks = ctx.peak_hours(3)
    weak = ctx.weak_hours(3)
    weak_chrono = sorted(weak, key=lambda w: w["hour"])
    peak_avg = sum(p["baseline"] for p in peaks) / max(len(peaks), 1)
    weak_avg = sum(w["baseline"] for w in weak) / max(len(weak), 1)
    headroom = _clamp((1.0 - (weak_avg / peak_avg if peak_avg else 1.0)) * 18.0, 0, 15)

    score = _clamp(
        58.0
        + 0.8 * min(weekend, 10.0)
        + 0.3 * max(weekend - 10.0, 0.0)
        + 0.7 * aov
        + headroom
    )

    parts = []
    if weekend > 2:
        parts.append(f"weekend revenue is up {weekend:.1f}%")
    if aov > 1:
        parts.append(f"average basket is up {aov:.1f}%")
    parts.append(
        f"your {weak_chrono[0]['label']} to {weak_chrono[-1]['label']} window is running well below peak"
    )
    summary = "Positive signals to build on: " + ", ".join(parts) + "."

    return ComponentScore(
        key="growth_potential",
        label="Growth Potential",
        score=_soften(score),
        weight=WEIGHTS["growth_potential"],
        summary=summary,
        drivers=[
            _driver("Weekend revenue", _pct(weekend), _tone(weekend)),
            _driver("Average basket", _pct(aov), _tone(aov)),
            _driver(
                "Untapped hours",
                f"{weak_chrono[0]['label']} - {weak_chrono[-1]['label']}",
                "neutral",
            ),
        ],
    )


COMPONENT_BUILDERS = [
    revenue_health,
    customer_health,
    transaction_health,
    stability,
    growth_potential,
]


def demand_fulfillment_component(demand: dict, weight: float) -> ComponentScore:
    """The sixth component, built from the shop-floor fulfilment analysis."""
    return ComponentScore(
        key="demand_fulfillment",
        label="Demand Fulfilment",
        score=float(demand["score"]),
        weight=weight,
        summary=demand["summary"],
        drivers=demand["drivers"],
    )


def compute_components(
    ctx: AnalyticsContext, demand: dict | None = None
) -> list[ComponentScore]:
    """
    The scored components.

    `demand` is the output of `demand_fulfillment.compute()`, or None when
    there is not enough shop-floor evidence to score it.
    """
    weights = effective_weights(demand is not None)
    components = [build(ctx) for build in COMPONENT_BUILDERS]

    # Re-weight the transaction components to make room for demand.
    for component in components:
        component.weight = weights[component.key]

    if demand is not None and "demand_fulfillment" in weights:
        components.append(
            demand_fulfillment_component(demand, weights["demand_fulfillment"])
        )

    return components


def compute_score(ctx: AnalyticsContext, demand: dict | None = None) -> float:
    total = sum(c.score * c.weight for c in compute_components(ctx, demand))
    return _clamp(total)


def health_score_payload(
    ctx: AnalyticsContext,
    previous_ctx: AnalyticsContext,
    demand: dict | None = None,
    previous_demand: dict | None = None,
) -> dict:
    """
    The score payload.

    `previous_demand` matters more than it looks: comparing a week that has
    shop-floor data against one that does not would make the score move for
    no reason other than the feature being switched on. Both weeks are scored
    on the same basis or neither is.
    """
    components = compute_components(ctx, demand)
    overall = _clamp(sum(c.score * c.weight for c in components))
    previous = compute_score(previous_ctx, previous_demand)

    overall_r = round(overall)
    previous_r = round(previous)

    change = overall_r - previous_r

    # The band label describes the level; the trend describes the direction.
    # A sharp fall inside a healthy band still warrants the merchant's attention,
    # so the two are reported separately rather than collapsed into one label.
    if change <= -5:
        trend = "declining"
    elif change >= 5:
        trend = "improving"
    else:
        trend = "steady"

    return {
        "overall_score": overall_r,
        "previous_score": previous_r,
        "change": change,
        "status": status_for(overall),
        "trend": trend,
        "needs_attention": trend == "declining" or overall < 65,
        "status_bands": [{"min": t, "label": l} for t, l in STATUS_BANDS],
        "components": {c.key: round(c.score) for c in components},
        "component_detail": [c.as_dict() for c in components],
        "weights": {c.key: round(c.weight, 4) for c in components},
        "base_weights": WEIGHTS,
        "demand_fulfillment_included": demand is not None,
        "demand_fulfillment_weight": demand_weight() if demand is not None else 0.0,
        "comparable_basis": (demand is not None) == (previous_demand is not None),
        "as_of": ctx.anchor.date().isoformat(),
    }
