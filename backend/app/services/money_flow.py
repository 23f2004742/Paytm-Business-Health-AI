"""
Money in, money stuck, money out.

The three columns a munim keeps, and the reason this product is not a payments
dashboard. Each column comes from a different place, and only one of them is
in the transaction data at all:

    money in     payments received          transactions.csv
    money stuck  udhaar not yet collected   Smart Khata (spoken)
    money out    what the shop spent        expense book (spoken)

A payments app can only ever draw the first column, which is why it can tell a
merchant their sales are down but never that their sales are fine and their
cash is gone. Two of these three columns exist only because somebody said them
out loud to the box on the counter.

Nothing here computes a health score. This module adds up money that was
already recorded elsewhere and says where it came from, so every number on the
dashboard can be traced back to a transaction row, a khata entry, or a
sentence the merchant actually spoke.
"""

from __future__ import annotations

from typing import Optional

from . import ai_box, expenses
from .transaction_analytics import AnalyticsContext, today_snapshot

# Settlement-style khata events, i.e. money that actually came back in.
REPAYMENT_EVENTS = {"KHATA_REPAYMENT", "KHATA_SETTLEMENT"}


def _round(value: float) -> float:
    return round(float(value or 0.0), 2)


def _khata_collected(activity: list[dict]) -> tuple[float, int]:
    """Udhaar recovered, read from what the box actually acted on."""
    total = 0.0
    count = 0
    for item in activity:
        if item.get("event_type") in REPAYMENT_EVENTS and item.get("action_taken"):
            amount = (item.get("changes") or {}).get("amount")
            if isinstance(amount, (int, float)):
                total += float(amount)
                count += 1
    return _round(total), count


def money_flow(
    ctx: AnalyticsContext,
    demand: Optional[dict] = None,
    merchant_id: Optional[str] = None,
) -> dict:
    """
    One payload for the three money columns, plus the one-line verdict.

    `demand` is the shop-floor summary. It contributes no rupees to any
    column: unmet demand is money that never existed, so it is reported
    beside the columns as a separate risk rather than added to them.
    """
    today = today_snapshot(ctx)
    khata = ai_box.snapshot()
    spend = expenses.totals(merchant_id)

    collected, collected_count = _khata_collected(khata.get("activity", []))

    outstanding = _round(khata.get("total_outstanding", 0.0))
    debtors = sorted(
        (c for c in khata.get("customers", []) if float(c.get("balance", 0) or 0) > 0),
        key=lambda c: float(c.get("balance", 0) or 0),
        reverse=True,
    )

    # Money that never arrived because the shelf was empty. Deliberately kept
    # out of the three columns: it is a forecast, not a rupee anyone holds.
    lost = None
    lost_requests = 0
    if demand:
        lost = demand.get("estimated_lost_revenue")
        lost_requests = int(demand.get("unfulfilled_requests", 0) or 0)

    in_today = _round(today["revenue"])
    out_today = _round(spend["today"])

    return {
        "money_in": {
            "today": in_today,
            "today_change": today["revenue_change"],
            "week": _round(ctx.current.revenue),
            "week_change": ctx.revenue_growth_wow,
            "transactions_today": today["transactions"],
            "customers_today": today["unique_customers"],
            "khata_collected": collected,
            "khata_collected_count": collected_count,
            "source": "Paytm transactions",
        },
        "money_stuck": {
            "outstanding": outstanding,
            "customers_with_dues": int(khata.get("customers_with_dues", 0) or 0),
            "top_debtors": [
                {"name": c.get("name"), "balance": _round(c.get("balance", 0))}
                for c in debtors[:5]
            ],
            "largest": _round(debtors[0].get("balance", 0)) if debtors else 0.0,
            "source": "Smart Khata",
        },
        "money_out": {
            "today": out_today,
            "total": _round(spend["total"]),
            "count": spend["count"],
            "count_today": spend["count_today"],
            "by_category": spend["by_category"],
            "recent": spend["recent"],
            "source": "Spoken expense book",
        },
        # What the shelf cost you. Not a column: nobody is holding this money.
        "at_risk": {
            "estimated_lost_revenue": lost,
            "unfulfilled_requests": lost_requests,
            "note": (
                "Demand that walked out unserved. An estimate from shop-floor "
                "conversations, not a recorded amount, so it is reported "
                "separately and never added to the money columns."
            ),
        },
        "net_today": _round(in_today - out_today),
        "verdict": _verdict(in_today, out_today, outstanding, spend["by_category"]),
        "as_of": today["date"],
    }


def _verdict(
    money_in: float, money_out: float, outstanding: float, by_category: list[dict]
) -> str:
    """
    One plain sentence a merchant can act on, phrased deterministically.

    Written here rather than by a model on purpose: this line states money,
    and money is never left to phrasing.
    """
    net = money_in - money_out

    if money_in == 0 and money_out == 0 and outstanding == 0:
        return (
            "Nothing recorded yet today. Tell the box about a sale, an udhaar "
            "or a kharcha and it starts keeping your books."
        )

    parts: list[str] = []
    if net >= 0:
        parts.append(f"You are up ₹{net:,.0f} today")
    else:
        parts.append(f"You are down ₹{abs(net):,.0f} today")

    if money_out:
        top = by_category[0] if by_category else None
        if top:
            parts.append(
                f"most of your spending is {top['label'].lower()} "
                f"(₹{top['amount']:,.0f})"
            )

    if outstanding:
        parts.append(f"and ₹{outstanding:,.0f} is still stuck in udhaar")

    return ", ".join(parts) + "."
