"""
Deterministic synthetic transaction generator for Paytm Business Health AI.

Produces ~150 days of realistic F&B merchant transactions for "Raj's Tea & Snacks"
with intentional, demo-stable patterns.

  Baseline (healthy):
    - Morning tea rush (8-10 AM), lunch peak (12-2 PM), evening peak (6-9 PM)
    - Afternoon lull (3-5 PM) -> the untapped-window opportunity
    - Stronger weekends, weaker Tuesdays
    - Long-tail repeat-customer distribution

  Recent 7 days (the demo story):
    - Evening (6-9 PM) transactions down ~30%
    - Repeat-customer transactions down ~14%
    - The most recent Tuesday's revenue down ~31%
    - Weekend revenue up ~9%          (positive counterweight)
    - Average transaction value up    (positive counterweight)

Design note: each effect draws from its own RNG stream, and the evening slump
removes an exact count rather than sampling per transaction. That keeps the
knobs in KNOBS independently tunable: changing one does not reshuffle the
others, which is what makes the demo numbers reproducible.

Run:  python generate_data.py
Out:  transactions.csv + meta.json (meta carries the as_of anchor date)
"""

from __future__ import annotations

import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 20260821
MERCHANT_ID = "PAYTM_M_001"
MERCHANT_NAME = "Raj's Tea & Snacks"
CATEGORY = "Food & Beverage"
LOCATION = "Hyderabad, Telangana"

DAYS = 150
OPEN_HOUR, CLOSE_HOUR = 8, 22

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------- knobs
# The five levers that shape the recent-7-day story. Each is independent.
KNOBS = {
    "evening_drop": 0.38,      # share of 6-9 PM transactions removed
    "weekend_boost": 1.22,     # weekend volume multiplier
    "tuesday_factor": 0.84,    # volume multiplier on the weak Tuesday
    "repeat_factor": 0.82,     # repeat-customer propensity multiplier
    "ticket_lift": 1.055,       # average basket multiplier
}

# Allow a tuning sweep to override any knob without editing this file:
#   PBH_EVENING_DROP=0.37 python generate_data.py
for _k in list(KNOBS):
    _env = os.environ.get(f"PBH_{_k.upper()}")
    if _env:
        KNOBS[_k] = float(_env)

# ------------------------------------------------------------- shape curves

HOUR_WEIGHTS = {
    8: 0.85, 9: 0.95, 10: 0.70, 11: 0.55,
    12: 1.15, 13: 1.30, 14: 0.85,
    15: 0.40, 16: 0.45, 17: 0.70,   # afternoon lull -> opportunity window
    18: 1.20, 19: 1.45, 20: 1.30,   # evening peak   -> the anomaly window
    21: 0.80,
}

# Monday = 0 ... Sunday = 6
DOW_MULTIPLIER = {0: 0.95, 1: 0.90, 2: 0.98, 3: 1.00, 4: 1.12, 5: 1.28, 6: 1.20}

# (name, min amount, max amount, weight). Kept tight so the daily average
# ticket is stable; a fat tail here would drown the real trend in noise.
ITEM_MIX = [
    ("Tea & Beverages", 50, 140, 0.36),
    ("Snacks", 130, 320, 0.32),
    ("Meals & Combos", 360, 820, 0.23),
    ("Desserts", 150, 300, 0.07),
    ("Bulk / Party Order", 900, 1500, 0.02),
]

PAYMENT_METHODS = [
    ("UPI", 0.62), ("Paytm Wallet", 0.18), ("Card", 0.12),
    ("Paytm Postpaid", 0.05), ("Cash", 0.03),
]

EVENING = (18, 20)  # inclusive hour buckets => 6 PM - 9 PM


def weighted_choice(rng: random.Random, options):
    """options: tuples whose LAST element is the weight."""
    total = sum(o[-1] for o in options)
    r = rng.random() * total
    upto = 0.0
    for opt in options:
        upto += opt[-1]
        if r <= upto:
            return opt
    return options[-1]


def build_customer_pool(rng: random.Random):
    """
    Long-tail loyalty curve:
      120 regulars (very frequent), 380 occasionals, 900 rare walk-ins.
    Returns (ids, cumulative_weights, total_weight) for O(log n) sampling.
    """
    ids, weights = [], []
    for i in range(120):
        ids.append(f"CUST_R{i:04d}")
        weights.append(rng.uniform(14.0, 26.0))
    for i in range(380):
        ids.append(f"CUST_O{i:04d}")
        weights.append(rng.uniform(3.0, 7.0))
    for i in range(900):
        ids.append(f"CUST_W{i:04d}")
        weights.append(rng.uniform(0.4, 1.2))

    cumulative, running = [], 0.0
    for w in weights:
        running += w
        cumulative.append(running)
    return ids, cumulative, running


