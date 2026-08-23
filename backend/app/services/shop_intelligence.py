"""
Shop-floor intelligence.

Turns a line of shop conversation into structured events:

    "Bhaiya, Maggi hai?"  /  "Nahi, khatam ho gaya."
        -> product: Maggi 2-Minute Noodles 70g
           intent: product_request
           availability: out_of_stock
           potential_lost_sale: True

The two-stage design is carried over from the original Vyapaar Saathi
extractor and is the part worth keeping:

  Stage 1  language  ->  a short English product description
  Stage 2  Python    ->  that description matched to a real catalogue SKU

Stage 1 has two implementations behind one interface. The rule-based one is
the default and needs nothing installed; the LLM one is optional and only
ever *replaces stage 1*. Stage 2 is deterministic either way, so a product
name in an event is always a real SKU from catalog.json, never model output.

Every event carries a full ISO timestamp. That is what lets the unified
engine join shop-floor demand against a transaction window; the original
stored bare "%H:%M:%S" strings and could not.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
EVENTS_PATH = DATA_DIR / "shop_events.json"
INTERACTIONS_PATH = DATA_DIR / "shop_interactions.json"

MATCH_THRESHOLD = 62          # below this a phrase is not a product
MAX_EVENTS = 5000

_lock = threading.Lock()


# --------------------------------------------------------------- catalogue

@lru_cache(maxsize=1)
def load_catalog() -> list[str]:
    if not CATALOG_PATH.exists():
        return []
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# Size and pack tokens carry no identity, so they are stripped before matching.
_NOISE_TOKEN = re.compile(
    r"^(?:\d+(?:\.\d+)?(?:g|gm|kg|ml|l|mg)|\d+[-\s]?pack|\d+s|\d+)$", re.I
)

_STOPWORDS = {
    "and", "the", "of", "with", "in", "for", "a", "an", "&", "or", "plus",
}

# Colour, format and grade words. They are legitimate catalogue tokens
# ("Green Chilli", "Bottle Gourd") but a shop conversation says them
# constantly about something else, so they may never *start* a product
# mention. They still match happily inside a wider window.
_WEAK_TOKENS = {
    "green", "red", "blue", "orange", "yellow", "white", "black",
    "bottle", "packet", "pack", "piece", "box", "tin", "jar", "pouch",
    "classic", "original", "plain", "regular", "premium", "gold", "light",
    "fresh", "big", "small", "large", "mini", "hot", "sweet", "salted",
    "special", "super", "extra", "double", "family", "value", "combo",
}

# Head nouns a customer uses without a brand. These are not catalogue heads
# (Indian grocery names lead with the brand) so they need naming explicitly.
_GENERIC_PRODUCT_NOUNS = {
    "milk", "biscuit", "biscuits", "chips", "noodles", "toothpaste", "soap",
    "detergent", "shampoo", "tea", "coffee", "butter", "cheese", "curd",
    "namkeen", "water", "oil", "rice", "sugar", "salt", "flour", "atta",
    "chocolate", "juice", "bread", "marie", "sauce", "ketchup", "cream",
    "potato", "tomato", "onion", "wheat",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _identity_tokens(name: str) -> list[str]:
    """Tokens that actually identify a product: no sizes, no filler."""
    return [
        t for t in _tokens(name)
        if not _NOISE_TOKEN.match(t) and t not in _STOPWORDS and len(t) > 1
    ]


@lru_cache(maxsize=1)
def _catalog_index() -> dict:
    """
    Precomputed lookup structures.

      families        first token -> display name ("maggi" -> "Maggi")
      family_of       catalog item -> family key
      trigger_tokens  every token that may start a product mention
      searchable      catalog item -> its identity tokens joined
    """
    catalog = load_catalog()
    families: dict[str, str] = {}
    family_of: dict[str, str] = {}
    trigger: set[str] = set()
    searchable: dict[str, str] = {}
    members: dict[str, list[str]] = {}

    for item in catalog:
        ident = _identity_tokens(item)
        if not ident:
            continue
        key = ident[0]
        family_of[item] = key
        searchable[item] = " ".join(ident)
        trigger.update(ident)
        members.setdefault(key, []).append(item)

    # Display name: the longest opening run of words every SKU in the family
    # shares, capped at two. "Thums Up 750ml" + "Thums Up 2L" gives "Thums
    # Up", while "Maggi Atta Noodles" + "Maggi 2-Minute Noodles" gives
    # "Maggi". Derived from the catalogue rather than a hand-kept list, and
    # it keeps the catalogue's own casing ("7UP", "Parle-G").
    for key, items in members.items():
        heads = [i.split() for i in items]
        display = heads[0][0].strip("/,")
        if len(heads[0]) > 1 and all(
            len(h) > 1 and h[1].lower() == heads[0][1].lower() for h in heads
        ):
            second = heads[0][1].strip("/,")
            if second.lower() not in _STOPWORDS and not _NOISE_TOKEN.match(second):
                display = f"{display} {second}"
        families[key] = display

    trigger = (trigger - _WEAK_TOKENS) | _GENERIC_PRODUCT_NOUNS

    return {
        "families": families,
        "family_of": family_of,
        "family_members": members,
        "trigger_tokens": trigger,
        "searchable": searchable,
    }


def family_display(key: str) -> str:
    return _catalog_index()["families"].get(key, key.title())


def family_of(product: str) -> str:
    idx = _catalog_index()
    if product in idx["family_of"]:
        return idx["family_of"][product]
    ident = _identity_tokens(product)
    return ident[0] if ident else product.lower()


# ------------------------------------------------------------- fuzzy match

def _ratio(a: str, b: str) -> int:
    return int(round(SequenceMatcher(None, a, b).ratio() * 100))


def _token_set_ratio(a: str, b: str) -> int:
    """
    A stdlib reimplementation of thefuzz's token_set_ratio.

    Compares the shared tokens against each full string, so "maggi noodles"
    scores highly against "maggi 2 minute noodles" despite the extra words.
    Reimplemented rather than imported: thefuzz's fast path needs a C
    extension that does not build cleanly on Windows, and without it thefuzz
    falls back to this same difflib algorithm anyway.
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0

    intersection = " ".join(sorted(ta & tb))
    rest_a = " ".join(sorted(ta - tb))
    rest_b = " ".join(sorted(tb - ta))

    combined_a = f"{intersection} {rest_a}".strip()
    combined_b = f"{intersection} {rest_b}".strip()

    return max(
        _ratio(intersection, combined_a),
        _ratio(intersection, combined_b),
        _ratio(combined_a, combined_b),
    )


