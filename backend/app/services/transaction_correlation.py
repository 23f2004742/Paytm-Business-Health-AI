"""
Transaction correlation.

A conversation that ends in a sale should leave a matching payment. This
module checks whether it did.

------------------------------------------------------------------------------
The honest limit, stated once and enforced everywhere below
------------------------------------------------------------------------------
`transactions.csv` carries transaction_id, timestamp, amount, customer_id and
a coarse category. It does **not** carry a SKU or a line-item breakdown.

So this module physically cannot confirm that a specific Maggi was bought. It
can only say: a conversation ended in an apparent sale at 18:42, and a payment
landed at 18:43. That is a **temporal** match and nothing more.

Consequently `confirmed` is unreachable through the timestamp path and is
reserved for a future provider that actually returns line items. The best this
data supports is `possible_match`, and the returned reason says exactly why.
Overstating this would be the easiest lie in the product and the most
damaging, because a merchant would act on it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


class CorrelationStatus:
    CONFIRMED = "confirmed"                    # needs SKU-level data
    POSSIBLE_MATCH = "possible_match"
    NO_MATCH = "no_match"
    INSUFFICIENT_DATA = "insufficient_data"


def _window_seconds() -> int:
    """How long after an exchange a payment still counts as related."""
    try:
        return int(os.environ.get("TRANSACTION_MATCH_WINDOW_SECONDS", "180"))
    except ValueError:
        return 180


# A payment can also land just before the words finish ("UPI kar diya" is said
# after tapping), so the window reaches slightly backwards too.
LEAD_SECONDS = 60


@dataclass
class CorrelationResult:
    interaction_id: str
    transaction_status: str
    matching_reason: str
    confidence: float
    matched_transaction: Optional[dict] = None
    candidates_in_window: int = 0
    window_seconds: int = 0
    data_limitation: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "interaction_id": self.interaction_id,
            "transaction_status": self.transaction_status,
            "matching_reason": self.matching_reason,
            "confidence": self.confidence,
            "matched_transaction": self.matched_transaction,
            "candidates_in_window": self.candidates_in_window,
            "window_seconds": self.window_seconds,
            "data_limitation": self.data_limitation,
        }


SKU_LIMITATION = (
    "Paytm transaction data available here contains amount and timestamp but "
    "no product line items, so a payment can be matched in time but never to a "
    "specific product."
)


def correlate(
    interaction: dict,
    transactions: pd.DataFrame,
    *,
    expected_price: Optional[float] = None,
) -> CorrelationResult:
    """
    Check one interaction against the ledger.

    Only interactions that actually expect a payment are worth checking. An
    unfulfilled request should have no transaction, and finding one near it
    would mean nothing.
    """
    interaction_id = interaction.get("interaction_id", "")
    window = _window_seconds()

    if not interaction.get("expects_transaction"):
        return CorrelationResult(
            interaction_id=interaction_id,
            transaction_status=CorrelationStatus.NO_MATCH,
            matching_reason=(
                "This exchange did not end in a sale, so no matching payment "
                "is expected."
            ),
            confidence=0.9,
            window_seconds=window,
        )

    try:
        when = datetime.fromisoformat(interaction["timestamp"])
    except (KeyError, ValueError):
        return CorrelationResult(
            interaction_id=interaction_id,
            transaction_status=CorrelationStatus.INSUFFICIENT_DATA,
            matching_reason="The interaction has no usable timestamp.",
            confidence=0.0,
            window_seconds=window,
        )

    if transactions is None or transactions.empty:
        return CorrelationResult(
            interaction_id=interaction_id,
            transaction_status=CorrelationStatus.INSUFFICIENT_DATA,
            matching_reason="No transaction data is loaded for this period.",
            confidence=0.0,
            window_seconds=window,
            data_limitation=SKU_LIMITATION,
        )

    start = when - timedelta(seconds=LEAD_SECONDS)
    end = when + timedelta(seconds=window)

    mask = (transactions["timestamp"] >= start) & (transactions["timestamp"] <= end)
    candidates = transactions.loc[mask]

    if candidates.empty:
        # The dataset is synthetic and generated independently of the
        # conversation script, so an absent payment says more about the demo
        # data than about the shop. Say so rather than implying theft.
        return CorrelationResult(
            interaction_id=interaction_id,
            transaction_status=CorrelationStatus.NO_MATCH,
            matching_reason=(
                f"No payment was recorded within {window}s of this exchange. "
                "That can mean cash, a delayed payment, or simply that this "
                "conversation and the transaction dataset are independent."
            ),
            confidence=0.55,
            candidates_in_window=0,
            window_seconds=window,
            data_limitation=SKU_LIMITATION,
        )

    # Prefer the payment closest in time; if a price was spoken, prefer the
    # closest amount instead, which is weak evidence but better than nothing.
    scored = candidates.assign(
        _gap=(candidates["timestamp"] - when).abs().dt.total_seconds()
    )
    if expected_price:
        scored = scored.assign(_price_gap=(scored["amount"] - expected_price).abs())
        best = scored.sort_values(["_price_gap", "_gap"]).iloc[0]
        price_delta = float(best["_price_gap"])
        price_note = (
            f" The amount is Rs {best['amount']:,.0f} against a spoken price of "
            f"Rs {expected_price:,.0f}."
        )
        price_bonus = 0.12 if price_delta <= max(2.0, expected_price * 0.1) else 0.0
    else:
        best = scored.sort_values("_gap").iloc[0]
        price_note = ""
        price_bonus = 0.0

    gap = float(best["_gap"])
    # Closer in time is better evidence, but it decays: at the edge of the
    # window a payment is barely related to the exchange at all.
    proximity = max(0.0, 1.0 - gap / max(window, 1))
    crowding = 1.0 / max(1, len(candidates))

    confidence = round(
        min(0.85, 0.35 + 0.30 * proximity + 0.20 * crowding + price_bonus), 2
    )

    reason = (
        f"A payment of Rs {best['amount']:,.0f} was recorded "
        f"{gap:.0f}s from this exchange, which ended in an apparent sale."
        f"{price_note}"
    )
    if len(candidates) > 1:
        reason += (
            f" {len(candidates)} payments fall inside the window, so this "
            "pairing is not unique."
        )

    return CorrelationResult(
        interaction_id=interaction_id,
        # Never `confirmed`: see the module docstring. Timestamps cannot
        # establish which product a payment was for.
        transaction_status=CorrelationStatus.POSSIBLE_MATCH,
        matching_reason=reason,
        confidence=confidence,
        matched_transaction={
            "transaction_id": str(best.get("transaction_id", "")),
            "timestamp": best["timestamp"].isoformat(),
            "amount": round(float(best["amount"]), 2),
            "seconds_from_interaction": round(gap),
        },
        candidates_in_window=int(len(candidates)),
        window_seconds=window,
        data_limitation=SKU_LIMITATION,
    )


def correlate_all(interactions: list[dict], transactions: pd.DataFrame) -> dict:
    """Correlate a batch and summarise what the ledger could corroborate."""
    results = []
    for interaction in interactions:
        result = correlate(
            interaction,
            transactions,
            expected_price=interaction.get("price_mentioned"),
        )
        results.append(result.as_dict())

    expected = [i for i in interactions if i.get("expects_transaction")]
    matched = [
        r
        for r in results
        if r["transaction_status"] == CorrelationStatus.POSSIBLE_MATCH
    ]

    return {
        "results": results,
        "summary": {
            "interactions_checked": len(interactions),
            "expected_transactions": len(expected),
            "possible_matches": len(matched),
            "no_match": sum(
                1 for r in results if r["transaction_status"] == CorrelationStatus.NO_MATCH
            ),
            "insufficient_data": sum(
                1
                for r in results
                if r["transaction_status"] == CorrelationStatus.INSUFFICIENT_DATA
            ),
            "match_rate": (
                round(len(matched) / len(expected) * 100, 1) if expected else None
            ),
        },
        "method": {
            "window_seconds": _window_seconds(),
            "lead_seconds": LEAD_SECONDS,
            "limitation": SKU_LIMITATION,
            "note": (
                "Status is never 'confirmed'. Product-level confirmation needs "
                "line-item data that this API does not provide."
            ),
        },
    }
