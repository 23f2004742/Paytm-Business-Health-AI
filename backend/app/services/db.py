"""
SQLite storage for everything a merchant action changes.

Why a database now
------------------------------------------------------------------------------
The JSON stores were the right call for a demo: no schema, no server, easy to
read by eye. They stop being the right call the moment two things are true at
once, and both now are.

  1. Concurrent writers. The Pi posts events, the browser posts voice
     commands, and a merchant action fires from a route. Every JSON store used
     read-modify-write under a process-local lock, which is not a lock at all
     across two uvicorn workers: the last writer wins and an udhaar payment
     silently disappears.

  2. Money. A dropped restock alert is an inconvenience. A dropped khata
     repayment is a merchant arguing with a customer about ₹500.

SQLite fixes both without adding a service to run or a package to install: it
is in the standard library, the whole database is one file next to the data it
replaces, and a transaction is a real transaction.

------------------------------------------------------------------------------
Design
------------------------------------------------------------------------------
* A connection per operation rather than one shared handle. SQLite connections
  are not safe to share across threads and FastAPI is threaded; opening one is
  measured in microseconds.
* WAL mode, so a reader never blocks on the writer. That matters here because
  the dashboard polls while the box is writing.
* Existing JSON files are imported once on first run and then left alone, so
  upgrading an installation loses nothing and the old files stay readable.

The service modules keep their existing function signatures. Nothing above
this layer knows the storage changed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "munim.db"

_init_lock = threading.Lock()
_initialised = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS khata_customers (
    customer_id      TEXT PRIMARY KEY,
    name             TEXT    NOT NULL,
    balance          REAL    NOT NULL DEFAULT 0,
    -- Chasing a debt needs somewhere to send the reminder and a language to
    -- write it in. Both are per customer: a shop's customers do not all read
    -- the same script.
    phone            TEXT,
    language         TEXT    NOT NULL DEFAULT 'hinglish',
    last_reminded_at TEXT,
    reminder_count   INTEGER NOT NULL DEFAULT 0
);

-- One row per reminder actually sent, so the shop can see what was chased,
-- when, and what it said. A merchant who cannot show the customer the exact
-- message they were sent has no answer when the customer denies getting one.
CREATE TABLE IF NOT EXISTS reminders (
    reminder_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    amount      REAL NOT NULL,
    channel     TEXT NOT NULL,
    message     TEXT NOT NULL,
    pay_link    TEXT,
    delivered   INTEGER NOT NULL DEFAULT 0,
    detail      TEXT,
    sent_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_customer ON reminders(customer_id, sent_at DESC);

CREATE TABLE IF NOT EXISTS expenses (
    expense_id  TEXT PRIMARY KEY,
    merchant_id TEXT    NOT NULL,
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL,
    payee       TEXT,
    transcript  TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    recorded_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_merchant ON expenses(merchant_id, recorded_at DESC);

-- The activity feed is genuinely heterogeneous: a khata update, an expense and
-- a product request share almost no fields. The queryable parts are columns;
-- the rest stays JSON rather than pretending to a schema it does not have.
CREATE TABLE IF NOT EXISTS activity (
    event_id   TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_time ON activity(timestamp DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS restock_alerts (
    alert_id    TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    product     TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_restock_open ON restock_alerts(merchant_id, status);

CREATE TABLE IF NOT EXISTS device_status (
    device_id TEXT PRIMARY KEY,
    status    TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """
    One connection, one transaction, always closed.

    Commits on a clean exit and rolls back on any exception, so a half-applied
    khata update cannot survive an error.
    """
    ensure_ready()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """
    A connection that holds the write lock for the WHOLE block.

    `connect()` is deferred: it takes the write lock only at the first write,
    so a read-modify-write done through it is still a lost-update race. Two
    repayments both read a balance of 500, both compute 490, and one of them
    vanishes.

    BEGIN IMMEDIATE takes the lock up front, so a concurrent writer waits
    (up to `timeout`) instead of reading stale state. Use this for anything
    that reads a value and then writes a value derived from it; use
    `connect()` for plain reads and independent inserts, which do not need to
    block the dashboard.
    """
    ensure_ready()
    conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def ensure_ready() -> None:
    """Create the schema once per process, and import any legacy JSON."""
    global _initialised
    if _initialised:
        return
    with _init_lock:
        if _initialised:
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        try:
            # WAL lets the dashboard read while the box is writing.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA)
            _add_missing_columns(conn)
            conn.commit()
        finally:
            conn.close()
        _initialised = True
        _import_legacy_json()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """
    Columns added after a database was first created.

    `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so new
    columns never appear on an installation that has been running: the schema
    above only describes a fresh database. Each column is added if absent,
    which is idempotent and cheap, and leaves existing rows at the default.
    """
    additions = (
        ("khata_customers", "phone", "TEXT"),
        ("khata_customers", "language", "TEXT NOT NULL DEFAULT 'hinglish'"),
        ("khata_customers", "last_reminded_at", "TEXT"),
        ("khata_customers", "reminder_count", "INTEGER NOT NULL DEFAULT 0"),
    )
    for table, column, decl in additions:
        # Indexed positionally: this runs on the bootstrap connection, which
        # has no row_factory, so rows come back as plain tuples. PRAGMA
        # table_info puts the column name at index 1.
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def unpack(row: sqlite3.Row | None) -> dict | None:
    """A payload row back to the dict the services already expect."""
    if row is None:
        return None
    return json.loads(row["payload"])


def pack(value: Any) -> str:
    return json.dumps(value)


# --------------------------------------------------------------- migration

def _read_json(path: Path, fallback: Any) -> Any:
    try:
        if not path.exists():
            return fallback
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(fallback)) else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def _import_legacy_json() -> None:
    """
    Bring the old JSON stores in, once.

    Only ever runs against an empty table, so re-running is harmless and a
    merchant who upgrades mid-week keeps their udhaar book. The JSON files are
    left on disk untouched: this is a copy, not a move, so a bad import can be
    walked back by deleting munim.db.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        def empty(table: str) -> bool:
            return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0

        if empty("khata_customers"):
            for row in _read_json(DATA_DIR / "khata.json", []):
                conn.execute(
                    "INSERT OR IGNORE INTO khata_customers(customer_id, name, balance)"
                    " VALUES(?,?,?)",
                    (row.get("customer_id"), row.get("name"), float(row.get("balance", 0) or 0)),
                )

        if empty("expenses"):
            for row in _read_json(DATA_DIR / "expenses.json", []):
                conn.execute(
                    "INSERT OR IGNORE INTO expenses(expense_id, merchant_id, amount,"
                    " category, payee, transcript, source, recorded_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (
                        row.get("expense_id"), row.get("merchant_id"),
                        float(row.get("amount", 0) or 0), row.get("category", "other"),
                        row.get("payee"), row.get("transcript", ""),
                        row.get("source", "voice"), row.get("recorded_at", ""),
                    ),
                )

        if empty("activity"):
            for row in _read_json(DATA_DIR / "business_activity.json", []):
                if row.get("event_id"):
                    conn.execute(
                        "INSERT OR IGNORE INTO activity(event_id, event_type, timestamp, payload)"
                        " VALUES(?,?,?,?)",
                        (row["event_id"], row.get("event_type", "UNKNOWN"),
                         row.get("timestamp", ""), json.dumps(row)),
                    )

        if empty("campaigns"):
            for row in _read_json(DATA_DIR / "campaigns.json", []):
                if row.get("campaign_id"):
                    conn.execute(
                        "INSERT OR IGNORE INTO campaigns(campaign_id, merchant_id, status,"
                        " created_at, payload) VALUES(?,?,?,?,?)",
                        (row["campaign_id"], row.get("merchant_id", ""),
                         row.get("status", "ACTIVE"), row.get("created_at", ""),
                         json.dumps(row)),
                    )

        if empty("restock_alerts"):
            for row in _read_json(DATA_DIR / "restock_alerts.json", []):
                if row.get("alert_id"):
                    conn.execute(
                        "INSERT OR IGNORE INTO restock_alerts(alert_id, merchant_id, product,"
                        " status, created_at, payload) VALUES(?,?,?,?,?,?)",
                        (row["alert_id"], row.get("merchant_id", ""), row.get("product", ""),
                         row.get("status", "OPEN"), row.get("created_at", ""),
                         json.dumps(row)),
                    )

        if empty("device_status"):
            for device_id, status in _read_json(DATA_DIR / "device_status.json", {}).items():
                conn.execute(
                    "INSERT OR IGNORE INTO device_status(device_id, status) VALUES(?,?)",
                    (device_id, status),
                )

        conn.commit()
    finally:
        conn.close()