def main() -> None:
    # Independent streams so tuning one knob does not perturb the others.
    rng_pool = random.Random(SEED)
    rng_volume = random.Random(SEED + 1)
    rng_txn = random.Random(SEED + 2)
    rng_drop = random.Random(SEED + 3)
    rng_cust = random.Random(SEED + 4)

    as_of = date.today()
    start = as_of - timedelta(days=DAYS - 1)
    recent_start = as_of - timedelta(days=6)  # last 7 days, inclusive of today

    weak_tuesday = next(
        (as_of - timedelta(days=o) for o in range(7)
         if (as_of - timedelta(days=o)).weekday() == 1),
        None,
    )

    cust_ids, cum_weights, total_weight = build_customer_pool(rng_pool)

    def pick_repeat_customer() -> str:
        r = rng_cust.random() * total_weight
        lo, hi = 0, len(cum_weights) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum_weights[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        return cust_ids[lo]

    rows: list[dict] = []
    txn_counter = 0
    new_customer_counter = 0
    have_history = False

    hour_options = list(HOUR_WEIGHTS.items())

    for day_index in range(DAYS):
        day = start + timedelta(days=day_index)
        dow = day.weekday()
        is_recent = day >= recent_start
        is_weekend = dow >= 5

        # ---- how many transactions today ---------------------------------
        trend = 1.0 + 0.06 * (day_index / max(DAYS - 1, 1))   # +6% end to end
        weekend_boost = KNOBS["weekend_boost"] if (is_weekend and is_recent) else 1.0
        noise = rng_volume.gauss(1.0, 0.06)

        day_txns = 108 * DOW_MULTIPLIER[dow] * trend * weekend_boost * noise
        day_txns = max(35, int(round(day_txns)))

        if weak_tuesday is not None and day == weak_tuesday:
            day_txns = int(round(day_txns * KNOBS["tuesday_factor"]))

        # ---- average basket ----------------------------------------------
        aov_factor = 1.0 + 0.05 * (day_index / max(DAYS - 1, 1))
        if is_recent:
            aov_factor *= KNOBS["ticket_lift"]

        # ---- build the day's candidate transactions ----------------------
        candidates = []
        for _ in range(day_txns):
            hour, _w = weighted_choice(rng_txn, hour_options)
            item, lo, hi, _p = weighted_choice(rng_txn, ITEM_MIX)

            amount = rng_txn.uniform(lo, hi) * aov_factor
            if EVENING[0] <= hour <= 21:
                amount *= 1.12          # dinner / family baskets run larger

            candidates.append(
                {
                    "hour": hour,
                    "minute": rng_txn.randrange(60),
                    "second": rng_txn.randrange(60),
                    "amount": round(amount, 2),
                    "category": item,
                    "method": weighted_choice(rng_txn, PAYMENT_METHODS)[0],
                    "status": "FAILED" if rng_txn.random() < 0.018 else "SUCCESS",
                }
            )

        # ---- the evening slump: remove an exact count --------------------
        if is_recent:
            evening_idx = [
                i for i, c in enumerate(candidates)
                if EVENING[0] <= c["hour"] <= EVENING[1]
            ]
            n_drop = int(round(len(evening_idx) * KNOBS["evening_drop"]))
            if n_drop:
                dropped = set(rng_drop.sample(evening_idx, n_drop))
                candidates = [c for i, c in enumerate(candidates) if i not in dropped]

        # ---- assign customers --------------------------------------------
        repeat_prob = 0.46 * (KNOBS["repeat_factor"] if is_recent else 1.0)

        for c in candidates:
            if have_history and rng_cust.random() < repeat_prob:
                customer_id = pick_repeat_customer()
            else:
                customer_id = f"CUST_N{new_customer_counter:05d}"
                new_customer_counter += 1

            ts = datetime(day.year, day.month, day.day, c["hour"], c["minute"], c["second"])
            txn_counter += 1
            rows.append(
                {
                    "transaction_id": f"TXN{txn_counter:07d}",
                    "merchant_id": MERCHANT_ID,
                    "timestamp": ts.isoformat(sep=" "),
                    "amount": f"{c['amount']:.2f}",
                    "customer_id": customer_id,
                    "payment_method": c["method"],
                    "status": c["status"],
                    "category": c["category"],
                    "campaign_id": "",
                }
            )
        have_history = True

    rows.sort(key=lambda r: r["timestamp"])

    out_csv = HERE / "transactions.csv"
    header = list(rows[0].keys())
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(str(r[k]) for k in header) + "\n")

    meta = {
        "merchant_id": MERCHANT_ID,
        "merchant_name": MERCHANT_NAME,
        "category": CATEGORY,
        "location": LOCATION,
        "owner_name": "Raj",
        "as_of_date": as_of.isoformat(),
        "start_date": start.isoformat(),
        "days": DAYS,
        "business_hours": f"{OPEN_HOUR}:00 - {CLOSE_HOUR}:00",
        "transaction_count": len(rows),
        "weak_tuesday": weak_tuesday.isoformat() if weak_tuesday else None,
        "seed": SEED,
        "knobs": KNOBS,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (HERE / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {len(rows):,} transactions -> {out_csv}")
    print(f"Window: {start} .. {as_of}   weak Tuesday: {weak_tuesday}")


if __name__ == "__main__":
    main()
