"""
AI explanation layer.

Four providers behind one `AI_PROVIDER` switch:

    template   deterministic, no network, no keys        (default)
    ollama     a local model over Ollama's HTTP API
    openai     OpenAI chat completions
    anthropic  the Anthropic Messages API

The template engine is not a degraded mode. It is the default, and it is what
the demo runs on. Selecting a model changes phrasing only: never the score,
never an anomaly, never a number.

The hard rule in every LLM path: every figure in an answer comes from the
structured context built by the analytics engines. The model is given the
figures and told to explain them, never to compute or estimate them.

The same abstraction serves a second, different job: `extract_json` runs
stage 1 of shop-floor extraction, where the model converts Hinglish speech
into product descriptions and Python still owns product identity.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

from .transaction_analytics import AnalyticsContext, EVENING_HOURS, hour_range_label

ANTHROPIC_MODEL = "claude-opus-5"
OPENAI_MODEL = "gpt-4o-mini"
OLLAMA_MODEL = "qwen2.5"
OLLAMA_HOST = "http://localhost:11434"
REQUEST_TIMEOUT = 30.0
EXTRACTION_TIMEOUT = 20.0

VALID_PROVIDERS = ("template", "mock", "sarvam", "ollama", "openai", "anthropic")

SYSTEM_PROMPT = """You are Paytm Business AI, an analyst speaking directly to a small \
merchant about their own shop.

