"""
Conversation intelligence: who said what, and what they meant.

The existing extractor treats a transcript as one undifferentiated utterance.
It finds products and notices out-of-stock phrases, but it does not know who
is speaking. That limit is real: "nahi chahiye" from a customer is a
cancellation, while "nahi hai" from a shopkeeper is a stockout, and only the
speaker tells them apart.

This module splits a transcript into utterances, assigns each a ROLE, and
reads a buyer intent or a seller response from it.

------------------------------------------------------------------------------
What "speaker identification" means here, precisely
------------------------------------------------------------------------------
This is **role classification from language**, not biometric speaker
identification and not acoustic diarization. Nothing here has heard a voice;
it has read words. Two different customers in one recording are both "buyer".

The signals are linguistic and positional:

  * lexical      "dena", "chahiye", "kitne ka"     -> buyer
                 "khatam ho gaya", "lijiye"        -> seller
  * address      "bhaiya", "bhai" address the shopkeeper -> speaker is buyer
                 "beta", "sir", "madam" address the customer -> speaker is seller
  * question     availability questions come from buyers;
                 clarifying questions ("kitna chahiye?") come from sellers
  * alternation  shop exchanges alternate, so an unmarked utterance between
                 two classified ones inherits the opposite role

When the evidence is thin the role is `unknown` and the confidence says so.
An honest `unknown` is worth more than a confident guess, because everything
downstream is weighted by this confidence.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .shop_intelligence import (
    OUT_OF_STOCK_MARKERS,
    _tokens,
    match_to_catalog,
    normalise,
)

# Below this, the role is reported as `unknown` rather than guessed.
ROLE_CONFIDENCE_FLOOR = 0.55
MAX_ROLE_CONFIDENCE = 0.95


# --------------------------------------------------------------- taxonomies

class BuyerIntent:
    PRODUCT_REQUEST = "product_request"        # "do Maggi dena"
    PRODUCT_INQUIRY = "product_inquiry"        # "Maggi hai?"
    PRICE_INQUIRY = "price_inquiry"            # "kitne ka hai?"
    QUANTITY_REQUEST = "quantity_request"      # "do packet"
    PURCHASE_INTENT = "purchase_intent"        # "theek hai, de do"
    PAYMENT_CONFIRMATION = "payment_confirmation"  # "UPI kar diya"
    COMPLAINT = "complaint"                    # "ye kharab hai"
    CANCELLATION = "cancellation"              # "nahi chahiye"
    UNKNOWN = "unknown"


class SellerResponse:
    AVAILABLE = "available"                    # "haan hai"
    UNAVAILABLE = "unavailable"                # "khatam ho gaya"
    PRICE_PROVIDED = "price_provided"          # "20 ka hai"
    QUANTITY_CONFIRMED = "quantity_confirmed"  # "kitna chahiye?"
    PURCHASE_CONFIRMED = "purchase_confirmed"  # "deta hoon"
    PAYMENT_ACKNOWLEDGED = "payment_acknowledged"  # "aa gaya"
    ALTERNATIVE_SUGGESTED = "alternative_suggested"  # "noodles le lo"
    UNABLE_TO_FULFILL = "unable_to_fulfill"    # "kal aana"
    UNKNOWN = "unknown"


class Role:
    BUYER = "buyer"
    SELLER = "seller"
    UNKNOWN = "unknown"


# ------------------------------------------------------------ lexical cues
#
# Each entry is (phrase, weight). Weights are evidence strength, not
# probability: they are summed per utterance and squashed at the end.
# Longer, less ambiguous phrases carry more weight.

BUYER_CUES: list[tuple[str, float]] = [
    # asking for something
    ("dena", 0.7), ("de do", 0.8), ("dedo", 0.8), ("de dijiye", 0.8),
    ("chahiye", 0.8), ("chaiye", 0.7), ("chahie", 0.7),
    ("give me", 0.8), ("i want", 0.8), ("i need", 0.8),
    # asking whether something exists
    ("hai kya", 0.8), ("hai?", 0.5), ("milega", 0.7), ("milegi", 0.7),
    ("do you have", 0.9), ("kya hai", 0.4),
    # price questions
    ("kitne ka", 0.9), ("kitna hua", 0.9), ("kitne ki", 0.9),
    ("how much", 0.9), ("price kya", 0.9),
    # paying
    ("kar diya", 0.8), ("scan kar", 0.8), ("paytm kar", 0.8),
    ("upi kar", 0.9), ("payment kar diya", 0.9), ("bhej diya", 0.8),
    # addressing the shopkeeper: the speaker must therefore be the buyer
    ("bhaiya", 0.6), ("bhai", 0.35), ("uncle", 0.5), ("chacha", 0.5),
    ("boss", 0.3),
    # declining
    ("nahi chahiye", 0.9), ("rehne do", 0.8), ("nahi lena", 0.9),
]

SELLER_CUES: list[tuple[str, float]] = [
    # stock answers
    ("khatam ho gaya", 0.95), ("khatam ho gayi", 0.95), ("khatam hogaya", 0.95),
    ("khatam hogaye", 0.95), ("katam ho gaya", 0.9), ("stock khatam", 0.95),
    ("stock nahi", 0.9), ("out of stock", 0.95), ("nahi milega", 0.85),
    ("khatam", 0.6), ("nahi hai", 0.55), ("nhi hai", 0.55),
    ("abhi nahi", 0.6), ("kal aana", 0.9), ("kal milega", 0.9),
    # affirmative service
    ("haan hai", 0.9), ("haan ji", 0.7), ("lijiye", 0.85), ("le lijiye", 0.9),
    ("deta hoon", 0.9), ("de raha hoon", 0.9), ("deti hoon", 0.9),
    ("ho jayega", 0.8), ("mil jayega", 0.8),
    # clarifying, which a shopkeeper does
    ("kitna chahiye", 0.9), ("kitne chahiye", 0.9), ("kaunsa", 0.7),
    ("konsa", 0.7), ("aur kuch", 0.85), ("kuch aur", 0.85),
    # money
    ("ka hai", 0.55), ("rupaye", 0.6), ("rupees", 0.5), ("total", 0.6),
    # payment acknowledgement
    ("aa gaya", 0.8), ("mil gaya", 0.75), ("received", 0.7),
    ("ho gaya payment", 0.9),
    # offering something else
    ("le lo", 0.7), ("try kar", 0.6),
    # addressing the customer: the speaker must therefore be the seller
    ("beta", 0.65), ("sir", 0.45), ("madam", 0.6), ("ji", 0.15),
]

# Buyer intent detection, checked in order. First match wins, so the more
# specific patterns come first.
BUYER_INTENT_RULES: list[tuple[str, list[str]]] = [
    (BuyerIntent.CANCELLATION,
     ["nahi chahiye", "rehne do", "nahi lena", "cancel", "mat do"]),
    (BuyerIntent.COMPLAINT,
     ["kharab", "expire", "purana", "galat", "wrong", "complaint", "kharaab",
      "refund", "paisa nahi"]),
    (BuyerIntent.PAYMENT_CONFIRMATION,
     ["kar diya", "scan kar", "upi kar", "paytm kar", "bhej diya", "paid",
      "payment ho gaya", "transfer kar"]),
    (BuyerIntent.PRICE_INQUIRY,
     ["kitne ka", "kitna hua", "kitne ki", "how much", "price kya", "daam",
      "kitne paise"]),
    (BuyerIntent.PRODUCT_INQUIRY,
     ["hai kya", "milega", "milegi", "do you have", "hai?", "available hai",
      "stock hai"]),
    (BuyerIntent.PRODUCT_REQUEST,
     ["dena", "de do", "dedo", "de dijiye", "chahiye", "chaiye", "give me",
      "i want", "i need", "packet do"]),
    (BuyerIntent.PURCHASE_INTENT,
     ["theek hai", "thik hai", "ok de", "haan de", "chalega", "le lunga",
      "de dijiyega"]),
]

SELLER_RESPONSE_RULES: list[tuple[str, list[str]]] = [
    (SellerResponse.UNAVAILABLE, OUT_OF_STOCK_MARKERS),
    (SellerResponse.UNABLE_TO_FULFILL,
     ["kal aana", "kal milega", "baad me", "abhi nahi de sakta", "order karna padega"]),
    (SellerResponse.PAYMENT_ACKNOWLEDGED,
     ["aa gaya", "mil gaya", "received", "ho gaya payment", "payment aa gaya"]),
    (SellerResponse.PURCHASE_CONFIRMED,
     ["deta hoon", "de raha hoon", "deti hoon", "ho jayega", "lijiye",
      "le lijiye", "packing kar", "de dunga"]),
    (SellerResponse.QUANTITY_CONFIRMED,
     ["kitna chahiye", "kitne chahiye", "kaunsa", "konsa", "kitne packet"]),
    (SellerResponse.ALTERNATIVE_SUGGESTED,
     ["le lo", "iske jagah", "instead", "dusra hai", "ye try kar", "alternative"]),
    (SellerResponse.AVAILABLE,
     ["haan hai", "haan ji", "hai ji", "available hai", "stock me hai", "haan"]),
]

# Words that mean a price is being stated rather than asked for.
_PRICE_PATTERN = re.compile(
    r"(?:rs\.?|₹|rupees?|rupaye|rupay)\s*(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s*(?:rs\.?|₹|rupees?|rupaye|rupay)"
    r"|(\d+(?:\.\d+)?)\s*(?:ka hai|ke hai|ka)",
    re.I,
)

# Hindi and English number words a shop actually uses for quantity.
_NUMBER_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5,
    "panch": 5, "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
    "das": 10, "dus": 10, "adha": 1, "aadha": 1,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1,
    "dozen": 12, "couple": 2,
}

# Units that follow a quantity, so "do packet" reads as 2 and "do rupaye"
# does not read as a quantity at all.
_QUANTITY_UNITS = {
    "packet", "packets", "pack", "packs", "piece", "pieces", "pcs",
    "bottle", "bottles", "kilo", "kg", "gram", "litre", "liter", "dozen",
    "box", "pouch", "strip", "plate", "cup",
}

_UTTERANCE_SPLIT = re.compile(r"(?<=[?.!])\s+|\s*\|\s*|\n+")


# ------------------------------------------------------------- data model

@dataclass
class Utterance:
    """One turn in a shop exchange."""

    index: int
    text: str
    normalised: str
    speaker: str                      # buyer | seller | unknown
    confidence: float
    role_evidence: list[str] = field(default_factory=list)
    intent: Optional[str] = None      # buyer utterances
    response: Optional[str] = None    # seller utterances
    products: list[dict] = field(default_factory=list)
    quantity: Optional[int] = None
    price: Optional[float] = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------- splitting

def split_utterances(transcript: str) -> list[str]:
    """
    Break a transcript into turns.

    Sentence punctuation is the main cue. Where a recording has none (Whisper
    often returns an unpunctuated run), a turn boundary is inferred before a
    strong opening cue such as "nahi" or "haan", which is how a reply starts.
    """
    raw = [p.strip() for p in _UTTERANCE_SPLIT.split(transcript) if p and p.strip()]

    out: list[str] = []
    for part in raw:
        # Only split further when the fragment is long enough that a run-on is
        # more likely than a genuine single sentence.
        if len(part.split()) > 6:
            out.extend(_split_on_reply_cue(part))
        else:
            out.append(part)
    return out or ([transcript.strip()] if transcript.strip() else [])


_REPLY_CUE = re.compile(
    r"\s+(?=(?:nahi|nhi|haan|han|sorry|arre|abhi|stock|khatam)\b)", re.I
)


def _split_on_reply_cue(text: str) -> list[str]:
    parts = [p.strip() for p in _REPLY_CUE.split(text) if p.strip()]
    return parts if len(parts) > 1 else [text]


# ------------------------------------------------------- role classification

def _score_role(normalised_text: str) -> tuple[float, float, list[str]]:
    """Summed buyer and seller evidence, plus the cues that fired."""
    buyer = seller = 0.0
    evidence: list[str] = []

    for phrase, weight in BUYER_CUES:
        if phrase in normalised_text:
            buyer += weight
            evidence.append(f"buyer:'{phrase}'")

    for phrase, weight in SELLER_CUES:
        if phrase in normalised_text:
            seller += weight
            evidence.append(f"seller:'{phrase}'")

    return buyer, seller, evidence


def classify_role(text: str, normalised_text: str) -> tuple[str, float, list[str]]:
    """
    Role for a single utterance, judged in isolation.

    Returns (role, confidence, evidence). Conversation-level correction
    happens afterwards in `_apply_alternation`, which can see neighbours.
    """
    buyer, seller, evidence = _score_role(normalised_text)

    # A price being *stated* is a seller behaviour; a price being *asked for*
    # is a buyer behaviour. The question cue already scored above, so only
    # add seller weight when no price question was detected.
    if _PRICE_PATTERN.search(normalised_text) and not any(
        q in normalised_text for q in ("kitne ka", "kitna hua", "how much", "kitne ki")
    ):
        seller += 0.5
        evidence.append("seller:price-stated")

    total = buyer + seller
    if total == 0:
        return Role.UNKNOWN, 0.0, evidence

    if buyer >= seller:
        role, share = Role.BUYER, buyer / total
    else:
        role, share = Role.SELLER, seller / total

    # Confidence blends how lopsided the evidence is with how much of it there
    # is. One weak cue should not produce a confident answer just because
    # nothing contradicted it.
    strength = min(1.0, max(buyer, seller) / 1.2)
    confidence = min(MAX_ROLE_CONFIDENCE, 0.5 * share + 0.5 * strength)

    if confidence < ROLE_CONFIDENCE_FLOOR:
        return Role.UNKNOWN, round(confidence, 2), evidence

    return role, round(confidence, 2), evidence


def _apply_alternation(utterances: list[Utterance]) -> None:
    """
    Fill in unknown roles from position.

    Shop exchanges alternate. An unlabelled turn sitting between two labelled
    ones takes the opposite role to its neighbour, at reduced confidence
    because position is weaker evidence than words. The first turn in an
    exchange defaults to buyer: a customer opens, which is what a shop is.
    """
    for i, utterance in enumerate(utterances):
        if utterance.speaker != Role.UNKNOWN:
            continue

        previous = utterances[i - 1] if i > 0 else None
        following = utterances[i + 1] if i + 1 < len(utterances) else None

        inferred: Optional[str] = None
        if previous and previous.speaker != Role.UNKNOWN:
            inferred = Role.SELLER if previous.speaker == Role.BUYER else Role.BUYER
        elif following and following.speaker != Role.UNKNOWN:
            inferred = Role.SELLER if following.speaker == Role.BUYER else Role.BUYER
        elif i == 0 and len(utterances) > 1:
            inferred = Role.BUYER

        if inferred:
            utterance.speaker = inferred
            utterance.confidence = 0.60
            utterance.role_evidence.append("inferred:alternation")


# ------------------------------------------------------ intent / response

def detect_buyer_intent(normalised_text: str, has_product: bool, quantity: Optional[int]) -> str:
    for intent, markers in BUYER_INTENT_RULES:
        if any(marker in normalised_text for marker in markers):
            # "do packet dena" is a quantity request, not a bare product request.
            if intent == BuyerIntent.PRODUCT_REQUEST and quantity and quantity > 1:
                return BuyerIntent.QUANTITY_REQUEST
            return intent

    if has_product:
        return BuyerIntent.PRODUCT_INQUIRY
    return BuyerIntent.UNKNOWN


_ALTERNATIVE_MARKERS = ["le lo", "iske jagah", "instead", "dusra hai", "ye try kar",
                        "alternative", "iske badle", "ye le"]


def detect_seller_response(normalised_text: str, has_product: bool) -> str:
    unavailable = any(m in normalised_text for m in OUT_OF_STOCK_MARKERS)
    alternative = any(m in normalised_text for m in _ALTERNATIVE_MARKERS)

    # "Maggi nahi hai, noodles le lo" is both a stockout and an offer. The
    # offer is the more useful reading: the customer may still buy, so this
    # is not a clean lost sale.
    if unavailable and alternative:
        return SellerResponse.ALTERNATIVE_SUGGESTED

    for response, markers in SELLER_RESPONSE_RULES:
        if any(marker in normalised_text for marker in markers):
            return response

    if _PRICE_PATTERN.search(normalised_text):
        return SellerResponse.PRICE_PROVIDED
    if has_product:
        return SellerResponse.AVAILABLE
    return SellerResponse.UNKNOWN


# ------------------------------------------------------ quantity and price

def extract_quantity(normalised_text: str) -> Optional[int]:
    """
    Quantity, only when a unit or a product follows the number.

    "do packet" is two. "do rupaye" is a price. "do Maggi dena" is two. A bare
    "do" on its own is the verb, not the number, so it is ignored.
    """
    tokens = _tokens(normalised_text)

    for i, token in enumerate(tokens):
        value: Optional[int] = None
        if token.isdigit():
            value = int(token)
        elif token in _NUMBER_WORDS:
            value = _NUMBER_WORDS[token]

        if value is None or not (1 <= value <= 50):
            continue

        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if not following:
            continue
        # A currency word after the number means this was money.
        if following in {"rupaye", "rupees", "rs", "rupay", "ka", "ke"}:
            continue
        if following in _QUANTITY_UNITS:
            return value
        # A product name after the number also makes it a quantity.
        if match_to_catalog(following)[0]:
            return value

    return None


def extract_price(normalised_text: str) -> Optional[float]:
    match = _PRICE_PATTERN.search(normalised_text)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return float(group)
            except ValueError:
                continue
    return None


def _products_in(text: str) -> list[dict]:
    """Catalogue-matched products in one utterance, via the existing matcher."""
    from .shop_intelligence import extract_phrases_rulebased

    return [
        {"product": hit["product"], "query": hit["query"], "score": hit["score"]}
        for hit in extract_phrases_rulebased(text)
    ]


# ------------------------------------------------------------------ public

def analyse_conversation(transcript: str) -> list[Utterance]:
    """
    Transcript in, roled and interpreted utterances out.

    Deterministic and offline: no model is involved anywhere in this path.
    """
    utterances: list[Utterance] = []

    for index, raw in enumerate(split_utterances(transcript)):
        lowered = normalise(raw)
        role, confidence, evidence = classify_role(raw, lowered)

        utterances.append(
            Utterance(
                index=index,
                text=raw.strip(),
                normalised=lowered,
                speaker=role,
                confidence=confidence,
                role_evidence=evidence,
            )
        )

    _apply_alternation(utterances)

    # Interpretation happens after roles settle, because what an utterance
    # means depends on who said it.
    for utterance in utterances:
        utterance.products = _products_in(utterance.text)
        utterance.quantity = extract_quantity(utterance.normalised)
        utterance.price = extract_price(utterance.normalised)
        has_product = bool(utterance.products)

        if utterance.speaker == Role.BUYER:
            utterance.intent = detect_buyer_intent(
                utterance.normalised, has_product, utterance.quantity
            )
        elif utterance.speaker == Role.SELLER:
            utterance.response = detect_seller_response(utterance.normalised, has_product)
        else:
            # Role is genuinely unclear, so record both readings and let the
            # outcome engine weigh them rather than forcing a choice here.
            utterance.intent = detect_buyer_intent(
                utterance.normalised, has_product, utterance.quantity
            )
            utterance.response = detect_seller_response(utterance.normalised, has_product)

    return utterances


def conversation_payload(utterances: list[Utterance]) -> list[dict]:
    """The `conversation` array carried on every interaction."""
    return [
        {
            "speaker": u.speaker,
            "confidence": u.confidence,
            "text": u.text,
            "intent": u.intent,
            "response": u.response,
            "products": [p["product"] for p in u.products],
            "quantity": u.quantity,
            "price": u.price,
        }
        for u in utterances
    ]
