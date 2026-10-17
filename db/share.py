"""Share pages, bookings, listing reports."""
import secrets
import uuid

from .core import connect, _now, _migrate_listing_reports, _migrate_refresh_log
import json



SHARE_TOKEN_BYTES = 9       # secrets.token_urlsafe(9) -> 12 chars


SHARE_TTL_DAYS = 30


def _gen_share_token(conn):
    """Unique 12-char URL-safe token (retries on collision)."""
    for _ in range(10):
        token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
        row = conn.execute(
            "SELECT 1 FROM share_pages WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return token
    raise RuntimeError("could not generate unique share token")


def create_share_page(broker_id, listing_ids, title="", client_id=None,
                      path=None, ttl_days=SHARE_TTL_DAYS):
    """Create a public share page. Returns the token."""
    now = _now()
    conn = connect(path)
    try:
        token = _gen_share_token(conn)
        conn.execute(
            "INSERT INTO share_pages (token, broker_id, client_id,"
            " listing_ids, title, created_at, expires_at, view_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (token, broker_id, client_id,
             json.dumps(list(listing_ids or []), ensure_ascii=False),
             title or "", now, now + ttl_days * 86400),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def get_share_page(token, path=None, bump_view=True):
    """Public share page by token. None if missing/expired.

    bump_view increments view_count (page render path only).
    """
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM share_pages WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d["expires_at"] and d["expires_at"] < _now():
            return None
        if bump_view:
            conn.execute(
                "UPDATE share_pages SET view_count = view_count + 1"
                " WHERE token = ?",
                (token,),
            )
            conn.commit()
            d["view_count"] = (d["view_count"] or 0) + 1
        d["listing_ids"] = json.loads(d["listing_ids"] or "[]")
        return d
    finally:
        conn.close()


def list_share_pages(broker_id, path=None):
    """Broker's share pages, newest first."""
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM share_pages WHERE broker_id = ?"
            " ORDER BY created_at DESC",
            (broker_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["listing_ids"] = json.loads(d["listing_ids"] or "[]")
            out.append(d)
        return out
    finally:
        conn.close()


def create_share_booking(token, broker_id, name, phone, listing_id=None,
                         preferred_date="", note="", path=None):
    """Viewing request from a public share page. Returns booking id."""
    conn = connect(path)
    try:
        bid = "sb:" + uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO share_bookings (id, token, broker_id, listing_id,"
            " name, phone, preferred_date, note, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
            (bid, token, broker_id, listing_id, name or "", phone or "",
             preferred_date or "", note or "", _now()),
        )
        conn.commit()
        return bid
    finally:
        conn.close()


def list_share_bookings(token=None, broker_id=None, path=None):
    """Bookings for a share page and/or broker, newest first."""
    conn = connect(path)
    try:
        conds, vals = [], []
        if token:
            conds.append("token = ?")
            vals.append(token)
        if broker_id is not None:
            conds.append("broker_id = ?")
            vals.append(broker_id)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = conn.execute(
            f"SELECT * FROM share_bookings {where} ORDER BY created_at DESC",
            vals,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


REPORT_REASONS = ("rented", "price_wrong", "photo_wrong", "address_wrong")


REPORT_REASON_VI = {
    "rented": "Đã cho thuê rồi",
    "price_wrong": "Giá không đúng",
    "photo_wrong": "Ảnh không đúng thực tế",
    "address_wrong": "Địa chỉ sai",
}


def create_listing_report(token, listing_id, broker_id, reason, path=None):
    """Store a client report. Returns report id, or None on bad reason."""
    if reason not in REPORT_REASONS:
        return None
    conn = connect(path)
    _migrate_listing_reports(conn)
    cur = conn.execute(
        "INSERT INTO listing_reports"
        " (token, listing_id, broker_id, reason, created_at, reviewed)"
        " VALUES (?, ?, ?, ?, ?, 0)",
        (token, listing_id, broker_id, reason, _now()),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def reserve_report_penalty(token, listing_id, report_id, reason, path=None):
    """Claim the single automatic penalty a public share link may cause.

    Returns True for the first penalty-worthy report coming from `token`
    and False for every later one (same listing again, or another listing
    on the same page). The check-and-claim is one INSERT on a primary key,
    so concurrent POSTs cannot both win. The report itself is always kept
    for admin review; only the automatic strike is limited.
    """
    conn = connect(path)
    _migrate_listing_reports(conn)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO report_penalties"
            " (token, listing_id, report_id, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (token, listing_id, report_id, reason, _now()),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def get_latest_refresh_claim(listing_id, path=None):
    """Most recent refresh claim for a listing, or None."""
    conn = connect(path)
    _migrate_refresh_log(conn)
    row = conn.execute(
        "SELECT * FROM listing_refresh_log"
        " WHERE listing_id = ? ORDER BY created_at DESC LIMIT 1",
        (listing_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def check_report_against_refresh(listing_id, path=None):
    """Does a client report likely indicate a false refresh claim?

    If the latest refresh claim was 'available' within the last 7 days and
    the report says the listing is rented -> probable false refresh.
    Returns the claim dict if suspicious, else None.
    """
    claim = get_latest_refresh_claim(listing_id, path=path)
    if not claim or claim["claimed_status"] != "available":
        return None
    if _now() - claim["created_at"] > 7 * 86400:
        return None
    return claim


def mark_report_reviewed(report_id, path=None):
    conn = connect(path)
    _migrate_listing_reports(conn)
    conn.execute(
        "UPDATE listing_reports SET reviewed = 1 WHERE id = ?",
        (report_id,),
    )
    conn.commit()
    conn.close()


def list_unreviewed_reports(limit=50, path=None):
    """For Khanh's admin view: unreviewed reports with listing/broker info."""
    conn = connect(path)
    _migrate_listing_reports(conn)
    rows = conn.execute(
        "SELECT r.*, l.broker_id AS listing_broker,"
        " b.phone AS broker_phone"
        " FROM listing_reports r"
        " LEFT JOIN tg_listings l ON l.id = r.listing_id"
        " LEFT JOIN brokers b ON b.user_id = r.broker_id"
        " WHERE r.reviewed = 0 ORDER BY r.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(x) for x in rows]


# ------------------------------------------------- admin /baocao (17/10)

def mark_report_penalty_applied(report_id, result, path=None):
    """Record that the strike reserved by `report_id` was really applied.

    `result` is what refresh.flag_false_refresh returned (broker_id,
    banned_until). Lets /baocao tell "penalised" from "reserved only" and
    take back exactly this strike later.
    """
    if not report_id or not result:
        return
    conn = connect(path)
    _migrate_listing_reports(conn)
    conn.execute(
        "UPDATE report_penalties SET applied_at = ?, broker_id = ?,"
        " banned_until = ? WHERE report_id = ?",
        (_now(), result.get("broker_id"), result.get("banned_until"),
         report_id),
    )
    conn.commit()
    conn.close()


def _penalty_state(row):
    """'applied' | 'revoked' | 'reserved' | None for a joined report row.

    Rows from before 17/10 have no applied_at; there the pipeline marked
    the report reviewed only after the strike was applied, so a reserved
    + reviewed report counts as applied.
    """
    if row.get("p_token") is None:
        return None
    if row.get("p_revoked_at"):
        return "revoked"
    if row.get("p_applied_at") or row.get("reviewed"):
        return "applied"
    return "reserved"


def list_recent_reports(limit=20, path=None):
    """Newest share-page reports for the admin, with listing, broker and
    penalty state ("penalty": applied/revoked/reserved/None)."""
    conn = connect(path)
    _migrate_listing_reports(conn)
    rows = conn.execute(
        "SELECT r.*, l.parsed AS listing_parsed,"
        " b.display_name AS broker_name, b.username AS broker_username,"
        " p.token AS p_token, p.applied_at AS p_applied_at,"
        " p.revoked_at AS p_revoked_at"
        " FROM listing_reports r"
        " LEFT JOIN tg_listings l ON l.id = r.listing_id"
        " LEFT JOIN brokers b ON b.user_id = r.broker_id"
        " LEFT JOIN report_penalties p ON p.report_id = r.id"
        " ORDER BY r.created_at DESC, r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for x in rows:
        d = dict(x)
        try:
            d["listing_parsed"] = json.loads(d.get("listing_parsed") or "{}")
        except (TypeError, ValueError):
            d["listing_parsed"] = {}
        d["penalty"] = _penalty_state(d)
        out.append(d)
    return out


def revoke_report_penalty(report_id, path=None):
    """Admin takes back the strike a share-page report caused.

    Gives back exactly one false-report strike, once. If that brings the
    broker under the ban threshold, the propose lock is lifted too (the
    lock exists only because the count reached the threshold). A lock that
    the remaining strikes still justify is kept.
    Returns {"broker_id", "false_count", "unlocked"} or None when the
    report caused no applied, still-standing penalty.
    """
    from .refresh import FALSE_REFRESH_BAN_COUNT
    from .core import _migrate_refresh_reputation
    conn = connect(path)
    try:
        _migrate_listing_reports(conn)
        _migrate_refresh_reputation(conn)
        row = conn.execute(
            "SELECT p.*, r.reviewed AS reviewed, r.broker_id AS r_broker,"
            " p.token AS p_token, p.applied_at AS p_applied_at,"
            " p.revoked_at AS p_revoked_at"
            " FROM report_penalties p"
            " LEFT JOIN listing_reports r ON r.id = p.report_id"
            " WHERE p.report_id = ?",
            (report_id,),
        ).fetchone()
        if not row or _penalty_state(dict(row)) != "applied":
            return None
        broker_id = row["broker_id"] or row["r_broker"]
        now = _now()
        # claim the revoke first so a double tap cannot give back two
        cur = conn.execute(
            "UPDATE report_penalties SET revoked_at = ?"
            " WHERE report_id = ? AND revoked_at IS NULL",
            (now, report_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.execute(
            "UPDATE brokers SET false_refresh_reports ="
            " MAX(0, COALESCE(false_refresh_reports, 0) - 1)"
            " WHERE user_id = ?",
            (broker_id,),
        )
        b = conn.execute(
            "SELECT false_refresh_reports, refresh_cooldown_until"
            " FROM brokers WHERE user_id = ?",
            (broker_id,),
        ).fetchone()
        count = (b["false_refresh_reports"] or 0) if b else 0
        unlocked = False
        if b and b["refresh_cooldown_until"] and \
                b["refresh_cooldown_until"] > now and \
                count < FALSE_REFRESH_BAN_COUNT:
            conn.execute(
                "UPDATE brokers SET refresh_cooldown_until = NULL"
                " WHERE user_id = ?",
                (broker_id,),
            )
            unlocked = True
        conn.commit()
        return {"broker_id": broker_id, "false_count": count,
                "unlocked": unlocked}
    finally:
        conn.close()