def match_to_catalog(phrase: str) -> tuple[Optional[str], int]:
    """
    Stage 2. A raw product description to the closest catalogue SKU.

    The brand-first boost is inherited from the original matcher: Indian
    grocery names lead with the brand, so a first-token match is strong
    evidence and keeps "lays chips" on *Lays ...* instead of
    *Too Yumm! ... Chips*.
    """
    query = " ".join(_identity_tokens(phrase))
    if not query:
        return None, 0

    idx = _catalog_index()
    query_head = query.split()[0]

    # A bare brand name ("maggi") is not ambiguous to a shopkeeper: it means
    # the line they stock first. Fuzzy scoring cannot separate SKUs inside a
    # family, so catalogue order decides rather than string length.
    if len(query.split()) == 1 and query in idx["family_members"]:
        return idx["family_members"][query][0], 100

    best_item: Optional[str] = None
    best_score = 0
    best_ratio = 0

    for item, searchable in idx["searchable"].items():
        score = _token_set_ratio(query, searchable)
        if searchable.split()[0] == query_head:
            score += 10

        if score > best_score:
            best_score, best_item = score, item
            best_ratio = _ratio(query, searchable)
        elif score == best_score and score >= 50:
            # Tie-break toward the closer overall string, which prefers the
            # shorter, more specific SKU.
            tie = _ratio(query, searchable)
            if tie > best_ratio:
                best_item, best_ratio = item, tie

    score = min(best_score, 100)
    return (best_item, score) if score >= MATCH_THRESHOLD else (None, score)


# ------------------------------------------------------- language handling

# Whisper mishears these consistently on Indian shop audio. Carried over from
# the original project and extended. Applied in Python rather than in the
# prompt so the rule-based path benefits too.
PHONETIC_MAP = {
    "maangi": "maggi", "mangy": "maggi", "magi": "maggi", "maggie": "maggi",
    "lace": "lays", "laise": "lays", "lays": "lays",
    "kurkura": "kurkure", "parle g": "parle-g", "parleg": "parle-g",
    "thumbs up": "thums up", "thumsup": "thums up",
    "colgate": "colgate", "coalgate": "colgate",
    "amool": "amul", "nandhini": "nandini",
    "bourbon": "bourbon", "burbon": "bourbon",
    "marigold": "marie gold", "mary gold": "marie gold",
}

