"""
Demand analysis.

Aggregates raw shop events into the two facts a merchant can act on:

    what customers keep asking for      (demand)
    what they asked for and did not get (unfulfilled demand)

The original project counted item mentions and listed out-of-stock reports
separately, so nothing ever connected the two. Here they are the same record:
a product carries both its request count and how many of those requests went
unfilled, which is what makes "high demand AND out of stock" expressible.

Products are aggregated by **family** (the brand token) rather than by SKU. A
merchant restocks Maggi, not specifically the 70g pack, and a customer asking
for "Maggi" has not chosen a variant yet.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

# Below this a product is a one-off request, not a demand signal.
HIGH_DEMAND_MIN_REQUESTS = 3

# Above this share of requests going unfilled, availability is the story.
UNFULFILLED_SHARE_ALERT = 0.5


def _parse(timestamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None


def filter_events(
    events: Iterable[dict],
    *,
    hours: Optional[tuple[int, int]] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    families: Optional[set[str]] = None,
) -> list[dict]:
    """Slice events by hour-of-day, date range and/or product family."""
    out = []
    for event in events:
        if families is not None and event.get("product_family") not in families:
            continue
        if hours is not None:
            hour = event.get("hour")
            if hour is None or not (hours[0] <= hour <= hours[1]):
                continue
        if start is not None or end is not None:
            when = _parse(event.get("timestamp", ""))
            if when is None:
                continue
            if start is not None and when < start:
                continue
            if end is not None and when > end:
                continue
        out.append(event)
    return out


def product_demand(events: Iterable[dict]) -> list[dict]:
    """
    Per-family demand, ranked by unfulfilled requests then total requests.

    A product that was asked for 14 times and unavailable 14 of them outranks
    one asked for 30 times and always in stock, because only the first one
    represents money the merchant did not take.
    """
    buckets: dict[str, dict] = {}

    for event in events:
        family = event.get("product_family")
        if not family or event.get("intent") == "suspicious_activity":
            continue

        bucket = buckets.setdefault(
            family,
            {
                "product": event.get("product_display") or family.title(),
                "family": family,
                "catalog_items": set(),
                "requests": 0,
                "unfulfilled": 0,
                "hours": defaultdict(int),
                "first_seen": None,
                "last_seen": None,
                "confidence_sum": 0.0,
            },
        )

        bucket["requests"] += 1
        bucket["catalog_items"].add(event.get("product", ""))
        bucket["confidence_sum"] += float(event.get("confidence") or 0)
        if event.get("availability") == "out_of_stock":
            bucket["unfulfilled"] += 1

        hour = event.get("hour")
        if hour is not None:
            bucket["hours"][int(hour)] += 1

        when = _parse(event.get("timestamp", ""))
        if when:
            if bucket["first_seen"] is None or when < bucket["first_seen"]:
                bucket["first_seen"] = when
            if bucket["last_seen"] is None or when > bucket["last_seen"]:
                bucket["last_seen"] = when

    rows = []
    for bucket in buckets.values():
        requests = bucket["requests"]
        unfulfilled = bucket["unfulfilled"]
        share = (unfulfilled / requests) if requests else 0.0

        if unfulfilled == 0:
            availability = "available"
        elif share >= UNFULFILLED_SHARE_ALERT:
            availability = "out_of_stock"
        else:
            availability = "intermittent"

        peak_hour = (
            max(bucket["hours"].items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if bucket["hours"]
            else None
        )

        rows.append(
            {
                "product": bucket["product"],
                "family": bucket["family"],
                "catalog_items": sorted(x for x in bucket["catalog_items"] if x),
                "requests": requests,
                "unfulfilled_requests": unfulfilled,
                "fulfilled_requests": requests - unfulfilled,
                "unfulfilled_share": round(share * 100, 1),
                "availability": availability,
                "potential_lost_sales": unfulfilled > 0,
                "high_demand": requests >= HIGH_DEMAND_MIN_REQUESTS,
                "peak_hour": peak_hour,
                "hourly_requests": [
                    {"hour": h, "requests": c} for h, c in sorted(bucket["hours"].items())
                ],
                "first_seen": bucket["first_seen"].isoformat(timespec="seconds")
                if bucket["first_seen"]
                else None,
                "last_seen": bucket["last_seen"].isoformat(timespec="seconds")
                if bucket["last_seen"]
                else None,
                "average_confidence": round(bucket["confidence_sum"] / requests, 2)
                if requests
                else 0.0,
            }
        )

    rows.sort(key=lambda r: (-r["unfulfilled_requests"], -r["requests"], r["product"]))
    return rows


def estimate_lost_revenue(unfulfilled: int, basket_value: Optional[float]) -> Optional[float]:
    """
    A deliberately rough figure, and labelled as such wherever it surfaces.

    catalog.json carries names but no prices, so a missed sale is valued at
    the merchant's own average basket rather than at a product price. That
    over-values a Rs 14 packet of noodles and under-values a monthly grocery
    run; it is offered as an order of magnitude, never as an amount owed.
    """
    if not basket_value or unfulfilled <= 0:
        return None
    return round(unfulfilled * float(basket_value), 2)


def hourly_demand(events: Iterable[dict]) -> list[dict]:
    """Requests and unfulfilled requests per hour, for the shop-floor chart."""
    requests: dict[int, int] = defaultdict(int)
    unfulfilled: dict[int, int] = defaultdict(int)

    for event in events:
        hour = event.get("hour")
        if hour is None or event.get("intent") == "suspicious_activity":
            continue
        requests[int(hour)] += 1
        if event.get("availability") == "out_of_stock":
            unfulfilled[int(hour)] += 1

    if not requests:
        return []

    lo, hi = min(requests), max(requests)
    return [
        {
            "hour": hour,
            "label": _hour_label(hour),
            "requests": requests.get(hour, 0),
            "unfulfilled": unfulfilled.get(hour, 0),
        }
        for hour in range(lo, hi + 1)
    ]


def _hour_label(hour: int) -> str:
    hour %= 24
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display} {suffix}"


def summarise(
    events: list[dict],
    *,
    basket_value: Optional[float] = None,
    min_requests: int = HIGH_DEMAND_MIN_REQUESTS,
) -> dict:
    """The payload behind GET /api/shop-intelligence/summary."""
    demand = product_demand(events)

    high = [d for d in demand if d["requests"] >= min_requests]
    missing = [d for d in demand if d["unfulfilled_requests"] > 0]

    fraud = [
        {
            "event_id": e.get("event_id"),
            "timestamp": e.get("timestamp"),
            "transcript": e.get("transcript"),
            **(e.get("fraud_signal") or {}),
        }
        for e in events
        if e.get("fraud_signal")
    ]

    total_unfulfilled = sum(d["unfulfilled_requests"] for d in demand)
    conversations = len({e.get("transcript") for e in events if e.get("transcript")})

    return {
        "total_requests": sum(d["requests"] for d in demand),
        "unique_products": len(demand),
        "conversations_captured": conversations,
        "unfulfilled_requests": total_unfulfilled,
        "high_demand_products": [
            {
                "product": d["product"],
                "requests": d["requests"],
                "availability": d["availability"],
                "peak_hour": d["peak_hour"],
            }
            for d in sorted(high, key=lambda d: -d["requests"])
        ],
        "out_of_stock_requests": [
            {
                "product": d["product"],
                "requests": d["requests"],
                "unfulfilled_requests": d["unfulfilled_requests"],
                "potential_lost_sales": True,
                "estimated_lost_revenue": estimate_lost_revenue(
                    d["unfulfilled_requests"], basket_value
                ),
            }
            for d in missing
        ],
        "products": demand,
        "hourly_demand": hourly_demand(events),
        "fraud_signals": fraud,
        "estimated_lost_revenue": estimate_lost_revenue(total_unfulfilled, basket_value),
        "lost_revenue_basis": (
            "Unfulfilled requests valued at the merchant's average basket. "
            "The catalogue carries no prices, so this is an order of magnitude, "
            "not an amount owed."
        ),
        "thresholds": {
            "high_demand_min_requests": min_requests,
            "unfulfilled_share_alert_percent": UNFULFILLED_SHARE_ALERT * 100,
        },
    }
