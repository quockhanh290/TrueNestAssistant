"""Broadcast matching, responses, propose flow."""
from .core import connect, _now
from .listings import count_broker_listings
from .brokers import bump_match_stats, get_broker
import json
import uuid
import time



def get_match_response(request_id, responder_broker_id, path=None):
    """One broker's response row for a request (or None)."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, responder_broker_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_match_consent(request_id, responder_broker_id, requester_consent=None,
                      responder_consent=None, path=None):
    """Set one side's consent flag. Returns (row_dict, just_unlocked).

    just_unlocked is True only on the transition to both-consented."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, responder_broker_id),
    ).fetchone()
    if not row:
        conn.close()
        return None, False
    was = bool(row["requester_consent"]) and bool(row["responder_consent"])
    sets, vals = [], []
    if requester_consent is not None:
        sets.append("requester_consent = ?")
        vals.append(1 if requester_consent else 0)
    if responder_consent is not None:
        sets.append("responder_consent = ?")
        vals.append(1 if responder_consent else 0)
    if sets:
        vals.extend([_now(), request_id, responder_broker_id])
        conn.execute(
            f"UPDATE match_responses SET {', '.join(sets)}, updated_at = ?"
            " WHERE request_id = ? AND responder_broker_id = ?",
            vals,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM match_responses"
            " WHERE request_id = ? AND responder_broker_id = ?",
            (request_id, responder_broker_id),
        ).fetchone()
    conn.close()
    d = dict(row)
    just = (not was) and bool(d["requester_consent"]) \
        and bool(d["responder_consent"])
    return d, just


