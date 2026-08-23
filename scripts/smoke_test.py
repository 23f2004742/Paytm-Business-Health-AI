"""
End-to-end smoke test.

Walks the entire demo flow against a running backend and asserts the things
that actually have to be true for the product to work. No pytest, no fixtures:
one file, standard library only.

    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://192.168.1.10:8000

Exit code 0 means the whole pipeline works.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((PASS if condition else FAIL, name, detail))
    marker = "  ok  " if condition else " FAIL "
    print(f"[{marker}] {name}" + (f"  -- {detail}" if detail and not condition else ""))
    return condition


def request(base: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def status_of(base: str, path: str, method: str = "GET", body: dict | None = None) -> int:
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={"content-type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    base = parser.parse_args().base.rstrip("/")

    print(f"Paytm Vyapaar AI: smoke test against {base}\n")

    # ---- 0. liveness ------------------------------------------------------
    try:
        health = request(base, "/health")
    except Exception as exc:  # noqa: BLE001
        print(f"[ FAIL ] Backend unreachable at {base}: {type(exc).__name__}")
        print("\nStart it with:  cd backend && uvicorn app.main:app --port 8000")
        return 1

    check("backend is up", health.get("status") == "ok")
    check(
        "runs without an LLM",
        health["ai_provider"]["provider"] == "template",
        f"provider is {health['ai_provider']['provider']} (fine, but not the default path)",
    )

    # ---- 1. clean slate ---------------------------------------------------
    reset = request(base, "/api/demo/reset", "POST")
    check("demo reset works", reset.get("status") == "ok")
    check(
        "reset re-seeds the shop floor",
        reset.get("shop_events_seeded", 0) > 0,
        f"seeded {reset.get('shop_events_seeded')}",
    )

    # ---- 2. transaction intelligence --------------------------------------
    score = request(base, "/api/health-score")
    check(
        "health score is in range",
        0 <= score["overall_score"] <= 100,
        str(score["overall_score"]),
    )
    check("score is deterministic", request(base, "/api/health-score")["overall_score"] == score["overall_score"])
    check(
        "score has 6 components incl. demand fulfilment",
        len(score["components"]) == 6 and "demand_fulfillment" in score["components"],
        str(sorted(score["components"])),
    )
    check(
        "both weeks scored on a comparable basis",
        score.get("comparable_basis") is True,
        "one week has shop data and the other does not; the delta would be an artefact",
    )
    check("component weights sum to 1", abs(sum(score["weights"].values()) - 1.0) < 0.001)

    anomalies = request(base, "/api/anomalies")
    check(
        "anomaly detection finds signals",
        anomalies["counts"]["total"] > 0,
        f"{anomalies['counts']['total']} found",
    )
    check(
        "evening decline detected",
        any("evening" in a["id"] for a in anomalies["anomalies"]),
    )

    # ---- 3. shop-floor intelligence ---------------------------------------
    shop = request(base, "/api/shop-intelligence/summary")
    check("shop requests captured", shop["total_requests"] > 0, str(shop["total_requests"]))
    check(
        "high-demand product identified",
        len(shop["high_demand_products"]) > 0,
    )
    check(
        "out-of-stock demand identified",
        len(shop["out_of_stock_requests"]) > 0,
    )

    top = shop["out_of_stock_requests"][0] if shop["out_of_stock_requests"] else {}
    check(
        "Maggi is the lead shortage",
        top.get("product") == "Maggi",
        f"got {top.get('product')!r}",
    )
    check(
        "Maggi requested ~14 times",
        12 <= top.get("requests", 0) <= 16,
        f"got {top.get('requests')}",
    )

    # ---- 4. live extraction (no mic, no model) ----------------------------
    extracted = request(
        base,
        "/api/shop-intelligence/text",
        "POST",
        {"transcript": "Bhaiya Maggi hai? Nahi khatam ho gaya"},
    )
    events = extracted.get("events", [])
    check("transcript produces an event", len(events) == 1, f"got {len(events)}")
    if events:
        event = events[0]
        check("product resolved to the catalogue", event["product_display"] == "Maggi")
        check("availability read as out of stock", event["availability"] == "out_of_stock")
        check("flagged as a potential lost sale", event["potential_lost_sale"] is True)
        check("event carries a full ISO timestamp", "T" in event["timestamp"])

    quiet = request(
        base, "/api/shop-intelligence/text", "POST", {"transcript": "aaj mausam accha hai"}
    )
    check("small talk produces no events", quiet.get("event_count") == 0)

    # ---- 5. the unified join ----------------------------------------------
    unified = request(base, "/api/insights/unified")
    check(
        "a unified insight exists",
        unified["counts"]["unified"] > 0,
        "no insight joined both sources",
    )
    check(
        "single-source signals still surface",
        unified["counts"]["transaction_only"] + unified["counts"]["shop_only"] > 0,
    )

    lead = unified["insights"][0]
    check("unified insight leads the ranking", lead["kind"] == "unified")
    check("it carries a payment signal", bool(lead.get("transaction_signal")))
    check("it carries a shop-floor signal", bool(lead.get("shop_signal")))
    check("confidence is capped below certainty", lead["confidence"] <= 0.9)

    text = " ".join(
        [i["explanation"] + " " + i["correlation_note"] for i in unified["insights"]]
    ).lower()
    banned = ["caused by", "because of", "as a result of", "due to", "proves"]
    found = [phrase for phrase in banned if phrase in text]
    check("no causal language is used", not found, f"found: {found}")
    check(
        "hedged language is used",
        any(p in text for p in ["coincide", "may be contributing", "potential"]),
    )

    # ---- 6. recommendations ------------------------------------------------
    plan = request(base, "/api/actions")
    types = {a["type"] for a in plan["actions"]}
    check("campaign action offered", "campaign" in types)
    check("restock action offered", "restock" in types)
    check("combined action offered", "combined" in types)
    check("combined action leads", plan["primary_type"] == "combined")

    combined = next(a for a in plan["actions"] if a["type"] == "combined")
    check("combined action is sequenced", len(combined.get("steps", [])) == 2)
    check(
        "restock is sequenced first",
        combined["steps"][0]["action"] == "restock",
        "campaign before restock would drive traffic at an empty shelf",
    )

    campaign = next(a for a in plan["actions"] if a["type"] == "campaign")
    check("campaign is sized from data", campaign["config"]["cashback_amount"] > 0)
    check(
        "projection is labelled simulated",
        "Simulated" in campaign["projection"]["label"],
    )
    check("projection has stated assumptions", len(campaign["projection"]["assumptions"]) > 0)

    # ---- 7. merchant actions ------------------------------------------------
    alert = request(base, "/api/restock-alerts", "POST", {"product": "Maggi"})
    check("restock alert created", alert["status"] == "OPEN")
    check("alert evidence comes from the store", alert["alert"]["unfulfilled_requests"] > 0)

    again = request(base, "/api/restock-alerts", "POST", {"product": "Maggi"})
    check("restock alert is idempotent", again["alert_id"] == alert["alert_id"])

    check(
        "unknown product is rejected",
        status_of(base, "/api/restock-alerts", "POST", {"product": "Ferrari"}) == 404,
    )

    launched = request(
        base,
        "/api/campaigns",
        "POST",
        {
            "merchant_id": "PAYTM_M_001",
            "campaign_name": "Evening Boost",
            "cashback_amount": campaign["config"]["cashback_amount"],
            "minimum_transaction": campaign["config"]["minimum_transaction"],
            "start_time": campaign["config"]["start_time"],
            "end_time": campaign["config"]["end_time"],
        },
    )
    check("campaign launches", launched["status"] == "ACTIVE")
    check(
        "projected impact is positive",
        launched["projection"]["delta"] > 0,
        str(launched["projection"]["delta"]),
    )

    # ---- 8. dashboard shows both sources -----------------------------------
    dashboard = request(base, "/api/dashboard")
    check("dashboard carries payment intelligence", len(dashboard["what_changed"]) > 0)
    check(
        "dashboard carries shop intelligence",
        dashboard["shop_floor"]["total_requests"] > 0,
    )
    check("dashboard carries the joined narrative", len(dashboard["ai_summary"]) > 40)
    check("dashboard reflects the live campaign", dashboard["active_campaign"] is not None)
    check("dashboard reflects the restock alert", len(dashboard["open_restock_alerts"]) > 0)

    # ---- 9. AI works without a model ---------------------------------------
    answer = request(base, "/api/ask-ai", "POST", {"question": "What is out of stock?"})
    check("AI answers without an LLM", answer["provider"] == "template")
    check("the answer names the product", "Maggi" in answer["answer"])
    check(
        "the answer avoids causal claims",
        not any(p in answer["answer"].lower() for p in ["caused by", "because of"]),
    )


    # ---- 5b. buyer / seller conversation intelligence ---------------------
    exchange = request(
        base,
        "/api/shop-intelligence/text",
        "POST",
        {"transcript": "Bhaiya, Maggi hai? Nahi, Maggi khatam ho gaya."},
    )
    interaction = exchange.get("interaction", {})
    turns = interaction.get("conversation", [])

    check("conversation split into two turns", len(turns) == 2, f"got {len(turns)}")
    if len(turns) == 2:
        check("first speaker classified as buyer", turns[0]["speaker"] == "buyer")
        check("second speaker classified as seller", turns[1]["speaker"] == "seller")
        check(
            "role confidence is reported",
            all(0 < t["confidence"] <= 1 for t in turns),
        )
    check("buyer intent detected", interaction.get("buyer_intent") == "product_inquiry")
    check("seller response detected", interaction.get("seller_response") == "unavailable")
    check("outcome is unfulfilled", interaction.get("interaction_outcome") == "unfulfilled")
    check("flagged as a potential lost sale", interaction.get("potential_lost_sale") is True)
    check("no transaction is expected", interaction.get("expects_transaction") is False)

    sale = request(
        base,
        "/api/shop-intelligence/text",
        "POST",
        {"transcript": "Do packet Maggi dena. Haan deta hoon."},
    )
    sold = sale.get("interaction", {})
    check("fulfilled exchange detected", sold.get("interaction_outcome") == "fulfilled")
    check("quantity extracted", sold.get("quantity") == 2, f"got {sold.get('quantity')}")
    check("a transaction is expected", sold.get("expects_transaction") is True)
    check("fulfilled sale is not a lost sale", sold.get("potential_lost_sale") is False)

    cancelled = request(
        base,
        "/api/shop-intelligence/text",
        "POST",
        {"transcript": "Bhaiya Lays dena. Nahi chahiye, rehne do."},
    )
    check(
        "cancellation reads as abandoned",
        cancelled.get("interaction", {}).get("interaction_outcome") == "abandoned",
    )

    alternative = request(
        base,
        "/api/shop-intelligence/text",
        "POST",
        {"transcript": "Maggi hai? Maggi nahi hai, noodles le lo."},
    )
    check(
        "substitute offer reads as alternative_offered",
        alternative.get("interaction", {}).get("interaction_outcome")
        == "alternative_offered",
    )

    unclear = request(
        base, "/api/shop-intelligence/text", "POST", {"transcript": "aaj mausam accha hai"}
    )
    check(
        "unclear speech reads as uncertain, not invented",
        unclear.get("interaction", {}).get("interaction_outcome") == "uncertain",
    )

    # ---- 5c. demand fulfilment -------------------------------------------
    demand = request(base, "/api/shop-intelligence/demand")
    outcomes = demand["outcomes"]["counts"]
    check("fulfilled exchanges recorded", outcomes["fulfilled"] > 0)
    check("unfulfilled exchanges recorded", outcomes["unfulfilled"] > 0)
    check(
        "fulfilment rate computed",
        demand["outcomes"]["fulfillment_rate"] is not None,
    )

    interactions = request(base, "/api/shop-intelligence/interactions?limit=5")
    check("interactions are retrievable", len(interactions["interactions"]) > 0)
    check(
        "each interaction carries its conversation",
        all(i.get("conversation") for i in interactions["interactions"]),
    )

    # ---- 5d. transaction correlation --------------------------------------
    correlation = request(base, "/api/transaction-correlation")
    check("correlation runs", "results" in correlation)
    statuses = {r["transaction_status"] for r in correlation["results"]}
    check(
        "never claims confirmed without line-item data",
        "confirmed" not in statuses,
        "the dataset has no SKUs, so confirmation is impossible",
    )
    check(
        "correlation states its data limitation",
        bool(correlation["method"].get("limitation")),
    )

    # ---- 5e. root cause analysis ------------------------------------------
    rca = request(base, "/api/root-cause-analysis")
    check("direct evidence found", len(rca["direct_evidence"]) > 0)
    check("contributing factors found", len(rca["possible_contributing_factors"]) > 0)
    check(
        "direct evidence and factors are separate keys",
        "direct_evidence" in rca and "possible_contributing_factors" in rca,
    )
    check(
        "direct evidence outranks correlation on confidence",
        min(c["confidence"] for c in rca["direct_evidence"])
        > max(f["confidence"] for f in rca["possible_contributing_factors"]),
    )
    total = sum(r["points_contributed"] for r in rca["score_attribution"])
    check(
        "score attribution sums to the actual change",
        abs(total - rca["score"]["change"]) < 1.0,
        f"attribution {total:.2f} vs change {rca['score']['change']}",
    )
    rca_text = " ".join(
        [rca["narrative"]]
        + [f["detail"] + " " + f["correlation_note"] for f in rca["possible_contributing_factors"]]
    ).lower()
    banned_rca = [p for p in ["caused by", "because of", "as a result of", "proves"] if p in rca_text]
    check("root cause avoids causal language", not banned_rca, f"found: {banned_rca}")

    # ---- 5f. the merchant copilot -----------------------------------------
    ask = request(base, "/api/ai/ask", "POST", {"question": "Why did my score drop?"})
    check("copilot answers", len(ask["answer"]) > 40)
    check("copilot returns evidence", len(ask["evidence"]) > 0)
    check(
        "evidence is tagged observed vs contributing",
        {e["evidence_type"] for e in ask["evidence"]} <= {"observed", "possible_contributing_factor"},
    )
    check("copilot works with no LLM key", ask["provider"] == "template")

    # ---- 5g. provider fallbacks -------------------------------------------
    health2 = request(base, "/health")
    check(
        "missing Sarvam key does not crash",
        health2["ai_provider"]["provider"] in {"template", "sarvam"},
    )
    check(
        "transcription resolves a provider",
        health2["transcription"]["active"] in {"sarvam", "whisper", "mock", "none"},
    )
    check(
        "Paytm data source is declared as mock",
        health2["paytm_data"]["provider"] == "mock-csv"
        and health2["paytm_data"]["is_live"] is False,
    )
    check(
        "no SKU-level capability is claimed",
        health2["paytm_data"]["capabilities"]["line_item_detail"] is False,
    )

    # ---- 10. tidy up --------------------------------------------------------
    request(base, "/api/demo/reset", "POST")
    check("state resets cleanly", request(base, "/api/dashboard")["active_campaign"] is None)

    # ---- report -------------------------------------------------------------
    failed = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 62)
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("\n  Failures:")
        for _, name, detail in failed:
            print(f"    - {name}" + (f"  ({detail})" if detail else ""))
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
