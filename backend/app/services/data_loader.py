"""Loads the merchant transaction dataset once and caches it in memory."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CSV_PATH = DATA_DIR / "transactions.csv"
META_PATH = DATA_DIR / "meta.json"


class DatasetMissingError(RuntimeError):
    """Raised when the dataset has not been generated yet."""


@lru_cache(maxsize=1)
def load_meta() -> dict:
    if not META_PATH.exists():
        raise DatasetMissingError(
            "meta.json not found. Run: python data/generate_data.py"
        )
    return json.loads(META_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_transactions() -> pd.DataFrame:
    """Successful transactions only, enriched with time-part columns."""
    if not CSV_PATH.exists():
        raise DatasetMissingError(
            "transactions.csv not found. Run: python data/generate_data.py"
        )

    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df = df[df["status"] == "SUCCESS"].copy()

    df["date"] = df["timestamp"].dt.normalize()
    df["hour"] = df["timestamp"].dt.hour
    df["dow"] = df["timestamp"].dt.dayofweek          # Monday = 0
    df["is_weekend"] = df["dow"] >= 5
    return df.reset_index(drop=True)


def as_of_timestamp() -> pd.Timestamp:
    """The dataset's 'today'. Analytics are anchored here, not on wall-clock."""
    return pd.Timestamp(load_meta()["as_of_date"]).normalize()


def reset_cache() -> None:
    load_meta.cache_clear()
    load_transactions.cache_clear()