# Hindi / Hinglish to the English word the catalogue uses.
HINDI_PRODUCTS = {
    "doodh": "toned milk", "dudh": "toned milk", "milk packet": "toned milk",
    "aloo": "potato", "aalu": "potato",
    "tamatar": "tomato", "tamaatar": "tomato",
    "pyaaz": "onion", "pyaz": "onion",
    "atta": "wheat flour", "aata": "wheat flour",
    "chawal": "rice", "chaawal": "rice",
    "cheeni": "sugar", "chini": "sugar",
    "namak": "salt", "tel": "oil",
    "sabun": "soap", "saabun": "soap",
    "biscuit": "biscuit", "bistkut": "biscuit",
    "namkeen": "namkeen", "chai": "tea", "chaipatti": "tea",
    "paani": "water", "pani": "water",
    "dahi": "curd", "makkhan": "butter",
    "anda": "egg", "chips": "chips", "noodles": "noodles",
}

# The shopkeeper reporting that something is gone. Order matters: longer
# phrases are checked first so "nahi hai" does not shadow "khatam nahi".
OUT_OF_STOCK_MARKERS = [
    "khatam ho gaya", "khatam ho gayi", "khatam hogaya", "khatam hogaye",
    "katam ho gaya", "katam hogaye", "stock khatam", "out of stock",
    "nahi milega", "nahi milta", "nhi milega",
    "abhi nahi hai", "abhi nahi", "khatam", "khatm",
    "stock nahi", "stock mein nahi", "finished", "not available",
    "nahi hai", "nhi hai", "nahi h", "no stock",
]

# The customer asking for something.
REQUEST_MARKERS = [
    "dena", "de do", "dedo", "chahiye", "chaiye", "chaye", "hai kya",
    "hai kya?", "milega", "kitne ka", "kitna", "de dijiye", "give me",
    "do you have", "want", "need", "ek", "do", "packet", "bottle",
]

# Kept from the original pipeline. Flagged, never acted on automatically.
FRAUD_MARKERS = {
    "refund": "medium", "cheat": "high", "cheating": "high",
    "fraud": "high", "scam": "high", "fake": "high", "duplicate": "medium",
    "scanner slow": "medium", "payment fail": "medium", "paisa nahi aaya": "high",
    "nakli": "high", "dhoka": "high", "धोखा": "high", "नकली": "high",
}

_SEGMENT_SPLIT = re.compile(r"[?.!|,;\n]+")


def normalise(text: str) -> str:
    out = f" {text.lower().strip()} "
    for wrong, right in PHONETIC_MAP.items():
        out = re.sub(rf"\b{re.escape(wrong)}\b", right, out)
    for hindi, english in HINDI_PRODUCTS.items():
        out = re.sub(rf"\b{re.escape(hindi)}\b", english, out)
    return out.strip()


def _has_marker(text: str, markers: Iterable[str]) -> Optional[str]:
    for marker in markers:
        if marker in text:
            return marker
    return None


# ------------------------------------------------------------- stage 1 (a)

def extract_phrases_rulebased(text: str) -> list[dict]:
    """
    Stage 1, no model required.

    Splits the line into segments, finds product mentions by looking for
    catalogue tokens, then decides availability per segment. A segment that
    reports an out-of-stock but names no product ("Nahi, khatam ho gaya")
    attaches to the product named just before it, which is how the exchange
    actually runs across a counter.
    """
    normalised = normalise(text)
    trigger_tokens = _catalog_index()["trigger_tokens"]

    results: list[dict] = []

    for raw_segment in _SEGMENT_SPLIT.split(normalised):
        segment = raw_segment.strip()
        if not segment:
            continue

        oos_marker = _has_marker(segment, OUT_OF_STOCK_MARKERS)
        request_marker = _has_marker(segment, REQUEST_MARKERS)

        tokens = _tokens(segment)
        found_here: list[dict] = []
        i = 0
        while i < len(tokens):
            if tokens[i] not in trigger_tokens:
                i += 1
                continue
            # Take the longest window (up to 3 tokens) that still matches.
            best: tuple[Optional[str], int, int] = (None, 0, 1)
            for size in (3, 2, 1):
                window = tokens[i : i + size]
                if len(window) < size:
                    continue
                item, score = match_to_catalog(" ".join(window))
                if item and score > best[1]:
                    best = (item, score, size)
            if best[0]:
                found_here.append(
                    {"product": best[0], "query": " ".join(tokens[i : i + best[2]]), "score": best[1]}
                )
                i += best[2]
            else:
                i += 1

        if found_here:
            for hit in found_here:
                results.append(
                    {
                        **hit,
                        "availability": "out_of_stock" if oos_marker else "unknown",
                        "requested": bool(request_marker) or not oos_marker,
                        "segment": segment,
                    }
                )
        elif oos_marker and results:
            # No product in this segment: the shopkeeper is answering about
            # the last thing that was asked for.
            results[-1]["availability"] = "out_of_stock"
            results[-1]["segment"] = f"{results[-1]['segment']} | {segment}"

    return results


