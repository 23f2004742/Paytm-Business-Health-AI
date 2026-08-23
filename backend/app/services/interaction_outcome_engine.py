"""
Interaction outcome engine.

Takes a roled conversation and answers the only question that matters
commercially: **did the customer get what they came for?**

    buyer intent  +  seller response  ->  outcome

    FULFILLED             they asked, the shop had it, it was served
    UNFULFILLED           they asked, the shop did not have it   <- lost sale
    ALTERNATIVE_OFFERED   not available, but something else was offered
    ABANDONED             the customer withdrew before any refusal
    UNCERTAIN             the exchange does not say

The distinction that pays for this whole module is UNFULFILLED. It is the one
business event that **leaves no trace in payment data at all**, because a sale
that does not happen produces no transaction. Payment analytics can see
revenue fall; only this can see why the customer left empty-handed.

`UNCERTAIN` is a real answer, not a failure. Half-heard exchanges are normal
on a shop floor, and inventing an outcome for one would quietly corrupt every
number built on top.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from .conversation import (
    BuyerIntent,
    Role,
    SellerResponse,
    Utterance,
    analyse_conversation,
    conversation_payload,
)
from .shop_intelligence import detect_fraud_signal, family_display, family_of


class Outcome:
    FULFILLED = "fulfilled"
    UNFULFILLED = "unfulfilled"
    ALTERNATIVE_OFFERED = "alternative_offered"
    ABANDONED = "abandoned"
    UNCERTAIN = "uncertain"


# Buyer intents that mean the customer wanted to buy something. Only these can
# produce a lost sale; a price inquiry that goes nowhere is not a loss.
_PURCHASE_INTENTS = {
    BuyerIntent.PRODUCT_REQUEST,
    BuyerIntent.PRODUCT_INQUIRY,
    BuyerIntent.QUANTITY_REQUEST,
    BuyerIntent.PURCHASE_INTENT,
}

# Seller responses that mean the customer walked away without the product.
_REFUSAL_RESPONSES = {
    SellerResponse.UNAVAILABLE,
    SellerResponse.UNABLE_TO_FULFILL,
}

# Seller responses that mean the shop served them.
_FULFILLING_RESPONSES = {
    SellerResponse.PURCHASE_CONFIRMED,
    SellerResponse.PAYMENT_ACKNOWLEDGED,
    SellerResponse.AVAILABLE,
    SellerResponse.PRICE_PROVIDED,
    SellerResponse.QUANTITY_CONFIRMED,
}


@dataclass
class Interaction:
    """One buyer/seller exchange, fully interpreted."""

    interaction_id: str
    merchant_id: str
    timestamp: str
    hour: int

    conversation: list[dict]

    product: Optional[str]                 # display name, e.g. "Maggi"
    product_family: Optional[str]
    catalog_item: Optional[str]            # the matched SKU
    quantity: Optional[int]
    price_mentioned: Optional[float]

    buyer_intent: str
    seller_response: str
    interaction_outcome: str

    potential_lost_sale: bool
    expects_transaction: bool

    confidence: float
    role_confidence: float
    transcript: str
    source: str
    extractor: str
    reasoning: list[str] = field(default_factory=list)
    fraud_signal: Optional[dict] = None
    transaction_correlation: Optional[dict] = None

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------- the decision

def decide_outcome(
    buyer_intent: str, seller_response: str
) -> tuple[str, bool, bool, list[str]]:
    """
    Returns (outcome, potential_lost_sale, expects_transaction, reasoning).

    Deterministic and fully enumerated: every branch is a rule someone can
    read and disagree with, which is the point.
    """
    reasoning: list[str] = []

    # The customer withdrew. Not the shop's failure and not a lost sale in the
    # inventory sense, so it must not be counted as one.
    if buyer_intent == BuyerIntent.CANCELLATION:
        reasoning.append("Customer withdrew the request before any refusal.")
        return Outcome.ABANDONED, False, False, reasoning

    if buyer_intent == BuyerIntent.COMPLAINT:
        reasoning.append("Exchange was a complaint rather than a purchase attempt.")
        return Outcome.UNCERTAIN, False, False, reasoning

    wanted_to_buy = buyer_intent in _PURCHASE_INTENTS

    # Something was offered in place of what was asked for. The customer may
    # still have bought, so this is deliberately not a clean lost sale.
    if seller_response == SellerResponse.ALTERNATIVE_SUGGESTED:
        reasoning.append(
            "Requested product was unavailable, but the shopkeeper offered a "
            "substitute, so the customer may still have bought something."
        )
        return Outcome.ALTERNATIVE_OFFERED, wanted_to_buy, False, reasoning

    if seller_response in _REFUSAL_RESPONSES:
        if wanted_to_buy:
            reasoning.append(
                "Customer asked for a product and the shopkeeper said it was "
                "unavailable. Nothing about this appears in payment data."
            )
            return Outcome.UNFULFILLED, True, False, reasoning
        reasoning.append("Shopkeeper reported an item unavailable, with no clear request.")
        return Outcome.UNCERTAIN, False, False, reasoning

    # The customer confirmed payment. Strongest available evidence of a sale.
    if buyer_intent == BuyerIntent.PAYMENT_CONFIRMATION or (
        seller_response == SellerResponse.PAYMENT_ACKNOWLEDGED
    ):
        reasoning.append("Payment was mentioned in the exchange, so a sale likely completed.")
        return Outcome.FULFILLED, False, True, reasoning

    if wanted_to_buy and seller_response in _FULFILLING_RESPONSES:
        reasoning.append(
            "Customer asked for a product and the shopkeeper served it, so a "
            "matching transaction is expected."
        )
        return Outcome.FULFILLED, False, True, reasoning

    # A price was asked and answered but nothing else happened. Genuinely
    # ambiguous: browsing looks exactly like this.
    if buyer_intent == BuyerIntent.PRICE_INQUIRY:
        reasoning.append("Price was discussed but the exchange does not say whether a sale followed.")
        return Outcome.UNCERTAIN, False, False, reasoning

    if wanted_to_buy and seller_response == SellerResponse.UNKNOWN:
        reasoning.append(
            "A product request was heard but the shopkeeper's reply was not "
            "captured, so the outcome is unknown."
        )
        return Outcome.UNCERTAIN, False, False, reasoning

    reasoning.append("The exchange does not contain a clear request and response.")
    return Outcome.UNCERTAIN, False, False, reasoning


# ------------------------------------------------------------- aggregation

def _pick_product(utterances: list[Utterance]) -> tuple[Optional[str], Optional[int]]:
    """
    The product the exchange is about, and how many.

    The buyer's own words win. A shopkeeper repeating the name back ("Maggi
    khatam ho gaya") confirms it but should not override the customer, and a
    substitute the shopkeeper names is emphatically not what was asked for.
    """
    for utterance in utterances:
        if utterance.speaker == Role.BUYER and utterance.products:
            return utterance.products[0]["product"], utterance.quantity

    for utterance in utterances:
        if utterance.products:
            return utterance.products[0]["product"], utterance.quantity

    return None, None


# Intents that describe how the exchange *ended*. If one of these appears
# anywhere, it outranks an earlier request: a customer who asks for Lays and
# then says "nahi chahiye" has abandoned, not requested.
_TERMINAL_INTENTS = (
    BuyerIntent.CANCELLATION,
    BuyerIntent.PAYMENT_CONFIRMATION,
    BuyerIntent.COMPLAINT,
)

# Same idea on the seller side: a refusal or a completed sale settles the
# exchange regardless of what was said first.
_TERMINAL_RESPONSES = (
    SellerResponse.UNAVAILABLE,
    SellerResponse.UNABLE_TO_FULFILL,
    SellerResponse.ALTERNATIVE_SUGGESTED,
    SellerResponse.PAYMENT_ACKNOWLEDGED,
    SellerResponse.PURCHASE_CONFIRMED,
)


def _dominant(utterances: list[Utterance], role: str, attribute: str, default: str) -> str:
    """
    The intent/response that best characterises this role's side of the
    exchange: a terminal one if present, otherwise the first meaningful one.
    """
    terminal = _TERMINAL_INTENTS if attribute == "intent" else _TERMINAL_RESPONSES
    values = [
        getattr(u, attribute)
        for u in utterances
        if u.speaker == role and getattr(u, attribute)
    ]
    for value in values:
        if value in terminal:
            return value

    for utterance in utterances:
        if utterance.speaker != role:
            continue
        value = getattr(utterance, attribute)
        if value and value != "unknown":
            return value

    # Nobody was classified into that role; fall back to any utterance that
    # carried a reading, which is what `unknown` speakers produce.
    for utterance in utterances:
        value = getattr(utterance, attribute)
        if value and value != "unknown":
            return value
    return default


def build_interaction(
    transcript: str,
    *,
    merchant_id: str,
    timestamp: Optional[datetime] = None,
    source: str = "audio",
    extractor: str = "rules",
    utterances: Optional[list[Utterance]] = None,
) -> Interaction:
    """Transcript in, one fully interpreted interaction out."""
    when = timestamp or datetime.now()
    turns = utterances if utterances is not None else analyse_conversation(transcript)

    buyer_intent = _dominant(turns, Role.BUYER, "intent", BuyerIntent.UNKNOWN)
    seller_response = _dominant(turns, Role.SELLER, "response", SellerResponse.UNKNOWN)

    outcome, lost_sale, expects_txn, reasoning = decide_outcome(buyer_intent, seller_response)

    product, quantity = _pick_product(turns)
    family = family_of(product) if product else None
    display = family_display(family) if family else None

    price = next((u.price for u in turns if u.price is not None), None)

    roled = [u for u in turns if u.speaker != Role.UNKNOWN]
    role_confidence = (
        round(sum(u.confidence for u in roled) / len(roled), 2) if roled else 0.0
    )

    # Overall confidence is held down by whichever part of the chain is
    # weakest. Knowing the words but not who said them is not a confident
    # reading of an exchange.
    match_confidence = 0.0
    for utterance in turns:
        if utterance.products:
            match_confidence = max(
                match_confidence, utterance.products[0]["score"] / 100.0
            )

    outcome_confidence = {
        Outcome.UNFULFILLED: 0.92,
        Outcome.FULFILLED: 0.88,
        Outcome.ALTERNATIVE_OFFERED: 0.80,
        Outcome.ABANDONED: 0.75,
        Outcome.UNCERTAIN: 0.40,
    }[outcome]

    confidence = round(
        min(0.97, 0.45 * outcome_confidence + 0.30 * role_confidence + 0.25 * match_confidence),
        2,
    )

    if not roled:
        reasoning.append("Speaker roles could not be determined from the language used.")

    return Interaction(
        interaction_id=f"INT_{uuid.uuid4().hex[:10]}",
        merchant_id=merchant_id,
        timestamp=when.isoformat(timespec="seconds"),
        hour=when.hour,
        conversation=conversation_payload(turns),
        product=display,
        product_family=family,
        catalog_item=product,
        quantity=quantity,
        price_mentioned=price,
        buyer_intent=buyer_intent,
        seller_response=seller_response,
        interaction_outcome=outcome,
        potential_lost_sale=lost_sale and bool(product),
        expects_transaction=expects_txn,
        confidence=confidence,
        role_confidence=role_confidence,
        transcript=transcript,
        source=source,
        extractor=extractor,
        reasoning=reasoning,
        fraud_signal=detect_fraud_signal(transcript),
    )


# ----------------------------------------------------------- summarisation

def summarise_outcomes(interactions: list[dict]) -> dict:
    """Counts by outcome, plus the fulfilment rate the health score reads."""
    counts = {
        Outcome.FULFILLED: 0,
        Outcome.UNFULFILLED: 0,
        Outcome.ALTERNATIVE_OFFERED: 0,
        Outcome.ABANDONED: 0,
        Outcome.UNCERTAIN: 0,
    }
    for interaction in interactions:
        outcome = interaction.get("interaction_outcome", Outcome.UNCERTAIN)
        if outcome in counts:
            counts[outcome] += 1

    # Only decided exchanges count toward the rate. Including UNCERTAIN would
    # let poor audio look like poor service.
    decided = (
        counts[Outcome.FULFILLED]
        + counts[Outcome.UNFULFILLED]
        + counts[Outcome.ALTERNATIVE_OFFERED]
    )
    # A substitute is a partial success, so it counts as half.
    served = counts[Outcome.FULFILLED] + 0.5 * counts[Outcome.ALTERNATIVE_OFFERED]

    return {
        "counts": counts,
        "decided_interactions": decided,
        "total_interactions": len(interactions),
        "fulfillment_rate": round(served / decided * 100, 1) if decided else None,
        "lost_sales": sum(1 for i in interactions if i.get("potential_lost_sale")),
        "expected_transactions": sum(1 for i in interactions if i.get("expects_transaction")),
    }
