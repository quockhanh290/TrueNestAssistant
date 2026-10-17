"""Broker accounts, tiers, premium, checklist."""
from contextlib import closing
from .core import connect, _now
import config
import json
import uuid



def get_or_create_broker(user_id, username=None, display_name=None, path=None):
    with closing(connect(path)) as conn:
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
    with closing(connect(path)) as conn:
        conn.execute(f"UPDATE brokers SET {sets} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()


def get_broker(user_id, path=None):
    with closing(connect(path)) as conn:
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
    with closing(connect(path)) as conn:
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

# Monthly price per paid tier, in VND. The ONE source for the prices shown
# on the plans screen (feat_premium builds its labels from it) and for the
# Pro -> Max day conversion below. A tier without a price (enterprise) is
# never converted.
TIER_PRICE_VND = {"pro": 99_000, "max": 199_000}


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


def set_tier(broker_id, tier, days=30, stack=False, path=None):
    """Activate a tier for `days` (use days=0 for no expiry).

    stack=True is for granting a PAID period (decide_premium_request): an
    early renewal of the same, still-active tier is counted from the current
    expiry, so paying before the old period ends never throws days away;
    an upgrade to a dearer tier converts the days still left by price (see
    _set_tier). stack=False (admin /approve without a pending request,
    referral, tests) never adds on top: the same active tier ends at
    max(current expiry, now + days), so typing /approve twice cannot hand
    out 60 days. A different tier, or an expired one, starts from now.
    Returns the new expiry (None = no expiry).
    """
    return _set_tier(broker_id, tier, days=days, stack=stack,
                     path=path)["expires_at"]


def upgrade_credit_days(old_tier, new_tier, days_left):
    """Days of `new_tier` worth the `days_left` of `old_tier`, by price.

    Only for an upgrade between two priced tiers (Pro -> Max):
    days_left x price(old) / price(new). 0 for anything else (same tier,
    downgrade, free, a tier without a price, nothing left).
    """
    p_old = TIER_PRICE_VND.get(old_tier)
    p_new = TIER_PRICE_VND.get(new_tier)
    if not p_old or not p_new or days_left <= 0:
        return 0.0
    if TIER_ORDER.get(new_tier, 0) <= TIER_ORDER.get(old_tier, 0):
        return 0.0
    return days_left * p_old / p_new


def _set_tier(broker_id, tier, days=30, stack=False, path=None):
    """set_tier, returning {"expires_at", "converted_from_tier",
    "converted_days_left", "converted_credit_days"} so the approval
    message can say how many days were converted."""
    if tier not in TIER_ORDER:
        raise ValueError(f"unknown tier: {tier}")
    now = _now()
    exp = None
    out = {"converted_from_tier": None, "converted_days_left": 0.0,
           "converted_credit_days": 0.0}
    if days:
        start = now
        b = get_broker(broker_id, path=path) or {}
        cur_tier = b.get("tier") or "free"
        cur_exp = b.get("tier_expires_at")
        active = bool(cur_exp and cur_exp > now)
        same_active = cur_tier == tier and active
        if same_active and stack:
            start = cur_exp
        exp = start + days * 86400
        if same_active and not stack:
            exp = max(exp, cur_exp)
        if stack and active and not same_active:
            # paid upgrade (Pro -> Max): the Pro days still left are worth
            # days_left x price(Pro) / price(Max) Max days. Downgrades and
            # unpriced tiers get 0 and start from now, as before.
            days_left = (cur_exp - now) / 86400
            credit = upgrade_credit_days(cur_tier, tier, days_left)
            if credit > 0:
                exp += credit * 86400
                out.update(converted_from_tier=cur_tier,
                           converted_days_left=days_left,
                           converted_credit_days=credit)
    limit = config.FREE_LISTING_LIMIT if tier == "free" else 0  # 0 = unlimited
    update_broker(broker_id, path=path, tier=tier,
                  tier_expires_at=exp, listing_limit=limit)
    out["expires_at"] = exp
    return out


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
    with closing(connect(path)) as conn:
        conn.execute(
            "INSERT INTO premium_requests (id, broker_id, tier_requested, status,"
            " created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?)",
            (rid, broker_id, tier_requested, now, now),
        )
        conn.commit()
        conn.close()
        return rid


def get_pending_premium_request(broker_id, path=None):
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM premium_requests WHERE broker_id = ? AND status = 'pending'"
            " ORDER BY created_at DESC LIMIT 1",
            (broker_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None


def list_pending_premium_requests(path=None):
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT * FROM premium_requests WHERE status = 'pending'"
            " ORDER BY created_at ASC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def decide_premium_request(request_id, approve, tier=None, days=30,
                           path=None):
    """Approve or reject a premium request. Returns the request dict.

    On approve this is the ONLY place the tier is granted (once). `tier`
    overrides what the broker asked for — the admin's typed tier wins.
    The granted tier/expiry are returned as req["granted_tier"] /
    req["expires_at"]; a paid Pro -> Max upgrade also returns
    req["converted_days_left"] (Pro days left) and
    req["converted_credit_days"] (Max days they were worth).
    """
    with closing(connect(path)) as conn:
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
            granted = tier or req["tier_requested"]
            req["granted_tier"] = granted
            res = _set_tier(req["broker_id"], granted, days=days, stack=True,
                            path=path)
            req["expires_at"] = res["expires_at"]
            req["converted_from_tier"] = res["converted_from_tier"]
            req["converted_days_left"] = res["converted_days_left"]
            req["converted_credit_days"] = res["converted_credit_days"]
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
    with closing(connect(path)) as conn:
        rows = conn.execute("SELECT * FROM brokers").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def add_checklist_item(broker_id, kind, ref_id, label="", path=None):
    """Idempotent — same (broker, kind, ref) is only stored once."""
    item_id = "ck:" + uuid.uuid4().hex[:12]
    now = _now()
    with closing(connect(path)) as conn:
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
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT * FROM pending_checklist WHERE broker_id = ?"
            " ORDER BY created_at ASC",
            (broker_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def clear_checklist_item(broker_id, kind, ref_id, path=None):
    with closing(connect(path)) as conn:
        cur = conn.execute(
            "DELETE FROM pending_checklist"
            " WHERE broker_id = ? AND kind = ? AND ref_id = ?",
            (broker_id, kind, ref_id),
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def clear_checklist(broker_id, path=None):
    with closing(connect(path)) as conn:
        cur = conn.execute(
            "DELETE FROM pending_checklist WHERE broker_id = ?", (broker_id,)
        )
        conn.commit()
        conn.close()
        return cur.rowcount


def clear_old_checklist(days=2, path=None):
    """Purge checklist items older than `days` — stale nags."""
    cutoff = _now() - days * 86400
    with closing(connect(path)) as conn:
        cur = conn.execute(
            "DELETE FROM pending_checklist WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        conn.close()
        return cur.rowcount