# ------------------------------------------------------------- stage 1 (b)

# Kept close to the original Vyapaar Saathi prompt: it encodes real
# shop-floor knowledge that took iteration to get right. The catalogue is
# still withheld from the model; stage 2 owns product identity.
LLM_SYSTEM_PROMPT = """You extract product requests from an Indian kirana \
(grocery) store conversation.

Your ONLY job is to identify what products the customer is asking for and \
write a short English description of each.

Rules:
1. Extract each requested product as a SHORT English description, 1-3 words.
   Translate Hindi: "doodh" -> "milk", "aloo" -> "potato", "tamatar" -> \
"tomato", "pani" -> "water", "atta" -> "wheat flour", "maggi"/"maangi" -> \
"maggi noodles", "lays"/"lace" -> "lays chips".
   Include brand names when spoken (Nandini milk, Lays chips, Maggi noodles).
2. "items" = products the customer WANTS TO BUY. Triggers: "dena" (give me), \
"chahiye" (I need), or simply naming an item.
3. "missing" = ONLY when the STORE OWNER says an item is unavailable. \
Triggers: "nahi hai", "khatam ho gaya", "katam hogaye", "out of stock", \
"nahi milega". A customer asking for something does NOT make it missing.
4. The word "chaye" at the end of a request usually means "chahiye" (want), \
not tea. Only treat it as tea if it is clearly the item.
5. Noise, gibberish or casual chat with no product request -> empty lists.
6. This is an INDIAN store. Never output Western items like bacon or ham.
7. Output strictly valid JSON.

FORMAT: {"items": ["product 1"], "missing": ["out of stock product"]}

Examples:
Input: "bhaiya ek marigold biscuit dena"
Output: {"items": ["marie gold biscuit"], "missing": []}
Input: "bhaiya maggi hai? nahi khatam ho gaya"
Output: {"items": ["maggi noodles"], "missing": ["maggi noodles"]}
Input: "ek kilo aloo aur tamatar dena"
Output: {"items": ["potato", "tomato"], "missing": []}
Input: "doodh hai? nahi bhai khatam ho gaya"
Output: {"items": ["milk"], "missing": ["milk"]}
Input: "aaj mausam accha hai"
Output: {"items": [], "missing": []}"""


def extract_phrases_llm(text: str) -> Optional[list[dict]]:
    """
    Stage 1 via an LLM. Returns None when no provider is reachable, so the
    caller falls back to the rule-based path rather than losing the event.
    """
    from . import ai_engine

    raw = ai_engine.extract_json(LLM_SYSTEM_PROMPT, text)
    if not isinstance(raw, dict):
        return None

    items = [x for x in raw.get("items", []) if isinstance(x, str) and len(x) > 1]
    missing = [x for x in raw.get("missing", []) if isinstance(x, str) and len(x) > 1]
    missing_matched = {match_to_catalog(m)[0] for m in missing}

    results: list[dict] = []
    for phrase in items or missing:
        product, score = match_to_catalog(phrase)
        if not product:
            continue
        results.append(
            {
                "product": product,
                "query": phrase,
                "score": score,
                "availability": "out_of_stock" if product in missing_matched else "unknown",
                "requested": True,
                "segment": text,
            }
        )
    return results


# ------------------------------------------------------------------ events

