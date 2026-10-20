"""WhatsApp bridge: pairing codes + phone -> telegram_id mapping.

Difference from the Zalo bridge: a WhatsApp sender id IS their phone
number, so the mapping key is the (normalized) phone. Pairing still goes
through a one-time code so a phone can never be linked to someone else's
Telegram by accident.
"""
from __future__ import annotations
import re
import secrets
import time
from .core import connect

WA_PAIRING_TTL_SEC = 15 * 60  # 15 minutes


def normalize_phone(raw: str) -> str:
    """Normalize to digits-only international form.

    '0912 345 678' -> '84912345678'; '+84 912-345-678' -> '84912345678';
    '84912345678@c.us' -> '84912345678'. Non-VN numbers keep their digits.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "84" + digits[1:]
    return digits


def init_whatsapp_tables(path=None) -> None:
    conn = connect(path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wa_links (
                phone TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                wa_name TEXT DEFAULT '',
                linked_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wa_pairing_codes (
                code TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_links_tg ON wa_links(telegram_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _gen_wa_code() -> str:
    # WA-XXXXXX, unambiguous chars (no 0/O, 1/I)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "WA-" + "".join(secrets.choice(alphabet) for _ in range(6))


def create_wa_pairing_code(telegram_id: int, path=None) -> str:
    """Generate a single-use pairing code for a Telegram user. Returns the code."""
    init_whatsapp_tables(path)
    conn = connect(path)
    try:
        now = int(time.time())
        # invalidate old unused codes for this user
        conn.execute(
            "UPDATE wa_pairing_codes SET used = 1 WHERE telegram_id = ? AND used = 0",
            (telegram_id,),
        )
        code = _gen_wa_code()
        conn.execute(
            "INSERT INTO wa_pairing_codes (code, telegram_id, created_at, expires_at, used)"
            " VALUES (?, ?, ?, ?, 0)",
            (code, telegram_id, now, now + WA_PAIRING_TTL_SEC),
        )
        conn.commit()
        return code
    finally:
        conn.close()


def redeem_wa_pairing_code(code: str, phone: str, wa_name: str = "", path=None) -> dict:
    """Redeem a pairing code. Returns {ok, telegram_id} or {ok: False, error}."""
    init_whatsapp_tables(path)
    code = (code or "").strip().upper()
    phone = normalize_phone(phone)
    if not phone:
        return {"ok": False, "error": "bad_phone"}
    conn = connect(path)
    try:
        now = int(time.time())
        row = conn.execute(
            "SELECT code, telegram_id, expires_at, used FROM wa_pairing_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        if row["used"]:
            return {"ok": False, "error": "used"}
        if row["expires_at"] < now:
            return {"ok": False, "error": "expired"}
        telegram_id = row["telegram_id"]
        conn.execute("UPDATE wa_pairing_codes SET used = 1 WHERE code = ?", (code,))
        conn.execute(
            "INSERT OR REPLACE INTO wa_links (phone, telegram_id, wa_name, linked_at)"
            " VALUES (?, ?, ?, ?)",
            (phone, telegram_id, wa_name or "", now),
        )
        conn.commit()
        return {"ok": True, "telegram_id": telegram_id}
    finally:
        conn.close()


def get_telegram_id_by_phone(phone: str, path=None):
    """Look up linked Telegram user id for a WhatsApp phone. None if not linked."""
    init_whatsapp_tables(path)
    phone = normalize_phone(phone)
    if not phone:
        return None
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT telegram_id FROM wa_links WHERE phone = ?", (phone,)
        ).fetchone()
        return row["telegram_id"] if row else None
    finally:
        conn.close()


def unlink_whatsapp(phone: str, path=None) -> bool:
    init_whatsapp_tables(path)
    phone = normalize_phone(phone)
    conn = connect(path)
    try:
        cur = conn.execute("DELETE FROM wa_links WHERE phone = ?", (phone,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
