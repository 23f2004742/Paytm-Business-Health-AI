"""
Analytics engine.

Everything the product says about the business is computed here, from the
transaction data. Nothing is hard-coded and nothing is model-generated.

Vocabulary used throughout:
  anchor          the 'today' the analysis is run against (dataset as_of date)
  current window  the 7 days ending on the anchor (inclusive)
  previous window the 7 days immediately before the current window
  baseline        the 28 days before the current window (the 'normal' period)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .data_loader import as_of_timestamp, load_transactions

WINDOW_DAYS = 7
BASELINE_DAYS = 28

EVENING_HOURS = (18, 20)     # 6 PM - 9 PM (the 20:xx hour ends at 9 PM)
AFTERNOON_HOURS = (15, 17)   # 3 PM - 6 PM lull

DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _pct_change(current: float, previous: float) -> float:
    """Percent change, guarding divide-by-zero. Returns 0.0 when no baseline."""
    if previous is None or previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100.0, 1)


def _safe_div(a: float, b: float) -> float:
    return (a / b) if b else 0.0


def _hour_label(hour: int) -> str:
    hour = hour % 24
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12
    if display == 0:
        display = 12
    return f"{display} {suffix}"


def hour_range_label(lo: int, hi: int) -> str:
    """(18, 20) -> '6 PM - 9 PM'. `hi` is an inclusive hour bucket."""
    return f"{_hour_label(lo)} - {_hour_label(hi + 1)}"


@dataclass
class Window:
    """A slice of transactions plus the aggregates every consumer needs."""

    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    df: pd.DataFrame = field(repr=False)

    @property
    def days(self) -> int:
        return int((self.end - self.start).days) + 1

    @property
    def revenue(self) -> float:
        return float(self.df["amount"].sum())

    @property
    def txns(self) -> int:
        return int(len(self.df))

    @property
    def avg_ticket(self) -> float:
        return float(_safe_div(self.revenue, self.txns))

    @property
    def revenue_per_day(self) -> float:
        return float(_safe_div(self.revenue, self.days))

    @property
    def txns_per_day(self) -> float:
        return float(_safe_div(self.txns, self.days))

    @property
    def unique_customers(self) -> int:
        return int(self.df["customer_id"].nunique())

    def hour_txns(self, lo: int, hi: int) -> int:
        return int(len(self.df[(self.df["hour"] >= lo) & (self.df["hour"] <= hi)]))

    def hour_revenue(self, lo: int, hi: int) -> float:
        mask = (self.df["hour"] >= lo) & (self.df["hour"] <= hi)
        return float(self.df.loc[mask, "amount"].sum())

    def daily_revenue(self) -> pd.Series:
        """Revenue per calendar day, zero-filled across the full window."""
        idx = pd.date_range(self.start, self.end, freq="D")
        return self.df.groupby("date")["amount"].sum().reindex(idx, fill_value=0.0)

    def daily_txns(self) -> pd.Series:
        idx = pd.date_range(self.start, self.end, freq="D")
        return self.df.groupby("date").size().reindex(idx, fill_value=0)


def slice_window(df: pd.DataFrame, end: pd.Timestamp, days: int, label: str) -> Window:
    start = end - pd.Timedelta(days=days - 1)
    mask = (df["date"] >= start) & (df["date"] <= end)
    return Window(label=label, start=start, end=end, df=df.loc[mask].copy())


@dataclass
class AnalyticsContext:
    """Every metric the scoring, anomaly, insight and AI layers read from."""

    anchor: pd.Timestamp
    current: Window
    previous: Window
    baseline: Window
    full: pd.DataFrame = field(repr=False)

    # ---------------------------------------------------------------- revenue
    @property
    def revenue_growth_wow(self) -> float:
        return _pct_change(self.current.revenue, self.previous.revenue)

    @property
    def revenue_vs_baseline(self) -> float:
        return _pct_change(self.current.revenue_per_day, self.baseline.revenue_per_day)

    @property
    def txn_growth_wow(self) -> float:
        return _pct_change(self.current.txns, self.previous.txns)

    @property
    def txn_vs_baseline(self) -> float:
        return _pct_change(self.current.txns_per_day, self.baseline.txns_per_day)

    @property
    def avg_ticket_growth(self) -> float:
        return _pct_change(self.current.avg_ticket, self.previous.avg_ticket)

    @property
    def avg_ticket_vs_baseline(self) -> float:
        return _pct_change(self.current.avg_ticket, self.baseline.avg_ticket)

    # --------------------------------------------------------------- customers
    def _repeat_stats(self, window: Window) -> dict:
        """
        A customer counts as 'repeat' in a window if they also transacted at
        some point before that window started.
        """
        prior_ids = set(self.full.loc[self.full["date"] < window.start, "customer_id"].unique())

        ids = window.df["customer_id"]
        repeat_mask = ids.isin(prior_ids)

        repeat_txns = int(repeat_mask.sum())
        total_customers = int(ids.nunique())

        return {
            "repeat_txns": repeat_txns,
            "repeat_customers": int(ids[repeat_mask].nunique()),
            "new_customers": int(ids[~repeat_mask].nunique()),
            "total_customers": total_customers,
            "repeat_txn_rate": round(_safe_div(repeat_txns, len(ids)) * 100, 1),
            "repeat_customer_rate": round(
                _safe_div(int(ids[repeat_mask].nunique()), total_customers) * 100, 1
            ),
            "repeat_revenue": float(window.df.loc[repeat_mask, "amount"].sum()),
        }

    @property
    def customers_current(self) -> dict:
        return self._repeat_stats(self.current)

    @property
    def customers_previous(self) -> dict:
        return self._repeat_stats(self.previous)

    @property
    def repeat_txn_change(self) -> float:
        return _pct_change(
            self.customers_current["repeat_txns"], self.customers_previous["repeat_txns"]
        )

    @property
    def new_customer_change(self) -> float:
        return _pct_change(
            self.customers_current["new_customers"], self.customers_previous["new_customers"]
        )

    # -------------------------------------------------------------- stability
    @property
    def revenue_cv(self) -> float:
        """Coefficient of variation of daily revenue over baseline + current."""
        series = pd.concat([self.baseline.daily_revenue(), self.current.daily_revenue()])
        mean = float(series.mean())
        if mean == 0:
            return 1.0
        return float(series.std(ddof=0) / mean)

    @property
    def txn_cv(self) -> float:
        series = pd.concat([self.baseline.daily_txns(), self.current.daily_txns()])
        mean = float(series.mean())
        if mean == 0:
            return 1.0
        return float(series.std(ddof=0) / mean)

    def daily_revenue_zscores(self) -> pd.Series:
        """Z-score of each current-window day against the baseline distribution."""
        base = self.baseline.daily_revenue()
        mu, sigma = float(base.mean()), float(base.std(ddof=0))
        cur = self.current.daily_revenue()
        if sigma == 0:
            return pd.Series(0.0, index=cur.index)
        return (cur - mu) / sigma

    # ------------------------------------------------------------ time-of-day
    @property
    def evening_current_per_day(self) -> float:
        return _safe_div(self.current.hour_txns(*EVENING_HOURS), self.current.days)

    @property
    def evening_baseline_per_day(self) -> float:
        return _safe_div(self.baseline.hour_txns(*EVENING_HOURS), self.baseline.days)

    @property
    def evening_change(self) -> float:
        return _pct_change(self.evening_current_per_day, self.evening_baseline_per_day)

    @property
    def evening_revenue_gap_per_day(self) -> float:
        """Rupees/day currently being lost in the evening window vs baseline."""
        cur = _safe_div(self.current.hour_revenue(*EVENING_HOURS), self.current.days)
        base = _safe_div(self.baseline.hour_revenue(*EVENING_HOURS), self.baseline.days)
        return max(0.0, base - cur)

    @property
    def evening_avg_ticket(self) -> float:
        """Average evening basket over the baseline; sizes the campaign offer."""
        df = self.baseline.df
        mask = (df["hour"] >= EVENING_HOURS[0]) & (df["hour"] <= EVENING_HOURS[1])
        sub = df.loc[mask]
        return float(_safe_div(float(sub["amount"].sum()), len(sub)))

    def evening_share_above(self, threshold: float) -> float:
        """% of baseline evening transactions already above a rupee threshold."""
        df = self.baseline.df
        mask = (df["hour"] >= EVENING_HOURS[0]) & (df["hour"] <= EVENING_HOURS[1])
        sub = df.loc[mask]
        if not len(sub):
            return 0.0
        return round(float((sub["amount"] >= threshold).sum()) / len(sub) * 100, 1)

    def hourly_distribution(self) -> list[dict]:
        """Per-hour txn counts: current window vs baseline daily average."""
        out = []
        for hour in range(8, 22):
            cur = _safe_div(self.current.hour_txns(hour, hour), self.current.days)
            base = _safe_div(self.baseline.hour_txns(hour, hour), self.baseline.days)
            out.append(
                {
                    "hour": hour,
                    "label": _hour_label(hour),
                    "current": round(cur, 1),
                    "baseline": round(base, 1),
                    "change_percent": _pct_change(cur, base),
                }
            )
        return out

    def peak_hours(self, n: int = 3) -> list[dict]:
        dist = sorted(self.hourly_distribution(), key=lambda d: d["baseline"], reverse=True)
        return dist[:n]

    def weak_hours(self, n: int = 3) -> list[dict]:
        """Weakest mid-day trading hours by baseline volume (the opportunity)."""
        dist = [d for d in self.hourly_distribution() if 9 <= d["hour"] <= 21]
        return sorted(dist, key=lambda d: d["baseline"])[:n]

    # ---------------------------------------------------------- day-of-week
    @property
    def weekend_change(self) -> float:
        cur_days = max(1, sum(1 for d in pd.date_range(self.current.start, self.current.end)
                              if d.dayofweek >= 5))
        base_days = max(1, sum(1 for d in pd.date_range(self.baseline.start, self.baseline.end)
                               if d.dayofweek >= 5))
        cur = self.current.df.loc[self.current.df["is_weekend"], "amount"].sum()
        base = self.baseline.df.loc[self.baseline.df["is_weekend"], "amount"].sum()
        return _pct_change(_safe_div(float(cur), cur_days), _safe_div(float(base), base_days))

    def weekday_comparison(self) -> list[dict]:
        """Each day in the current window vs that weekday's historical average."""
        out = []
        hist = self.full[self.full["date"] < self.current.start]
        for day in pd.date_range(self.current.start, self.current.end):
            dow = int(day.dayofweek)
            day_rev = float(self.full.loc[self.full["date"] == day, "amount"].sum())

            per_day = hist.loc[hist["dow"] == dow].groupby("date")["amount"].sum()
            hist_avg = float(per_day.mean()) if len(per_day) else 0.0

            out.append(
                {
                    "date": day.date().isoformat(),
                    "day": DOW_NAMES[dow],
                    "revenue": round(day_rev, 2),
                    "historical_average": round(hist_avg, 2),
                    "change_percent": _pct_change(day_rev, hist_avg),
                }
            )
        return out

    def revenue_trend(self, days: int = 30) -> list[dict]:
        """Daily revenue series ending at the anchor, for the dashboard chart."""
        start = self.anchor - pd.Timedelta(days=days - 1)
        idx = pd.date_range(start, self.anchor, freq="D")
        mask = (self.full["date"] >= start) & (self.full["date"] <= self.anchor)
        sub = self.full.loc[mask]
        rev = sub.groupby("date")["amount"].sum().reindex(idx, fill_value=0.0)
        txns = sub.groupby("date").size().reindex(idx, fill_value=0)
        return [
            {
                "date": d.date().isoformat(),
                "label": d.strftime("%d %b"),
                "revenue": round(float(rev.loc[d]), 2),
                "transactions": int(txns.loc[d]),
            }
            for d in idx
        ]