@dataclass
class ShopEvent:
    event_id: str
    merchant_id: str
    timestamp: str            # full ISO-8601, the key to the unified join
    hour: int
    product: str
    product_family: str
    product_display: str
    product_query: str
    intent: str               # product_request | out_of_stock_report | suspicious_activity
    availability: str         # available | out_of_stock | unknown
    potential_lost_sale: bool
    confidence: float
    transcript: str
    source: str               # audio | demo | manual
    extractor: str            # rules | llm
    fraud_signal: Optional[dict] = field(default=None)

    # Back-reference to the buyer/seller exchange this event came from, so a
    # demand number can always be traced to the conversation that produced it.
    interaction_id: Optional[str] = field(default=None)
    interaction_outcome: Optional[str] = field(default=None)
    buyer_intent: Optional[str] = field(default=None)
    seller_response: Optional[str] = field(default=None)
    quantity: Optional[int] = field(default=None)

    def as_dict(self) -> dict:
        return asdict(self)


def detect_fraud_signal(text: str) -> Optional[dict]:
    lowered = text.lower()
    for marker, severity in FRAUD_MARKERS.items():
        if marker in lowered:
            return {
                "marker": marker,
                "severity": severity,
                "reason": f"Phrase detected in conversation: '{marker}'",
            }
    return None


def _confidence(score: int, extractor: str, availability: str) -> float:
    """
    Match strength, discounted for how much was inferred rather than heard.
    Never claims certainty: the ceiling is 0.97.
    """
    base = min(0.97, max(0.35, score / 100.0))
    if extractor == "llm":
        base = min(0.97, base + 0.04)
    if availability == "unknown":
        base -= 0.05
    return round(max(0.3, base), 2)


# An interaction outcome decides the availability an event reports. Keeping
# this mapping in one place is what stops the two stores drifting apart.
_OUTCOME_TO_AVAILABILITY = {
    "unfulfilled": "out_of_stock",
    "alternative_offered": "out_of_stock",   # the requested product still was
    "fulfilled": "available",
    "abandoned": "unknown",
    "uncertain": "unknown",
}

_OUTCOME_TO_INTENT = {
    "unfulfilled": "out_of_stock_report",
    "alternative_offered": "out_of_stock_report",
    "fulfilled": "product_request",
    "abandoned": "product_request",
    "uncertain": "product_request",
}


def build_interaction_and_events(
    transcript: str,
    *,
    merchant_id: str,
    timestamp: Optional[datetime] = None,
    source: str = "audio",
    prefer_llm: Optional[bool] = None,
):
    """
    The full pipeline, in the order the conversation actually happens.

        transcript
          -> utterances with speaker roles      (conversation.py)
          -> buyer intent + seller response
          -> interaction outcome                (interaction_outcome_engine.py)
          -> shop events                        (here)

    The interaction is the source of truth and the events are derived from
    it, so demand aggregation and the outcome engine can never disagree about
    whether a customer got what they asked for.

    Returns (interaction, events).
    """
    # Imported here, not at module scope: conversation.py imports this module
    # for the catalogue matcher, so a top-level import would be circular.
    from .interaction_outcome_engine import build_interaction

    when = timestamp or datetime.now()
    fraud = detect_fraud_signal(transcript)

    use_llm = prefer_llm if prefer_llm is not None else _llm_extraction_enabled()
    extractor = "rules"
    llm_hits: Optional[list[dict]] = None

    if use_llm:
        try:
            llm_hits = extract_phrases_llm(transcript)
            if llm_hits is not None:
                extractor = "llm"
        except Exception:  # noqa: BLE001 - never lose an event to a provider fault
            llm_hits = None

    interaction = build_interaction(
        transcript,
        merchant_id=merchant_id,
        timestamp=when,
        source=source,
        extractor=extractor,
    )

    store = event_store()
    events: list[ShopEvent] = []

    if interaction.catalog_item:
        outcome = interaction.interaction_outcome
        availability = _OUTCOME_TO_AVAILABILITY.get(outcome, "unknown")
        family = interaction.product_family or family_of(interaction.catalog_item)

        # One event per interaction, deliberately. A "request" means a
        # customer who asked, which is what a merchant counts and what a
        # restock decision turns on. The units they wanted are carried on
        # `quantity` for anyone who needs them, rather than being multiplied
        # into the request count where a misheard number would distort the
        # whole week.
        if True:
            events.append(
                ShopEvent(
                    event_id=store.next_id(),
                    merchant_id=merchant_id,
                    timestamp=when.isoformat(timespec="seconds"),
                    hour=when.hour,
                    product=interaction.catalog_item,
                    product_family=family,
                    product_display=interaction.product or family_display(family),
                    product_query=interaction.catalog_item,
                    intent=_OUTCOME_TO_INTENT.get(outcome, "product_request"),
                    availability=availability,
                    quantity=interaction.quantity,
                    potential_lost_sale=interaction.potential_lost_sale,
                    confidence=interaction.confidence,
                    transcript=transcript,
                    source=source,
                    extractor=extractor,
                    fraud_signal=fraud,
                    interaction_id=interaction.interaction_id,
                    interaction_outcome=outcome,
                    buyer_intent=interaction.buyer_intent,
                    seller_response=interaction.seller_response,
                )
            )

    # A conversation can carry a fraud signal without naming any product.
    if not events and fraud:
        events.append(
            ShopEvent(
                event_id=store.next_id(),
                merchant_id=merchant_id,
                timestamp=when.isoformat(timespec="seconds"),
                hour=when.hour,
                product="",
                product_family="",
                product_display="",
                product_query="",
                intent="suspicious_activity",
                availability="unknown",
                potential_lost_sale=False,
                confidence=0.5,
                transcript=transcript,
                source=source,
                extractor=extractor,
                fraud_signal=fraud,
                interaction_id=interaction.interaction_id,
                interaction_outcome=interaction.interaction_outcome,
                buyer_intent=interaction.buyer_intent,
                seller_response=interaction.seller_response,
            )
        )

    return interaction, events


