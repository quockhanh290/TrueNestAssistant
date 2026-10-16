"""Delayed follow-up system for TrueNest Assistant bot.

2-3 days after a listing is submitted, if required schema fields are still
unknown, the bot circles back with a natural message framed as helping the
broker answer common client questions — NOT as data collection.

Honesty rule: use "Khách hay hỏi về..." (clients often ask about...),
NEVER "Có khách đang hỏi" (a client is asking) unless actually true.

Run:  python3 followup.py [--db PATH]
Prints candidates as JSON for bot.py to send later.
"""
import argparse
import json
import sqlite3
import sys
import time

import config
import db

# Required schema fields (master schema "Bắt buộc") that the bot can collect,
# in priority order. Only ONE is asked per follow-up.
FOLLOWUP_FIELDS = [
    "pet_friendly",      # Nhóm 6 — expat top filter
    "furnishing",        # Nhóm 6
    "allow_foreigners",  # Nhóm 13 — key for expat market
    "curfew_type",       # Nhóm 13
    "ev_charging",       # Nhóm 13
    "amenities",         # Nhóm 6
]

# Window: listings last updated between these many days ago
FOLLOWUP_DAYS_MIN = 2
FOLLOWUP_DAYS_MAX = 3
# Max 1 follow-up per listing per 7 days
FOLLOWUP_COOLDOWN_DAYS = 7

# Only follow up on listings in these statuses (live, not rented/expired)
FOLLOWUP_STATUSES = ("submitted", "pending_info")


def ensure_followup_column(path=None):
    """Add last_followup_at to tg_listings if missing (idempotent)."""
    conn = db.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tg_listings)")]
    if "last_followup_at" not in cols:
        conn.execute("ALTER TABLE tg_listings ADD COLUMN last_followup_at REAL")
        conn.commit()
    conn.close()


def _unknown_required_fields(parsed):
    """Return FOLLOWUP_FIELDS still unknown in the parsed dict, in priority order."""
    unknown = []
    for f in FOLLOWUP_FIELDS:
        v = parsed.get(f)
        if v is None or v == "" or v == "unknown":
            unknown.append(f)
    return unknown


def get_followup_candidates(path=None, days_min=FOLLOWUP_DAYS_MIN,
                             days_max=FOLLOWUP_DAYS_MAX):
    """Find listings updated 2-3 days ago with unknown required fields.

    Excludes listings followed up within the cooldown window.
    Returns list of dicts: listing + broker info + target field.
    """
    ensure_followup_column(path)
    now = time.time()
    oldest = now - days_max * 86400
    newest = now - days_min * 86400
    cooldown_cutoff = now - FOLLOWUP_COOLDOWN_DAYS * 86400

    conn = db.connect(path)
    ph = ", ".join("?" for _ in FOLLOWUP_STATUSES)
    rows = conn.execute(
        f"SELECT l.*, b.user_id AS tg_user_id, b.display_name, b.username"
        f" FROM tg_listings l JOIN brokers b ON b.user_id = l.broker_id"
        f" WHERE l.status IN ({ph})"
        f" AND l.updated_at >= ? AND l.updated_at < ?"
        f" AND (l.last_followup_at IS NULL OR l.last_followup_at < ?)"
        f" ORDER BY l.updated_at ASC",
        (*FOLLOWUP_STATUSES, oldest, newest, cooldown_cutoff),
    ).fetchall()
    conn.close()

    candidates = []
    for r in rows:
        d = dict(r)
        try:
            parsed = json.loads(d["parsed"]) if isinstance(d["parsed"], str) else d["parsed"]
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        unknown = _unknown_required_fields(parsed)
        if not unknown:
            continue
        d["parsed"] = parsed
        d["target_field"] = unknown[0]  # highest priority only
        d["unknown_fields"] = unknown
        candidates.append(d)
    return candidates


