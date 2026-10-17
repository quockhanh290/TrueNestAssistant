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