def build_events(
    transcript: str,
    *,
    merchant_id: str,
    timestamp: Optional[datetime] = None,
    source: str = "audio",
    prefer_llm: Optional[bool] = None,
) -> list[ShopEvent]:
    """Events only. Kept so existing callers keep working unchanged."""
    _, events = build_interaction_and_events(
        transcript,
        merchant_id=merchant_id,
        timestamp=timestamp,
        source=source,
        prefer_llm=prefer_llm,
    )
    return events


def _llm_extraction_enabled() -> bool:
    from . import ai_engine

    return ai_engine.active_provider() != "template"


# ------------------------------------------------------------- event store

class ShopEventStore:
    """
    JSON-backed, append-mostly. A hackathon needs persistence across a
    restart, not a database.
    """

    def __init__(self, path: Path = EVENTS_PATH) -> None:
        self.path = path
        self._counter = 0

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, events: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(events[-MAX_EVENTS:], indent=2), encoding="utf-8")

    def next_id(self) -> str:
        with _lock:
            if not self._counter:
                self._counter = len(self._read())
            self._counter += 1
            return f"SE_{self._counter:05d}"

    def append(self, events: list[ShopEvent]) -> None:
        if not events:
            return
        with _lock:
            existing = self._read()
            existing.extend(e.as_dict() for e in events)
            self._write(existing)

    def all(self, merchant_id: Optional[str] = None) -> list[dict]:
        events = self._read()
        if merchant_id:
            events = [e for e in events if e.get("merchant_id") == merchant_id]
        return sorted(events, key=lambda e: e.get("timestamp", ""), reverse=True)

    def between(
        self, start: datetime, end: datetime, merchant_id: Optional[str] = None
    ) -> list[dict]:
        out = []
        for event in self.all(merchant_id):
            try:
                when = datetime.fromisoformat(event["timestamp"])
            except (KeyError, ValueError):
                continue
            if start <= when <= end:
                out.append(event)
        return out

    def clear(self) -> None:
        with _lock:
            self._counter = 0
            self._write([])

    def count(self) -> int:
        return len(self._read())


_store: Optional[ShopEventStore] = None


def event_store() -> ShopEventStore:
    global _store
    if _store is None:
        _store = ShopEventStore()
    return _store