def build_context(anchor: Optional[pd.Timestamp] = None) -> AnalyticsContext:
    df = load_transactions()
    anchor = (anchor if anchor is not None else as_of_timestamp()).normalize()

    current = slice_window(df, anchor, WINDOW_DAYS, "current")
    prev_end = anchor - pd.Timedelta(days=WINDOW_DAYS)
    previous = slice_window(df, prev_end, WINDOW_DAYS, "previous")
    baseline = slice_window(df, prev_end, BASELINE_DAYS, "baseline")

    return AnalyticsContext(
        anchor=anchor, current=current, previous=previous, baseline=baseline, full=df
    )


# ------------------------------------------------------------------ dashboard

def today_snapshot(ctx: AnalyticsContext) -> dict:
    """Today's numbers vs the same weekday's recent average."""
    today = ctx.anchor
    today_df = ctx.full[ctx.full["date"] == today]

    hist = ctx.full[(ctx.full["date"] < today) & (ctx.full["dow"] == int(today.dayofweek))]
    per_day_rev = hist.groupby("date")["amount"].sum()
    per_day_txn = hist.groupby("date").size()

    rev = float(today_df["amount"].sum())
    txns = int(len(today_df))
    avg = float(_safe_div(rev, txns))

    base_rev = float(per_day_rev.tail(6).mean()) if len(per_day_rev) else 0.0
    base_txn = float(per_day_txn.tail(6).mean()) if len(per_day_txn) else 0.0
    base_avg = float(_safe_div(base_rev, base_txn))

    return {
        "date": today.date().isoformat(),
        "revenue": round(rev, 2),
        "revenue_change": _pct_change(rev, base_rev),
        "transactions": txns,
        "transactions_change": _pct_change(txns, base_txn),
        "average_transaction": round(avg, 2),
        "average_transaction_change": _pct_change(avg, base_avg),
        "unique_customers": int(today_df["customer_id"].nunique()),
    }


