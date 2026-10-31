"""Persistent state for the WhatsApp bridge v2.

Everything the bridge must not lose on restart lives in the shared bot
DB (db.core.connect, BOT_DB_PATH-aware):

- wa_bridge_state: Batcher snapshot per sender (open batches survive).
- wa_pending: flushed batches awaiting the broker's button decision
  ('save' = confirm card, 'supp' = supplement question), with the
  1-hour reminder flag for save cards.
- wa_outbox: failed saves, retried with backoff by the tick loop.
- wa_batch_listing: batch_id -> listing_id for supplement merges and
  the HUY-undo "latest save" lookup.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from db.core import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wa_bridge_state (
    sender TEXT PRIMARY KEY, snap TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS wa_pending (
    batch_id INTEGER PRIMARY KEY, sender TEXT, kind TEXT,
    payload TEXT, created REAL, reminded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS wa_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, payload TEXT,
    attempts INTEGER DEFAULT 0, next_at REAL, created REAL);
CREATE TABLE IF NOT EXISTS wa_batch_listing (
    sender TEXT, batch_id INTEGER, listing_id TEXT, saved_at REAL,
    PRIMARY KEY (sender, batch_id));
"""


def _conn() -> sqlite3.Connection:
    conn = connect()
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------- batcher snap

def load_snapshot(sender: str) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT snap FROM wa_bridge_state WHERE sender = ?",
            (sender,)).fetchone()
        return json.loads(row[0]) if row else None


def load_all_snapshots() -> dict:
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT sender, snap FROM wa_bridge_state").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}


def save_snapshot(sender: str, snap: dict, now: float):
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO wa_bridge_state (sender, snap, updated) VALUES (?, ?, ?)"
            " ON CONFLICT(sender) DO UPDATE SET snap = excluded.snap,"
            " updated = excluded.updated",
            (sender, json.dumps(snap, ensure_ascii=False), now))
        conn.commit()


# ---------------------------------------------------------- pending

def put_pending(batch_id: int, sender: str, kind: str, payload: dict,
                now: float):
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wa_pending"
            " (batch_id, sender, kind, payload, created, reminded)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            (batch_id, sender, kind, json.dumps(payload, ensure_ascii=False),
             now))
        conn.commit()


def get_pending(batch_id: int) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT batch_id, sender, kind, payload, created, reminded"
            " FROM wa_pending WHERE batch_id = ?", (batch_id,)).fetchone()
        if not row:
            return None
        return {"batch_id": row[0], "sender": row[1], "kind": row[2],
                "payload": json.loads(row[3]), "created": row[4],
                "reminded": row[5]}


def pop_pending(batch_id: int) -> dict | None:
    p = get_pending(batch_id)
    if p:
        with closing(_conn()) as conn:
            conn.execute("DELETE FROM wa_pending WHERE batch_id = ?",
                         (batch_id,))
            conn.commit()
    return p


def list_pending() -> list:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT batch_id, sender, kind, payload, created, reminded"
            " FROM wa_pending").fetchall()
        return [{"batch_id": r[0], "sender": r[1], "kind": r[2],
                 "payload": json.loads(r[3]), "created": r[4],
                 "reminded": r[5]} for r in rows]


def mark_reminded(batch_id: int):
    with closing(_conn()) as conn:
        conn.execute("UPDATE wa_pending SET reminded = 1 WHERE batch_id = ?",
                     (batch_id,))
        conn.commit()


# ---------------------------------------------------------- outbox

def enqueue_outbox(sender: str, payload: dict, now: float, delay: float = 60.0):
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO wa_outbox (sender, payload, attempts, next_at, created)"
            " VALUES (?, ?, 0, ?, ?)",
            (sender, json.dumps(payload, ensure_ascii=False), now + delay, now))
        conn.commit()


def due_outbox(now: float) -> list:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT id, sender, payload, attempts FROM wa_outbox"
            " WHERE next_at <= ?", (now,)).fetchall()
        return [{"id": r[0], "sender": r[1], "payload": json.loads(r[2]),
                 "attempts": r[3]} for r in rows]


def update_outbox(row_id: int, attempts: int, next_at: float):
    with closing(_conn()) as conn:
        conn.execute(
            "UPDATE wa_outbox SET attempts = ?, next_at = ? WHERE id = ?",
            (attempts, next_at, row_id))
        conn.commit()


def delete_outbox(row_id: int):
    with closing(_conn()) as conn:
        conn.execute("DELETE FROM wa_outbox WHERE id = ?", (row_id,))
        conn.commit()


# ---------------------------------------------------------- batch->listing

def record_listing(sender: str, batch_id: int, listing_id: str, now: float):
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wa_batch_listing"
            " (sender, batch_id, listing_id, saved_at) VALUES (?, ?, ?, ?)",
            (sender, batch_id, listing_id, now))
        conn.commit()


def listing_for_batch(sender: str, batch_id: int) -> str | None:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT listing_id FROM wa_batch_listing"
            " WHERE sender = ? AND batch_id = ?",
            (sender, batch_id)).fetchone()
        return row[0] if row else None


def last_save(sender: str):
    """(listing_id, saved_at) of the sender's most recent bridge save."""
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT listing_id, saved_at FROM wa_batch_listing"
            " WHERE sender = ? ORDER BY saved_at DESC LIMIT 1",
            (sender,)).fetchone()
        return (row[0], row[1]) if row else None