class InteractionStore:
    """
    Buyer/seller exchanges, stored whole.

    Separate from the event store because the grain differs: one interaction
    can produce several demand events (a request for two packets), and the
    conversation itself has to survive intact so the dashboard can show the
    exchange that produced a number.
    """

    def __init__(self, path: Path = INTERACTIONS_PATH) -> None:
        self.path = path

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, interactions: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(interactions[-MAX_EVENTS:], indent=2), encoding="utf-8"
        )

    def append(self, interaction) -> None:
        with _lock:
            existing = self._read()
            existing.append(
                interaction if isinstance(interaction, dict) else interaction.as_dict()
            )
            self._write(existing)

    def all(self, merchant_id: Optional[str] = None) -> list[dict]:
        interactions = self._read()
        if merchant_id:
            interactions = [
                i for i in interactions if i.get("merchant_id") == merchant_id
            ]
        return sorted(interactions, key=lambda i: i.get("timestamp", ""), reverse=True)

    def between(
        self, start: datetime, end: datetime, merchant_id: Optional[str] = None
    ) -> list[dict]:
        out = []
        for interaction in self.all(merchant_id):
            try:
                when = datetime.fromisoformat(interaction["timestamp"])
            except (KeyError, ValueError):
                continue
            if start <= when <= end:
                out.append(interaction)
        return out

    def clear(self) -> None:
        with _lock:
            self._write([])

    def count(self) -> int:
        return len(self._read())


_interaction_store: Optional[InteractionStore] = None


def interaction_store() -> InteractionStore:
    global _interaction_store
    if _interaction_store is None:
        _interaction_store = InteractionStore()
    return _interaction_store


# -------------------------------------------------------------- demo seeding

# A scripted shop day. Deterministic: same script, same events, every run.
# Weighted toward the evening so it lands inside the same window the
# transaction data shows declining, which is the whole point of the join.
# A scripted shop week, written as buyer/seller exchanges rather than lone
# utterances so the whole conversation pipeline is exercised by the demo and
# not only by tests. Deterministic: same script, same events, every run.
#
# The story the numbers tell: Maggi sold normally at the start of the week,
# ran out, and was then refused twelve times, mostly in the evening window
# where the transaction data independently shows a decline.
#
#   (days_ago, hour, transcript, repeat_count)
DEMO_SCRIPT: list[tuple[int, int, str, int]] = [
    # --- Maggi, still in stock early in the week: 2 fulfilled -------------
    (6, 9, "Bhaiya ek Maggi dena. Haan, 20 rupaye. UPI kar diya", 1),
    (6, 11, "Do packet Maggi dena. Haan deta hoon", 1),

    # --- Maggi runs out: 12 unfulfilled, weighted to the evening ----------
    (6, 20, "Maggi noodles hai? Nahi hai abhi", 1),
    (5, 19, "Bhaiya Maggi dena do packet. Khatam ho gaya", 2),
    (4, 20, "Maggi packet hai? Nahi milega abhi", 1),
    (3, 19, "Maggi hai kya? Nahi stock khatam", 2),
    (2, 19, "Bhaiya Maggi noodles chahiye. Khatam ho gaya bhai", 1),
    (1, 19, "Maggi milega kya? Nahi abhi nahi hai", 2),
    (0, 20, "Ek Maggi packet dena. Sorry khatam ho gaya hai", 1),
    (0, 19, "Bhaiya Maggi hai? Nahi beta khatam ho gaya", 2),

    # --- Ordinary trade, all fulfilled -----------------------------------
    (0, 18, "Amul butter aur Parle-G dena. Haan lijiye", 1),
    (0, 9, "Do Parle-G packet dena. Haan deta hoon", 2),
    (0, 11, "Nandini milk dena. Haan hai, lijiye", 1),
    (1, 20, "Do Lays packet dena. Haan lijiye", 1),
    (1, 18, "Nandini milk hai? Haan hai lijiye", 1),
    (1, 9, "Britannia Good Day biscuit dena. Haan deta hoon", 2),
    (2, 21, "Thums Up ek bottle dena. Haan lijiye", 1),
    (2, 8, "Tata Tea premium ek packet. Haan deta hoon", 2),
    (2, 16, "Surf Excel detergent dena. Haan lijiye", 1),
    (3, 20, "Colgate toothpaste dena ek. Haan deta hoon", 1),
    (3, 18, "Ek Maaza aur do Kurkure dedo. Haan lijiye", 1),
    (3, 9, "Parle-G aur Amul butter chahiye. Haan deta hoon", 1),
    (4, 19, "Britannia Good Day biscuit dena. Haan lijiye", 1),
    (4, 12, "Ek Pepsi bottle dena. Haan deta hoon", 1),
    (5, 11, "Tata Tea premium dena. Haan lijiye", 1),
    (5, 16, "Haldirams namkeen dena ek. Haan deta hoon", 1),
    (5, 20, "Sprite ek bottle dena. Haan lijiye", 1),
    (6, 17, "Ek Thums Up aur Lays dena. Haan deta hoon", 1),
    (6, 12, "Surf Excel aur Vim bar dena. Haan lijiye", 1),

    # --- A flagged phrase, for the fraud-signal path ----------------------
    (6, 15, "Bhai ye payment fail ho gaya, refund chahiye", 1),
]