def metrics_payload(ctx: AnalyticsContext) -> dict:
    """Full structured metric set, also the context handed to the AI layer."""
    cur_cust = ctx.customers_current
    prev_cust = ctx.customers_previous

    return {
        "period": {
            "anchor": ctx.anchor.date().isoformat(),
            "current_window": [ctx.current.start.date().isoformat(),
                               ctx.current.end.date().isoformat()],
            "previous_window": [ctx.previous.start.date().isoformat(),
                                ctx.previous.end.date().isoformat()],
            "baseline_window": [ctx.baseline.start.date().isoformat(),
                                ctx.baseline.end.date().isoformat()],
        },
        "revenue": {
            "current_week": round(ctx.current.revenue, 2),
            "previous_week": round(ctx.previous.revenue, 2),
            "growth_percent": ctx.revenue_growth_wow,
            "vs_baseline_percent": ctx.revenue_vs_baseline,
            "current_week_per_day": round(ctx.current.revenue_per_day, 2),
            "baseline_per_day": round(ctx.baseline.revenue_per_day, 2),
        },
        "transactions": {
            "current_week": ctx.current.txns,
            "previous_week": ctx.previous.txns,
            "growth_percent": ctx.txn_growth_wow,
            "vs_baseline_percent": ctx.txn_vs_baseline,
            "average_transaction_value": round(ctx.current.avg_ticket, 2),
            "average_transaction_change": ctx.avg_ticket_growth,
            "peak_hours": ctx.peak_hours(),
            "weak_hours": ctx.weak_hours(),
            "hourly_distribution": ctx.hourly_distribution(),
        },
        "customers": {
            "unique_customers": cur_cust["total_customers"],
            "repeat_customers": cur_cust["repeat_customers"],
            "new_customers": cur_cust["new_customers"],
            "repeat_customer_rate": cur_cust["repeat_customer_rate"],
            "repeat_transaction_rate": cur_cust["repeat_txn_rate"],
            "repeat_transaction_change": ctx.repeat_txn_change,
            "new_customer_change": ctx.new_customer_change,
            "previous_repeat_customers": prev_cust["repeat_customers"],
            "previous_unique_customers": prev_cust["total_customers"],
        },
        "stability": {
            "revenue_coefficient_variation": round(ctx.revenue_cv, 3),
            "transaction_coefficient_variation": round(ctx.txn_cv, 3),
            "daily_revenue_zscores": [
                {"date": d.date().isoformat(), "z": round(float(z), 2)}
                for d, z in ctx.daily_revenue_zscores().items()
            ],
        },
        "time_of_day": {
            "evening_window": hour_range_label(*EVENING_HOURS),
            "evening_current_per_day": round(ctx.evening_current_per_day, 1),
            "evening_baseline_per_day": round(ctx.evening_baseline_per_day, 1),
            "evening_change_percent": ctx.evening_change,
            "evening_revenue_gap_per_day": round(ctx.evening_revenue_gap_per_day, 2),
            "evening_average_ticket": round(ctx.evening_avg_ticket, 2),
            "afternoon_window": hour_range_label(*AFTERNOON_HOURS),
        },
        "day_of_week": {
            "weekend_change_percent": ctx.weekend_change,
            "weekday_comparison": ctx.weekday_comparison(),
        },
    }