def _short_desc(parsed):
    """Build a short listing description like '2PN An Thượng'."""
    parts = []
    bedrooms = parsed.get("bedrooms")
    if bedrooms is not None:
        try:
            b = float(bedrooms)
            parts.append("Studio" if b == 0 else f"{int(b)}PN")
        except (ValueError, TypeError):
            pass
    for key in ("building_name", "street", "ward", "district"):
        v = parsed.get(key)
        if v:
            parts.append(str(v))
            break
    price = parsed.get("price_vnd")
    if price:
        try:
            parts.append(f"{float(price) / 1e6:.0f}tr")
        except (ValueError, TypeError):
            pass
    return " ".join(parts) if parts else "căn này"


# (message template, quick-reply buttons) per field.
# Honest framing: "khách hay hỏi" — never fabricate a specific client.
FIELD_TEMPLATES = {
    "pet_friendly": (
        "Anh ơi, khách xem tin {desc} của anh hay hỏi về pet lắm. "
        "Tin mình chưa ghi, anh xác nhận giúp em để em trả lời khách được ngay nhé?",
        ["Có, cho nuôi pet", "Không cho pet"],
    ),
    "furnishing": (
        "Anh ơi, khách hay hỏi tin {desc} có full nội thất không. "
        "Anh xác nhận giúp em để em báo khách cho chuẩn nhé?",
        ["Full nội thất", "Cơ bản", "Trống"],
    ),
    "allow_foreigners": (
        "Anh ơi, khách nước ngoài hay hỏi tin {desc} có nhận không. "
        "Anh xác nhận giúp em để em trả lời họ ngay nhé?",
        ["Có nhận", "Không nhận"],
    ),
    "curfew_type": (
        "Anh ơi, khách hay hỏi về giờ giấc của tin {desc}. "
        "Chỗ mình giờ giấc tự do hay có giờ giới nghiêm anh?",
        ["Tự do 24/7", "Có giới nghiêm"],
    ),
    "ev_charging": (
        "Anh ơi, khách đi xe điện hay hỏi tin {desc} có chỗ sạc không. "
        "Anh xác nhận giúp em nhé?",
        ["Có chỗ sạc", "Không có"],
    ),
    "amenities": (
        "Anh ơi, để em ghi tin {desc} nổi bật hơn cho khách dễ tìm, "
        "chỗ mình có những tiện ích nào anh nhỉ? (thang máy, hồ bơi, máy giặt...)",
        ["Để em ghi sau"],
    ),
}


def build_followup_message(listing, field=None):
    """Build a natural follow-up message for one listing.

    Returns (message_text, quick_reply_buttons).
    """
    field = field or listing.get("target_field")
    if field not in FIELD_TEMPLATES:
        raise ValueError(f"no template for field {field!r}")
    template, buttons = FIELD_TEMPLATES[field]
    desc = _short_desc(listing.get("parsed", {}))
    return template.format(desc=desc), buttons


def record_followup(listing_id, path=None):
    """Mark a listing as followed up now (enforces 1/week limit)."""
    ensure_followup_column(path)
    conn = db.connect(path)
    conn.execute(
        "UPDATE tg_listings SET last_followup_at = ? WHERE id = ?",
        (time.time(), listing_id),
    )
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Find listings due for follow-up")
    ap.add_argument("--db", default=None, help="SQLite path (default: config.DB_PATH)")
    ap.add_argument("--mark", action="store_true",
                    help="Record follow-ups (otherwise dry-run, just prints)")
    args = ap.parse_args()

    db.init_db(args.db)
    candidates = get_followup_candidates(args.db)

    out = []
    for c in candidates:
        msg, buttons = build_followup_message(c)
        item = {
            "listing_id": c["id"],
            "tg_user_id": c["tg_user_id"],
            "broker_name": c.get("display_name") or c.get("username"),
            "target_field": c["target_field"],
            "unknown_fields": c["unknown_fields"],
            "message": msg,
            "buttons": buttons,
        }
        out.append(item)
        if args.mark:
            record_followup(c["id"], args.db)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