# The week before. Same shop, same trade, but Maggi was in stock, so almost
# every request was filled.
#
# This exists for a methodological reason, not for volume: comparing a week
# that has shop-floor data against one that does not would make the health
# score move purely because the feature was switched on. Both weeks are
# scored on the same basis, so the week-over-week change is real.
DEMO_SCRIPT_PREVIOUS: list[tuple[int, int, str, int]] = [
    (7, 19, "Bhaiya Maggi hai? Haan hai, kitna chahiye", 2),
    (7, 20, "Do packet Maggi dena. Haan deta hoon", 1),
    (8, 19, "Ek Maggi dena. Haan, 20 rupaye. UPI kar diya", 2),
    (9, 19, "Maggi milega? Haan lijiye", 2),
    (10, 20, "Bhaiya Maggi do packet dena. Haan deta hoon", 2),
    (11, 19, "Maggi hai kya? Haan hai lijiye", 2),
    (12, 20, "Ek Maggi packet dena. Haan deta hoon", 1),
    (13, 19, "Maggi noodles dena. Haan lijiye", 1),

    (7, 9, "Do Parle-G packet dena. Haan deta hoon", 2),
    (7, 18, "Amul butter dena. Haan lijiye", 1),
    (8, 9, "Britannia Good Day biscuit dena. Haan deta hoon", 2),
    (8, 20, "Do Lays packet dena. Haan lijiye", 1),
    (9, 8, "Tata Tea premium ek packet. Haan deta hoon", 2),
    (9, 21, "Thums Up ek bottle dena. Haan lijiye", 1),
    (10, 12, "Ek Pepsi bottle dena. Haan deta hoon", 1),
    (10, 16, "Surf Excel detergent dena. Haan lijiye", 1),
    (11, 9, "Nandini milk dena. Haan hai, lijiye", 2),
    (11, 18, "Ek Maaza aur do Kurkure dedo. Haan lijiye", 1),
    (12, 11, "Colgate toothpaste dena ek. Haan deta hoon", 1),
    (12, 17, "Haldirams namkeen dena ek. Haan lijiye", 1),
    (13, 12, "Sprite ek bottle dena. Haan deta hoon", 1),
    (13, 16, "Vim bar aur Surf Excel dena. Haan lijiye", 1),

    # Two genuine misses, so the previous week is a real shop and not a
    # perfect one. Below the chronic-shortage threshold, by design.
    (10, 19, "Britannia bread hai? Nahi khatam ho gaya", 1),
    (12, 19, "Frooti hai kya? Nahi abhi nahi hai", 1),
]


def seed_demo_events(
    merchant_id: str, anchor: datetime, *, replace: bool = True
) -> int:
    """
    Populate the store with the scripted day, anchored to the dataset's
    'today' so shop events and transactions describe the same seven days.
    """
    store = event_store()
    interactions = interaction_store()
    if replace:
        store.clear()
        interactions.clear()

    created = 0
    for days_ago, hour, transcript, repeats in DEMO_SCRIPT + DEMO_SCRIPT_PREVIOUS:
        for index in range(repeats):
            when = (anchor - timedelta(days=days_ago)).replace(
                hour=hour,
                minute=(7 + index * 17 + days_ago * 3) % 60,
                second=0,
                microsecond=0,
            )
            interaction, events = build_interaction_and_events(
                transcript,
                merchant_id=merchant_id,
                timestamp=when,
                source="demo",
                prefer_llm=False,   # determinism matters more than phrasing here
            )
            interactions.append(interaction)
            store.append(events)
            created += len(events)

    return created


def demo_mode_enabled() -> bool:
    return os.environ.get("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def ensure_demo_events(merchant_id: str, anchor: datetime) -> None:
    """Seed once, on first read, when DEMO_MODE is on and the store is empty."""
    if demo_mode_enabled() and event_store().count() == 0:
        seed_demo_events(merchant_id, anchor)