def match_overview_stats(path=None):
    """Aggregate match demand stats for the admin dashboard.

    Returns {"week": {...}, "month": {...}} with requests/responses/unlocks.
    Unlocks count mutual-consent pairs (updated_at used as unlock proxy)."""
    now = _now()
    out = {}
    conn = connect(path)
    for days, key in ((7, "week"), (30, "month")):
        cutoff = now - days * 86400
        req = conn.execute(
            "SELECT COUNT(*) c FROM match_requests WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()["c"]
        resp = conn.execute(
            "SELECT COUNT(*) c FROM match_responses WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()["c"]
        unl = conn.execute(
            "SELECT COUNT(*) c FROM match_responses"
            " WHERE requester_consent = 1 AND responder_consent = 1"
            " AND updated_at >= ?",
            (cutoff,),
        ).fetchone()["c"]
        out[key] = {"requests": req, "responses": resp, "unlocks": unl}
    conn.close()
    return out


def top_match_requesters(limit=5, path=None):
    """Brokers ranked by match_requests_sent."""
    conn = connect(path)
    rows = conn.execute(
        "SELECT user_id, username, display_name, name, match_requests_sent"
        " FROM brokers WHERE match_requests_sent > 0"
        " ORDER BY match_requests_sent DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def top_match_responders(limit=5, path=None):
    """Brokers ranked by number of match responses sent."""
    conn = connect(path)
    rows = conn.execute(
        "SELECT responder_broker_id AS user_id, COUNT(*) AS n"
        " FROM match_responses GROUP BY responder_broker_id"
        " ORDER BY n DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        b = get_broker(r["user_id"], path=path) or {}
        out.append({
            "user_id": r["user_id"],
            "responses": r["n"],
            "username": b.get("username"),
            "display_name": b.get("display_name") or b.get("name"),
        })
    return out


MATCH_REQUEST_STATUSES = ("open", "matched", "closed")


def create_match_request(broker_id, client_id, requirements_summary,
                         urgency="normal", path=None):
    if urgency not in ("urgent", "normal", "low"):
        urgency = "normal"
    mr_id = "mr:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO match_requests (id, broker_id, client_id,"
        " requirements_summary, urgency, status, group_message_id,"
        " created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 'open', NULL, ?, ?)",
        (mr_id, broker_id, client_id, requirements_summary, urgency,
         now, now),
    )
    conn.commit()
    conn.close()
    bump_match_stats(broker_id, path=path, requests_sent=1)
    return mr_id


def get_match_request(mr_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_requests WHERE id = ?", (mr_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_match_request_by_group_message(group_message_id, path=None):
    """Find an OPEN request by its Telegram group message id."""
    expire_old_requests(path=path)
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_requests"
        " WHERE group_message_id = ? AND status = 'open'",
        (group_message_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_broker_requests(broker_id, status=None, limit=50, path=None):
    expire_old_requests(path=path)
    conds = ["broker_id = ?"]
    vals = [broker_id]
    if status:
        conds.append("status = ?")
        vals.append(status)
    vals.append(limit)
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM match_requests WHERE " + " AND ".join(conds) +
        " ORDER BY updated_at DESC LIMIT ?",
        vals,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_open_requests(broker_id=None, path=None):
    """All open requests; optionally scoped to one broker."""
    expire_old_requests(path=path)
    if broker_id is None:
        sql = ("SELECT * FROM match_requests WHERE status = 'open'"
               " ORDER BY updated_at DESC")
        vals = []
    else:
        sql = ("SELECT * FROM match_requests WHERE broker_id = ?"
               " AND status = 'open' ORDER BY updated_at DESC")
        vals = [broker_id]
    conn = connect(path)
    rows = conn.execute(sql, vals).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_match_request(mr_id, path=None, **fields):
    allowed = {"status", "group_message_id", "requirements_summary",
               "closed_reason"}
    sets = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
    vals.extend([_now(), mr_id])
    conn = connect(path)
    conn.execute(
        f"UPDATE match_requests SET {sets}, updated_at = ? WHERE id = ?",
        vals,
    )
    conn.commit()
    conn.close()


def close_match_request(mr_id, path=None):
    update_match_request(mr_id, path=path, status="closed")


BROADCAST_EXPIRE_DAYS = 7  # broadcasts auto-close after this long


MAX_RESPONDERS = 3         # max brokers that can respond to one broadcast


def expire_old_requests(days=BROADCAST_EXPIRE_DAYS, path=None):
    """Auto-close stale open/matched requests. Returns count closed."""
    cutoff = _now() - days * 86400
    now = _now()
    conn = connect(path)
    cur = conn.execute(
        "UPDATE match_requests SET status = 'closed',"
        " closed_reason = 'expired', updated_at = ?"
        " WHERE status IN ('open', 'matched') AND created_at < ?",
        (now, cutoff),
    )
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def broadcast_stats(broker_id, path=None):
    """Broadcast counts for rate limits. Every successful broadcast creates
    a match_requests row, so stats derive from it (no separate table)."""
    now = _now()
    conn = connect(path)
    row = conn.execute(
        "SELECT"
        " SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS d24,"
        " SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS d7,"
        " MAX(created_at) AS last_at"
        " FROM match_requests WHERE broker_id = ?",
        (now - 86400, now - 7 * 86400, broker_id),
    ).fetchone()
    conn.close()
    return {
        "last_24h": row["d24"] or 0,
        "last_7d": row["d7"] or 0,
        "last_at": row["last_at"],
    }


def open_request_for_client(broker_id, client_id, path=None):
    """Any active (open/matched) broadcast request for this client?"""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_requests WHERE broker_id = ? AND client_id = ?"
        " AND status IN ('open', 'matched')"
        " ORDER BY updated_at DESC LIMIT 1",
        (broker_id, client_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def can_broadcast(broker_id, client=None, path=None):
    """All anti-spam checks before posting to the group.

    Returns (ok, reason, info). reason is None when ok, otherwise one of:
    not_qualified | low_urgency | already_open |
    daily_limit | weekly_limit | cooldown.
    """
    expire_old_requests(path=path)
    now = _now()

    # 1. qualification gate: >= 10 submitted listings
    n_listings = count_broker_listings(broker_id, statuses=["submitted"])
    if n_listings < 10:
        return False, "not_qualified", {"listing_count": n_listings}

    # 2. urgency filter: only urgent/normal can broadcast
    urg = (client or {}).get("urgency") or "normal"
    if urg not in ("urgent", "normal"):
        return False, "low_urgency", {"urgency": urg}

    # 3. one active broadcast per client
    cid = (client or {}).get("id")
    if cid and open_request_for_client(broker_id, cid, path=path):
        return False, "already_open", {"client_name": client.get("name")}

    # 4/5/6. rate limits
    stats = broadcast_stats(broker_id, path=path)
    if stats["last_24h"] >= config.BROADCAST_DAILY_LIMIT:
        return False, "daily_limit", {
            "daily_limit": config.BROADCAST_DAILY_LIMIT}
    if stats["last_7d"] >= config.BROADCAST_WEEKLY_LIMIT:
        return False, "weekly_limit", {
            "weekly_limit": config.BROADCAST_WEEKLY_LIMIT}
    if stats["last_at"]:
        hours_since = (now - stats["last_at"]) / 3600
        if hours_since < config.BROADCAST_COOLDOWN_HOURS:
            return False, "cooldown", {
                "hours_since": hours_since,
                "hours_left": config.BROADCAST_COOLDOWN_HOURS - hours_since}
    return True, None, stats


def record_broadcast(broker_id, path=None):
    """Hook called right after a broadcast posts successfully. The
    match_requests row created by create_match_request() IS the record —
    broadcast_stats() reads it — so this returns current stats as a
    confirmation hook for the anti-spam flow."""
    return broadcast_stats(broker_id, path=path)


def add_match_response(request_id, responder_broker_id, responder_username=None,
                       listing_id=None, listing_ids=None, match_scores=None,
                       path=None):
    """Record one broker's response. Returns (ok, response_count).
    ok=False when this broker already responded (deduped).
    listing_ids/match_scores are stored as JSON (set after scoring passes)."""
    conn = connect(path)
    exists = conn.execute(
        "SELECT 1 FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, responder_broker_id),
    ).fetchone()
    if exists:
        n = conn.execute(
            "SELECT COUNT(*) c FROM match_responses WHERE request_id = ?",
            (request_id,),
        ).fetchone()["c"]
        conn.close()
        return False, n
    lids = listing_ids or ([listing_id] if listing_id else [])
    now = _now()
    conn.execute(
        "INSERT INTO match_responses (id, request_id, responder_broker_id,"
        " responder_username, listing_id, listing_ids, match_scores,"
        " messages, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
        ("mresp:" + uuid.uuid4().hex[:12], request_id, responder_broker_id,
         responder_username, lids[0] if lids else listing_id,
         json.dumps(lids, ensure_ascii=False),
         json.dumps(match_scores or {}, ensure_ascii=False),
         now, now),
    )
    n = conn.execute(
        "SELECT COUNT(*) c FROM match_responses WHERE request_id = ?",
        (request_id,),
    ).fetchone()["c"]
    conn.commit()
    conn.close()
    # analytics: requester gained a response; responder was active
    req = get_match_request(request_id, path=path)
    if req:
        bump_match_stats(req["broker_id"], path=path, responses_received=1)
    bump_match_stats(responder_broker_id, path=path)
    return True, n


def has_responded(request_id, responder_broker_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT 1 FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, responder_broker_id),
    ).fetchone()
    conn.close()
    return bool(row)


def count_responses(request_id, path=None):
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM match_responses WHERE request_id = ?",
        (request_id,),
    ).fetchone()["c"]
    conn.close()
    return n


def list_responses(request_id, path=None):
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM match_responses WHERE request_id = ?"
        " ORDER BY created_at ASC",
        (request_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_responses_seen(request_id, path=None):
    """Broker opened the response list — stop the 'unseen' nag."""
    conn = connect(path)
    cur = conn.execute(
        "UPDATE match_requests SET responses_seen_at = ?, updated_at = ?"
        " WHERE id = ?",
        (_now(), _now(), request_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def unseen_match_responses(broker_id, min_hours=24, path=None):
    """Broadcast requests with responses the broker hasn't looked at for
    min_hours+ hours. Returns [{request, response_count, latest_at}]."""
    cutoff = _now() - min_hours * 3600
    conn = connect(path)
    rows = conn.execute(
        "SELECT mr.*, COUNT(msp.id) AS n_resp, MAX(msp.created_at) AS latest_at"
        " FROM match_requests mr"
        " JOIN match_responses msp ON msp.request_id = mr.id"
        " WHERE mr.broker_id = ? AND mr.status IN ('open', 'matched')"
        " GROUP BY mr.id"
        " HAVING n_resp > 0 AND MAX(msp.created_at) < ?"
        " AND (mr.responses_seen_at IS NULL"
        " OR mr.responses_seen_at < MAX(msp.created_at))",
        (broker_id, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


PROPOSE_TIMEOUT_SECONDS = 3600  # 1 hour to submit after reserving


PROPOSE_MAX_LISTINGS = 5


def set_match_request_expiry(request_id, seconds=PROPOSE_TIMEOUT_SECONDS,
                             path=None):
    """Set expires_at for a match request (called when broadcast goes out)."""
    conn = connect(path)
    conn.execute(
        "UPDATE match_requests SET expires_at = ?, updated_at = ?"
        " WHERE id = ?",
        (_now() + seconds, _now(), request_id),
    )
    conn.commit()
    conn.close()


def check_broker_slot(request_id, broker_id, path=None):
    """True if this broker has a reserved slot (response row exists or is
    in the in-memory pending set managed by feat_match)."""
    conn = connect(path)
    row = conn.execute(
        "SELECT 1 FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, broker_id),
    ).fetchone()
    conn.close()
    return bool(row)


def get_propose_request(request_id, path=None):
    """Full request dict with client requirements for the propose view."""
    conn = connect(path)
    row = conn.execute(
        "SELECT mr.*, c.budget_min, c.budget_max, c.bedrooms, c.district,"
        " c.property_type, c.requirements_raw, c.urgency AS client_urgency"
        " FROM match_requests mr"
        " LEFT JOIN clients c ON c.id = mr.client_id"
        " WHERE mr.id = ?",
        (request_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def save_propose_response(request_id, broker_id, listing_ids, match_scores=None,
                          path=None):
    """Save/update a broker's proposed listings. Returns True on success."""
    conn = connect(path)
    now = _now()
    cur = conn.execute(
        "UPDATE match_responses SET listing_ids = ?, match_scores = ?,"
        " updated_at = ?"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (json.dumps(listing_ids), json.dumps(match_scores or {}),
         now, request_id, broker_id),
    )
    if cur.rowcount == 0:
        import uuid as _uuid
        conn.execute(
            "INSERT INTO match_responses (id, request_id, responder_broker_id,"
            " listing_ids, match_scores, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"mresp:{_uuid.uuid4().hex[:12]}", request_id, broker_id,
             json.dumps(listing_ids), json.dumps(match_scores or {}),
             now, now),
        )
    conn.commit()
    conn.close()
    return True


def get_propose_response(request_id, broker_id, path=None):
    """Existing response for this broker (for already_submitted state)."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, broker_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["listing_ids"] = json.loads(d.get("listing_ids") or "[]")
    except (ValueError, TypeError):
        d["listing_ids"] = []
    return d


def release_empty_slot(request_id, broker_id, path=None):
    """Release a broker's slot when they have no eligible listings.

    Called when hard-filtering leaves 0 eligible listings for a reserved
    broker who hasn't submitted yet. Removes their match_responses row so
    the slot opens up for waitlisted brokers.

    Returns True if a slot was actually released.
    """
    conn = connect(path)
    # Only release if they haven't submitted any listings yet
    row = conn.execute(
        "SELECT listing_ids FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, broker_id),
    ).fetchone()
    if not row:
        conn.close()
        return False
    try:
        lids = json.loads(row["listing_ids"] or "[]")
    except (ValueError, TypeError):
        lids = []
    if lids:
        conn.close()
        return False  # already submitted — don't release
    conn.execute(
        "DELETE FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, broker_id),
    )
    conn.commit()
    conn.close()
    return True


def count_active_reservations(request_id, path=None):
    """Count non-released reservations (response rows) for a request."""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM match_responses WHERE request_id = ?",
        (request_id,),
    ).fetchone()["c"]
    conn.close()
    return n


def list_open_xbroker_requests(exclude_broker_id=None, limit=20, path=None):
    """List broadcast requests that need cross-broker help.

    Returns requests that are still open (not expired, not closed) where
    the broker hasn't already responded. Used for the ?view=xbroker page.
    """
    import time
    conn = connect(path)
    now = time.time()
    q = (
        "SELECT mr.*, c.budget_min, c.budget_max, c.bedrooms, c.district,"
        " c.property_type"
        " FROM match_requests mr"
        " LEFT JOIN clients c ON c.id = mr.client_id"
        " WHERE (mr.expires_at IS NULL OR mr.expires_at > ?)"
        " AND (mr.closed_reason IS NULL OR mr.closed_reason = '')"
    )
    args = [now]
    if exclude_broker_id:
        q += (" AND mr.id NOT IN (SELECT request_id FROM match_responses"
              " WHERE responder_broker_id = ?)")
        args.append(exclude_broker_id)
    q += " ORDER BY mr.created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["response_count"] = count_active_reservations(d["id"], path)
        out.append(d)
    return out


def log_relay_message(request_id, responder_broker_id, sender_id, text,
                      path=None):
    """Append one relayed message to the response thread's log."""
    conn = connect(path)
    row = conn.execute(
        "SELECT messages FROM match_responses"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (request_id, responder_broker_id),
    ).fetchone()
    if not row:
        conn.close()
        return False
    try:
        msgs = json.loads(row["messages"] or "[]")
    except (ValueError, TypeError):
        msgs = []
    msgs.append({"from": sender_id, "text": text, "ts": _now()})
    conn.execute(
        "UPDATE match_responses SET messages = ?, updated_at = ?"
        " WHERE request_id = ? AND responder_broker_id = ?",
        (json.dumps(msgs, ensure_ascii=False), _now(), request_id,
         responder_broker_id),
    )
    conn.commit()
    conn.close()
    return True
