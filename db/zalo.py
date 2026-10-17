"""Zalo bridge: pairing codes + zalo_id -> telegram_id mapping."""
from __future__ import annotations
import secrets
import time
from .core import connect

PAIRING_TTL_SEC = 15 * 60  # 15 minutes


def init_zalo_tables(path=None) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS zalo_links (
                zalo_id TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                zalo_name TEXT DEFAULT '',
                linked_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS zalo_pairing_codes (
                code TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _gen_code() -> str:
    # ZN-XXXXXX, unambiguous chars (no 0/O, 1/I)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "ZN-" + "".join(secrets.choice(alphabet) for _ in range(6))


def create_pairing_code(telegram_id: int, path=None) -> str:
    """Generate a single-use pairing code for a Telegram user. Returns the code."""
    init_zalo_tables(path)
    conn = connect(path)
    try:
        now = int(time.time())
        # invalidate old unused codes for this user
        conn.execute(
            "UPDATE zalo_pairing_codes SET used = 1 WHERE telegram_id = ? AND used = 0",
            (telegram_id,),
        )
        code = _gen_code()
        conn.execute(
            "INSERT INTO zalo_pairing_codes (code, telegram_id, created_at, expires_at, used)"
            " VALUES (?, ?, ?, ?, 0)",
            (code, telegram_id, now, now + PAIRING_TTL_SEC),
        )
        conn.commit()
        return code
    finally:
        conn.close()


def redeem_pairing_code(code: str, zalo_id: str, zalo_name: str = "", path=None) -> dict:
    """Redeem a pairing code. Returns {ok, telegram_id} or {ok: False, error}."""
    init_zalo_tables(path)
    code = (code or "").strip().upper()
    conn = connect(path)
    try:
        now = int(time.time())
        row = conn.execute(
            "SELECT code, telegram_id, expires_at, used FROM zalo_pairing_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        if row["used"]:
            return {"ok": False, "error": "used"}
        if row["expires_at"] < now:
            return {"ok": False, "error": "expired"}
        telegram_id = row["telegram_id"]
        conn.execute("UPDATE zalo_pairing_codes SET used = 1 WHERE code = ?", (code,))
        conn.execute(
            "INSERT OR REPLACE INTO zalo_links (zalo_id, telegram_id, zalo_name, linked_at)"
            " VALUES (?, ?, ?, ?)",
            (zalo_id, telegram_id, zalo_name or "", now),
        )
        conn.commit()
        return {"ok": True, "telegram_id": telegram_id}
    finally:
        conn.close()


def get_telegram_id(zalo_id: str, path=None):
    """Look up linked Telegram user id for a Zalo sender id. None if not linked."""
    init_zalo_tables(path)
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT telegram_id FROM zalo_links WHERE zalo_id = ?", (zalo_id,)
        ).fetchone()
        return row["telegram_id"] if row else None
    finally:
        conn.close()


def unlink_zalo(zalo_id: str, path=None) -> bool:
    init_zalo_tables(path)
    conn = connect(path)
    try:
        cur = conn.execute("DELETE FROM zalo_links WHERE zalo_id = ?", (zalo_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