Rules you must follow:
- Use ONLY the figures in the CONTEXT block. Never invent, estimate, or \
extrapolate a number that is not there.
- If the context does not contain what is needed to answer, say so plainly.
- Write for a busy shop owner: short sentences, no jargon, no bullet-point \
walls. Two or three short paragraphs at most.
- Amounts are Indian rupees; write them as Rs 1,234.
- Be direct about problems, and mention what is going well when the data \
supports it.
- Close with one concrete next step only when the context includes a \
recommendation.
- Never promise or guarantee a result.
- The CONTEXT may contain a `shop_floor` block. Those are things customers \
ASKED FOR out loud in the shop. They are not sales and are not in the payment \
data, which is exactly why they are useful.
- When a shop-floor signal and a transaction signal line up in time, that is \
CO-OCCURRENCE, not cause. Write "coincides with", "may be contributing", or \
"a potential missed sale". Never write that one caused the other."""


# ------------------------------------------------------------------ context

def build_ai_context(
    ctx: AnalyticsContext,
    health: dict,
    insights: list[dict],
    recommendation: Optional[dict] = None,
    demand: Optional[dict] = None,
    unified: Optional[dict] = None,
) -> dict:
    """
    The structured facts every provider (LLM or template) answers from.

    `demand` and `unified` are what make this a Vyapaar AI context rather
    than a Business Health one: the model can now speak about products
    customers asked for and did not get, which never appear in the ledger.
    """
    cur = ctx.customers_current
    context = {
        "merchant": "Raj's Tea & Snacks",
        "period": {
            "this_week": [
                ctx.current.start.date().isoformat(),
                ctx.current.end.date().isoformat(),
            ],
            "compared_with": "the previous 7 days and the 4 weeks before that",
        },
        "health_score": {
            "current": health["overall_score"],
            "previous": health["previous_score"],
            "change": health["change"],
            "status": health["status"],
            "components": health["components"],
        },
        "revenue": {
            "this_week": round(ctx.current.revenue),
            "last_week": round(ctx.previous.revenue),
            "change_percent": ctx.revenue_growth_wow,
            "vs_four_week_average_percent": ctx.revenue_vs_baseline,
        },
        "transactions": {
            "this_week": ctx.current.txns,
            "last_week": ctx.previous.txns,
            "change_percent": ctx.txn_growth_wow,
            "average_sale": round(ctx.current.avg_ticket),
            "average_sale_vs_baseline_percent": ctx.avg_ticket_vs_baseline,
        },
        "customers": {
            "total_this_week": cur["total_customers"],
            "returning": cur["repeat_customers"],
            "new": cur["new_customers"],
            "repeat_rate_percent": cur["repeat_customer_rate"],
            "repeat_purchases_change_percent": ctx.repeat_txn_change,
        },
        "time_of_day": {
            "evening_window": hour_range_label(*EVENING_HOURS),
            "evening_change_percent": ctx.evening_change,
            "evening_transactions_per_day_now": round(ctx.evening_current_per_day, 1),
            "evening_transactions_per_day_before": round(ctx.evening_baseline_per_day, 1),
            "evening_revenue_lost_per_day": round(ctx.evening_revenue_gap_per_day),
            "quietest_hours": [h["label"] for h in sorted(ctx.weak_hours(3), key=lambda w: w["hour"])],
            "busiest_hours": [h["label"] for h in ctx.peak_hours(3)],
        },
        "weekend": {"change_percent": ctx.weekend_change},
        "key_findings": [
            {
                "what": i["title"],
                "change_percent": i["change_percent"],
                "kind": i["kind"],
                "detail": i["description"],
            }
            for i in insights
        ],
        "recommendation": (
            {
                "name": recommendation["name"],
                "cashback": recommendation["config"]["cashback_amount"],
                "minimum_transaction": recommendation["config"]["minimum_transaction"],
                "window": recommendation["config"]["window_label"],
                "why": recommendation["why_now"],
            }
            if recommendation
            else None
        ),
    }

    if demand:
        context["shop_floor"] = {
            "note": (
                "Captured from conversation in the shop. These are things "
                "customers asked for; they are NOT transactions and never "
                "appear in the payment data."
            ),
            "total_requests": demand.get("total_requests", 0),
            "conversations_captured": demand.get("conversations_captured", 0),
            "unfulfilled_requests": demand.get("unfulfilled_requests", 0),
            "high_demand_products": demand.get("high_demand_products", [])[:5],
            "out_of_stock_products": [
                {
                    "product": p["product"],
                    "requests": p["requests"],
                    "unfulfilled_requests": p["unfulfilled_requests"],
                }
                for p in demand.get("out_of_stock_requests", [])[:5]
            ],
            "estimated_lost_revenue": demand.get("estimated_lost_revenue"),
            "estimate_caveat": demand.get("lost_revenue_basis"),
        }

    if unified:
        context["unified_findings"] = [
            {
                "title": i["title"],
                "severity": i["severity"],
                "confidence": i["confidence"],
                "transaction_signal": i.get("transaction_signal"),
                "shop_signal": i.get("shop_signal"),
                "explanation": i["explanation"],
            }
            for i in unified.get("insights", [])[:4]
        ]
        context["correlation_rules"] = (
            "Findings that combine a transaction signal with a shop signal are "
            "TEMPORAL CO-OCCURRENCE ONLY. Say 'coincides with', 'may be "
            "contributing' or 'potential missed sale'. Never say one caused the "
            "other."
        )

    return context


# ------------------------------------------------------ provider selection

def _ollama_host() -> str:
    return os.environ.get("OLLAMA_URL", OLLAMA_HOST).rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", OLLAMA_MODEL)


def configured_provider() -> str:
    """What `AI_PROVIDER` asks for, defaulting to the built-in engine."""
    requested = os.environ.get("AI_PROVIDER", "template").strip().lower()
    return requested if requested in VALID_PROVIDERS else "template"


def active_provider() -> str:
    """
    What will actually run, after checking credentials.

    Selection is explicit: an API key sitting in the environment does not by
    itself switch the product onto a model. That keeps the demo reproducible
    on any machine, and makes "it worked on mine" impossible.
    """
    requested = configured_provider()

    if requested == "sarvam":
        from .providers import sarvam

        # A configured-but-keyless Sarvam must not break the product. It falls
        # back to the deterministic engine and says so via provider_status().
        return "sarvam" if sarvam.is_configured() else "template"

    # `mock` is an explicit, offline stand-in used by tests and by demos where
    # deterministic phrasing is wanted regardless of what keys are present.
    if requested == "mock":
        return "template"

    if requested == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if requested == "openai" and os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if requested == "ollama":
        return "ollama"
    return "template"


# ----------------------------------------------------------------- providers

def _ollama_chat(system: str, user: str, *, want_json: bool, timeout: float) -> str:
    """
    Ollama's HTTP API directly, rather than the `ollama` Python SDK.

    httpx is already a dependency for the other two providers, so this keeps
    the package count down and makes all three providers the same shape.
    """
    payload: dict[str, Any] = {
        "model": _ollama_model(),
        "stream": False,
        "options": {"temperature": 0.0 if want_json else 0.3},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if want_json:
        payload["format"] = "json"

    response = httpx.post(f"{_ollama_host()}/api/chat", json=payload, timeout=timeout)
    response.raise_for_status()
    text = (response.json().get("message", {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("Empty response from Ollama")
    return text


def _anthropic_answer(question: str, context: dict, api_key: str) -> str:
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 700,
        "system": SYSTEM_PROMPT,
        # Low effort keeps the dashboard responsive; this is explanation, not
        # analysis; the numbers are already computed.
        "output_config": {"effort": "low"},
        "messages": [
            {
                "role": "user",
                "content": (
                    f"CONTEXT:\n{json.dumps(context, indent=2)}\n\n"
                    f"MERCHANT'S QUESTION: {question}"
                ),
            }
        ],
    }
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()

    if body.get("stop_reason") == "refusal":
        raise RuntimeError("Anthropic declined the request")

    parts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise RuntimeError("Empty response from Anthropic")
    return text


def _openai_answer(question: str, context: dict, api_key: str) -> str:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("OPENAI_MODEL", OPENAI_MODEL),
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"CONTEXT:\n{json.dumps(context, indent=2)}\n\n"
                        f"MERCHANT'S QUESTION: {question}"
                    ),
                },
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"].strip()
    if not text:
        raise RuntimeError("Empty response from OpenAI")
    return text


# ------------------------------------------------------- deterministic engine

def _rupees(value: Any) -> str:
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return "Rs 0"


def _classify(question: str) -> str:
    q = (question or "").lower()

    def has(*words: str) -> bool:
        return any(w in q for w in words)

    # Checked first: these are the questions only the merged product can
    # answer, and several of them also contain "improve" or "revenue" words.
    if has("stock", "out of stock", "restock", "shelf", "inventory", "unavailable"):
        return "stock"
    if has("ask", "asking", "request", "demand", "shop floor", "customers want",
           "wanted", "maggi", "product"):
        return "demand"

    if has("improve", "fix", "better", "what should i do", "how do i", "grow", "increase"):
        return "improve"
    if has("doing well", "good", "positive", "working", "strength"):
        return "positive"
    if has("hurting", "wrong", "problem", "bad", "worst", "issue"):
        return "problems"
    if has("customer", "repeat", "loyal", "returning"):
        return "customers"
    if has("evening", "time", "hour", "when", "peak", "quiet"):
        return "timing"
    if has("revenue", "sales", "money", "earning", "income", "low this week"):
        return "revenue"
    if has("campaign", "offer", "cashback", "promotion"):
        return "campaign"
    return "why_score"


def _template_answer(question: str, context: dict) -> str:
    intent = _classify(question)
    hs = context["health_score"]
    rev = context["revenue"]
    txn = context["transactions"]
    cust = context["customers"]
    tod = context["time_of_day"]
    weekend = context["weekend"]
    rec = context.get("recommendation")

    negatives = [f for f in context["key_findings"] if f["kind"] == "negative"]
    positives = [f for f in context["key_findings"] if f["kind"] == "positive"]

    direction = "dropped" if hs["change"] < 0 else "improved"
    movement = (
        f"Your Business Health Score {direction} by {abs(hs['change'])} points this week, "
        f"from {hs['previous']} to {hs['current']} out of 100."
    )

    good_news = ""
    if positives:
        top = positives[0]
        good_news = f"On the positive side, {top['detail'][0].lower()}{top['detail'][1:]}"
    elif weekend["change_percent"] > 0:
        good_news = f"On the positive side, weekend revenue is up {weekend['change_percent']:.0f}%."

    next_step = ""
    if rec:
        next_step = (
            f"Recommended next step: run a {_rupees(rec['cashback'])} cashback offer on orders "
            f"above {_rupees(rec['minimum_transaction'])} between {rec['window']}, your weakest "
            f"window right now."
        )

    shop = context.get("shop_floor")
    unified = context.get("unified_findings") or []

    if intent in {"stock", "demand"}:
        if not shop or not shop.get("total_requests"):
            return (
                "No shop-floor conversation has been captured yet, so I can only "
                "see what customers bought, not what they asked for. Connect the "
                "shop listener, or turn on demo mode, and this becomes answerable."
            )

        missing = shop.get("out_of_stock_products") or []
        top = (shop.get("high_demand_products") or [{}])[0]

        lines = [
            f"Customers made {shop['total_requests']} product requests across "
            f"{shop['conversations_captured']} conversations this week."
        ]
        if top.get("product"):
            lines.append(
                f"{top['product']} was the most asked for, {top['requests']} times."
            )
        if missing:
            worst = missing[0]
            lines.append(
                f"\n{worst['product']} is the problem: asked for "
                f"{worst['requests']} times, and {worst['unfulfilled_requests']} of "
                f"those requests could not be filled. None of that reaches your "
                f"payment data, because a sale that does not happen leaves no record."
            )
            if unified and unified[0].get("transaction_signal"):
                signal = unified[0]["transaction_signal"]
                lines.append(
                    f"\nThat coincides with {signal['metric'].lower()} running "
                    f"{abs(signal['change_percent']):.0f}% below normal in the same "
                    f"window. It may be contributing; the data shows the overlap, "
                    f"not the cause."
                )
            lines.append(f"\nRecommended next step: restock {worst['product']}.")
        else:
            lines.append(
                "\nNothing was reported out of stock this week, so demand is being met."
            )
        return "\n".join(lines)

    if intent == "improve":
        body = (
            f"The biggest single opportunity is your {tod['evening_window']} window. It is running "
            f"{abs(tod['evening_change_percent']):.0f}% below normal, which works out to about "
            f"{_rupees(tod['evening_revenue_lost_per_day'])} of lost takings a day.\n\n"
            f"Your second lever is your regulars: repeat purchases are "
            f"{abs(cust['repeat_purchases_change_percent']):.0f}% down, and returning customers are "
            f"cheaper to bring back than new ones are to find. "
            f"{tod['quietest_hours'][0]} to {tod['quietest_hours'][-1]} is your quietest stretch if you "
            f"want a second window to work on later."
        )
        return "\n\n".join(p for p in [body, next_step] if p)

    if intent == "positive":
        lines = [
            f"Your average sale has grown to {_rupees(txn['average_sale'])}, "
            f"{txn['average_sale_vs_baseline_percent']:+.0f}% against the same baseline. "
            f"Customers who do come in are spending more.",
        ]
        for item in positives[:2]:
            lines.append(item["detail"])
        # Only add the generic weekend line if no finding already covers it.
        if weekend["change_percent"] > 0 and not any(
            "weekend" in line.lower() for line in lines
        ):
            lines.insert(
                0,
                f"Weekend revenue is up {weekend['change_percent']:.0f}% "
                "against your 4-week average.",
            )
        return (
            "A few things are genuinely working:\n\n"
            + "\n".join(f"- {line}" for line in dict.fromkeys(lines))
            + f"\n\nThat is why your score is still {hs['current']} rather than lower: "
            "the weakness is concentrated in one window, not spread across the business."
        )

    if intent == "customers":
        return (
            f"You served {cust['total_this_week']} customers this week: {cust['returning']} returning "
            f"and {cust['new']} new, a repeat rate of {cust['repeat_rate_percent']:.0f}%.\n\n"
            f"Repeat purchases are down {abs(cust['repeat_purchases_change_percent']):.0f}% on last week. "
            f"That is the part worth watching. Your regulars are the ones who normally fill your "
            f"{tod['evening_window']} window, and that window is down "
            f"{abs(tod['evening_change_percent']):.0f}% at the same time."
            + (f"\n\n{next_step}" if next_step else "")
        )

    if intent == "timing":
        return (
            f"Your busiest hours are {', '.join(tod['busiest_hours'])}. "
            f"The quietest are {', '.join(tod['quietest_hours'])}.\n\n"
            f"The problem right now is not the quiet stretch. It is your {tod['evening_window']} peak, "
            f"which has fallen from about {tod['evening_transactions_per_day_before']:.0f} transactions "
            f"a day to {tod['evening_transactions_per_day_now']:.0f}. That single window accounts for "
            f"roughly {_rupees(tod['evening_revenue_lost_per_day'])} a day in lost takings."
            + (f"\n\n{next_step}" if next_step else "")
        )

    if intent == "revenue":
        return (
            f"You took {_rupees(rev['this_week'])} this week against {_rupees(rev['last_week'])} last "
            f"week, a change of {rev['change_percent']:+.1f}%. Against your 4-week average you are "
            f"{rev['vs_four_week_average_percent']:+.1f}%.\n\n"
            f"Volume is the cause rather than pricing: {txn['this_week']} transactions against "
            f"{txn['last_week']}, while your average sale actually rose to "
            f"{_rupees(txn['average_sale'])}. Fewer customers, each spending a little more."
            + (f"\n\n{next_step}" if next_step else "")
        )

    if intent == "campaign":
        if not rec:
            return "There is no campaign recommendation for you right now. Your numbers are holding steady."
        return (
            f"{rec['why']}\n\n"
            f"The suggested offer is {_rupees(rec['cashback'])} cashback on orders above "
            f"{_rupees(rec['minimum_transaction'])}, running {rec['window']}. The minimum is set just "
            f"under your typical evening basket, so most customers clear it by adding one item.\n\n"
            "Based on your historical patterns this targets your weakest window. It may improve "
            "evening engagement. It is not a guaranteed result."
        )

    # "problems" and the default "why_score" share a shape.
    problem_lines = [f"- {n['detail']}" for n in negatives[:3]]
    intro = (
        movement
        if intent == "why_score"
        else "Here is what is pulling your numbers down this week:"
    )
    return "\n\n".join(
        p
        for p in [
            intro,
            ("\n".join(problem_lines) if problem_lines else None),
            good_news or None,
            next_step or None,
        ]
        if p
    )


# ------------------------------------------------------------------- public

def _model_name(provider: str) -> str:
    if provider == "sarvam":
        from .providers import sarvam

        return sarvam.chat_model()
    return {
        "anthropic": ANTHROPIC_MODEL,
        "openai": os.environ.get("OPENAI_MODEL", OPENAI_MODEL),
        "ollama": _ollama_model(),
    }.get(provider, "built-in insight engine")


def provider_status() -> dict:
    active = active_provider()
    label = {
        "anthropic": f"Anthropic ({ANTHROPIC_MODEL})",
        "openai": f"OpenAI ({os.environ.get('OPENAI_MODEL', OPENAI_MODEL)})",
        "ollama": f"Ollama ({_ollama_model()})",
        "sarvam": f"Sarvam AI ({_model_name('sarvam')})",
        "template": "Built-in insight engine",
    }[active]

    requested = configured_provider()
    payload = {
        "provider": active,
        "configured": requested,
        "label": label,
        "model": _model_name(active),
        "llm_enabled": active != "template",
    }

    # Say plainly when the requested provider could not be used, rather than
    # letting the demo look configured when it silently is not.
    if requested == "sarvam" and active == "template":
        payload["fallback_reason"] = (
            "SARVAM_API_KEY is not set, so the deterministic engine is being "
            "used. Numbers are identical either way; only phrasing changes."
        )
    return payload


def answer(question: str, context: dict) -> dict:
    """
    Answer a merchant question. Never raises: any provider failure falls
    through to the deterministic engine so the product keeps working, and
    the reason is reported rather than hidden.
    """
    provider = active_provider()
    prompt = f"CONTEXT:\n{json.dumps(context, indent=2)}\n\nMERCHANT'S QUESTION: {question}"
    error: Optional[str] = None

    if provider != "template":
        try:
            if provider == "anthropic":
                text = _anthropic_answer(
                    question, context, os.environ["ANTHROPIC_API_KEY"]
                )
            elif provider == "openai":
                text = _openai_answer(question, context, os.environ["OPENAI_API_KEY"])
            elif provider == "sarvam":
                from .providers import sarvam

                text = sarvam.chat(SYSTEM_PROMPT, prompt)
            else:
                text = _ollama_chat(
                    SYSTEM_PROMPT, prompt, want_json=False, timeout=REQUEST_TIMEOUT
                )
            return {
                "answer": text,
                "provider": provider,
                "model": _model_name(provider),
                "fallback_used": False,
            }
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the request
            error = f"{provider}: {type(exc).__name__}"

    return {
        "answer": _template_answer(question, context),
        "provider": "template",
        "model": "built-in insight engine",
        "fallback_used": bool(error),
        "fallback_reason": error,
    }


def extract_json(system_prompt: str, user_text: str) -> Optional[dict]:
    """
    Stage 1 of shop-floor extraction, when a model is configured.

    Returns None on any failure so the caller falls back to the rule-based
    extractor rather than dropping the event. Never raises.
    """
    provider = active_provider()
    if provider == "template":
        return None

    try:
        if provider == "sarvam":
            from .providers import sarvam

            return sarvam.extract_json(system_prompt, user_text)
        if provider == "ollama":
            raw = _ollama_chat(
                system_prompt, user_text, want_json=True, timeout=EXTRACTION_TIMEOUT
            )
        elif provider == "openai":
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                    "content-type": "application/json",
                },
                json={
                    "model": os.environ.get("OPENAI_MODEL", OPENAI_MODEL),
                    "max_tokens": 300,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text},
                    ],
                },
                timeout=EXTRACTION_TIMEOUT,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
        else:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 300,
                    "system": system_prompt,
                    "output_config": {"effort": "low"},
                    "messages": [
                        {"role": "user", "content": user_text},
                        # Prefilling the opening brace keeps the reply to bare
                        # JSON without needing a "no preamble" instruction.
                        {"role": "assistant", "content": "{"},
                    ],
                },
                timeout=EXTRACTION_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
            parts = [
                b.get("text", "")
                for b in body.get("content", [])
                if b.get("type") == "text"
            ]
            raw = "{" + "".join(parts)

        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001 - the rule-based path is always available
        return None


SUGGESTED_QUESTIONS = [
    "Why did my score drop?",
    "What are customers asking for?",
    "What is out of stock?",
    "What is hurting my business?",
    "What is doing well?",
    "How can I improve?",
    "Tell me about my customers",
]
