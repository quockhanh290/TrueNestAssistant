"""Broker accounts, tiers, premium, checklist."""
from .core import connect, _now
import json
import uuid



def get_or_create_broker(user_id, username=None, display_name=None, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row:
        conn.close()
        return dict(row)
    now = _now()
    conn.execute(
        "INSERT INTO brokers (user_id, username, display_name, status,"
        " created_at, updated_at)"
        " VALUES (?, ?, ?, 'new', ?, ?)",
        (user_id, username, display_name, now, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def update_broker(user_id, path=None, **fields):
    allowed = {"username", "display_name", "name", "pronoun", "phone", "zalo",
               "facebook", "status", "listings_count", "approved_count",
               "tier", "tier_expires_at", "listing_limit", "seen_hints",
               "match_requests_sent", "match_responses_received",
               "match_contacts_unlocked", "last_match_at"}
    sets = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
    # every broker mutation bumps updated_at (counters in create_listing /
    # set_listing_status are excluded — they're aggregate stats, not edits)
    sets += ", updated_at = ?"
    vals.append(_now())
    vals.append(user_id)
    conn = connect(path)
    conn.execute(f"UPDATE brokers SET {sets} WHERE user_id = ?", vals)
    conn.commit()
    conn.close()


def get_broker(user_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_seen_hints(broker_id, path=None):
    """Return list of hint keys this broker has already seen."""
    import json
    b = get_broker(broker_id, path=path)
    if not b:
        return []
    try:
        return json.loads(b.get("seen_hints") or "[]")
    except (ValueError, TypeError):
        return []


def mark_hint_seen(broker_id, hint_key, path=None):
    """Record that a broker has seen a hint (idempotent)."""
    import json
    seen = get_seen_hints(broker_id, path=path)
    if hint_key not in seen:
        seen.append(hint_key)
        update_broker(broker_id, path=path, seen_hints=json.dumps(seen))


def bump_match_stats(broker_id, path=None, requests_sent=0,
                     responses_received=0, contacts_unlocked=0):
    """Atomically increment a broker's match counters and touch
    last_match_at. Always bumps last_match_at when called."""
    sets, vals = [], []
    if requests_sent:
        sets.append("match_requests_sent = match_requests_sent + ?")
        vals.append(requests_sent)
    if responses_received:
        sets.append("match_responses_received = match_responses_received + ?")
        vals.append(responses_received)
    if contacts_unlocked:
        sets.append("match_contacts_unlocked = match_contacts_unlocked + ?")
        vals.append(contacts_unlocked)
    sets.append("last_match_at = ?")
    vals.append(_now())
    vals.append(broker_id)
    conn = connect(path)
    conn.execute(f"UPDATE brokers SET {', '.join(sets)} WHERE user_id = ?",
                 vals)
    conn.commit()
    conn.close()


def get_match_stats(broker_id, path=None):
    """Per-broker cross-broker match usage stats."""
    b = get_broker(broker_id, path=path) or {}
    return {
        "match_requests_sent": b.get("match_requests_sent") or 0,
        "match_responses_received": b.get("match_responses_received") or 0,
        "match_contacts_unlocked": b.get("match_contacts_unlocked") or 0,
        "last_match_at": b.get("last_match_at"),
    }


TIER_ORDER = {"free": 0, "pro": 1, "max": 2, "enterprise": 3}


ENTERPRISE_LISTING_THRESHOLD = 300


def get_tier(broker_id, path=None):
    """Broker's current tier, auto-downgrading to free if expired."""
    b = get_broker(broker_id, path=path)
    if not b:
        return "free"
    tier = b.get("tier") or "free"
    if tier != "free":
        exp = b.get("tier_expires_at")
        if exp and exp < _now():
            # expired — downgrade silently
            update_broker(broker_id, path=path, tier="free",
                          tier_expires_at=None)
            return "free"
    return tier if tier in TIER_ORDER else "free"


def set_tier(broker_id, tier, days=30, path=None):
    """Activate a tier for `days` (use days=0 for no expiry)."""
    if tier not in TIER_ORDER:
        raise ValueError(f"unknown tier: {tier}")
    exp = _now() + days * 86400 if days else None
    limit = config.FREE_LISTING_LIMIT if tier == "free" else 0  # 0 = unlimited
    update_broker(broker_id, path=path, tier=tier,
                  tier_expires_at=exp, listing_limit=limit)


def tier_allows(broker_id, min_tier, path=None):
    """True if the broker's tier is at least min_tier ('pro' or 'max')."""
    return TIER_ORDER.get(get_tier(broker_id, path=path), 0) >= \
        TIER_ORDER.get(min_tier, 99)


def is_premium(broker_id, path=None):
    """True if broker has an active paid tier."""
    return tier_allows(broker_id, "pro", path=path)


def requires_enterprise_tier(broker_id, path=None):
    """True if the broker manages >300 active listings but isn't Enterprise.

    Wholesalers (đầu nậu) with huge inventories must be on Enterprise tier.
    """
    from .listings import active_listing_count  # lazy: avoids circular import
    if tier_allows(broker_id, "enterprise", path=path):
        return False
    return active_listing_count(broker_id, path=path) > \
        ENTERPRISE_LISTING_THRESHOLD


def create_premium_request(broker_id, tier_requested="pro", path=None):
    rid = f"pr:{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO premium_requests (id, broker_id, tier_requested, status,"
        " created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?)",
        (rid, broker_id, tier_requested, now, now),
    )
    conn.commit()
    conn.close()
    return rid


def get_pending_premium_request(broker_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM premium_requests WHERE broker_id = ? AND status = 'pending'"
        " ORDER BY created_at DESC LIMIT 1",
        (broker_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pending_premium_requests(path=None):
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM premium_requests WHERE status = 'pending'"
        " ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def decide_premium_request(request_id, approve, path=None):
    """Approve or reject a premium request. Returns the request dict."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM premium_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    req = dict(row)
    if req["status"] != "pending":
        conn.close()
        return req
    status = "approved" if approve else "rejected"
    now = _now()
    conn.execute(
        "UPDATE premium_requests SET status = ?, decided_at = ?,"
        " updated_at = ? WHERE id = ?",
        (status, now, now, request_id),
    )
    conn.commit()
    conn.close()
    if approve:
        set_tier(req["broker_id"], req["tier_requested"], days=30, path=path)
    req["status"] = status
    return req


def get_broker_phone(broker_id, path=None):
    """Broker's saved phone, or None."""
    b = get_broker(broker_id, path=path)
    return b.get("phone") if b else None


def set_broker_phone(broker_id, phone, path=None):
    """Save broker's phone (used for listing auto-fill)."""
    update_broker(broker_id, path=path, phone=phone)


def list_brokers(path=None):
    """All brokers — for cron scripts that fan out per broker."""
    conn = connect(path)
    rows = conn.execute("SELECT * FROM brokers").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_checklist_item(broker_id, kind, ref_id, label="", path=None):
    """Idempotent — same (broker, kind, ref) is only stored once."""
    item_id = "ck:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT OR IGNORE INTO pending_checklist"
        " (id, broker_id, kind, ref_id, label, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (item_id, broker_id, kind, ref_id, label, now, now),
    )
    conn.commit()
    conn.close()
    return item_id


def list_checklist(broker_id, path=None):
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM pending_checklist WHERE broker_id = ?"
        " ORDER BY created_at ASC",
        (broker_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_checklist_item(broker_id, kind, ref_id, path=None):
    conn = connect(path)
    cur = conn.execute(
        "DELETE FROM pending_checklist"
        " WHERE broker_id = ? AND kind = ? AND ref_id = ?",
        (broker_id, kind, ref_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def clear_checklist(broker_id, path=None):
    conn = connect(path)
    cur = conn.execute(
        "DELETE FROM pending_checklist WHERE broker_id = ?", (broker_id,)
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def clear_old_checklist(days=2, path=None):
    """Purge checklist items older than `days` — stale nags."""
    cutoff = _now() - days * 86400
    conn = connect(path)
    cur = conn.execute(
        "DELETE FROM pending_checklist WHERE created_at < ?", (cutoff,)
    )
    conn.commit()
    conn.close()
    return cur.rowcount
