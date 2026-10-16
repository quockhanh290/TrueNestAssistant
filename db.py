"""SQLite storage for TrueNest Assistant broker bot.

Tables:
  brokers      — one row per Telegram user
  tg_listings  — listings submitted via the bot
  tg_events    — status-change log for availability tracking
"""
import json
import sqlite3
import time
import uuid

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS brokers (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT,
    display_name   TEXT,
    name           TEXT,
    pronoun        TEXT,
    phone          TEXT,
    zalo           TEXT,
    facebook       TEXT,
    status         TEXT NOT NULL DEFAULT 'new',
    listings_count INTEGER NOT NULL DEFAULT 0,
    approved_count INTEGER NOT NULL DEFAULT 0,
    match_requests_sent     INTEGER NOT NULL DEFAULT 0,
    match_responses_received INTEGER NOT NULL DEFAULT 0,
    match_contacts_unlocked INTEGER NOT NULL DEFAULT 0,
    last_match_at  REAL,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tg_listings (
    id             TEXT PRIMARY KEY,
    broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
    raw_text       TEXT NOT NULL DEFAULT '',
    photo_file_ids TEXT NOT NULL DEFAULT '[]',
    parsed         TEXT NOT NULL DEFAULT '{}',
    missing_fields TEXT NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'draft',
    view_count     INTEGER NOT NULL DEFAULT 0,
    inquiry_count  INTEGER NOT NULL DEFAULT 0,
    duplicate_of   TEXT,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_broker ON tg_listings(broker_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON tg_listings(status);
-- composite: covers list_broker_listings / count_broker_listings /
-- count_recent_listings (broker_id prefix) + status-filtered ORDER BY created_at
CREATE INDEX IF NOT EXISTS idx_listings_broker_status_created
    ON tg_listings(broker_id, status, created_at);

-- NOTE: tg_events intentionally has NO updated_at. It is an append-only
-- audit log: rows are never modified after insert (old_status/new_status/
-- field edits are immutable history). created_at is the single timestamp.
CREATE TABLE IF NOT EXISTS tg_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  TEXT NOT NULL REFERENCES tg_listings(id),
    old_status  TEXT,
    new_status  TEXT,
    changed_by  TEXT NOT NULL DEFAULT 'broker',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_listing ON tg_events(listing_id);

CREATE TABLE IF NOT EXISTS clients (
    id              TEXT PRIMARY KEY,
    broker_id       INTEGER NOT NULL REFERENCES brokers(user_id),
    name            TEXT,
    phone           TEXT,
    budget_min      REAL,
    budget_max      REAL,
    bedrooms        REAL,
    district        TEXT,
    property_type   TEXT,
    requirements_raw TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'new',
    urgency         TEXT NOT NULL DEFAULT 'normal',
    notes           TEXT NOT NULL DEFAULT '',
    viewed_listings TEXT NOT NULL DEFAULT '[]',
    sent_listings   TEXT NOT NULL DEFAULT '[]',
    client_choice   TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    last_contact_at REAL
);
CREATE INDEX IF NOT EXISTS idx_clients_broker ON clients(broker_id);
CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);

CREATE TABLE IF NOT EXISTS viewings (
    id          TEXT PRIMARY KEY,
    broker_id   INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id   TEXT,
    client_name TEXT NOT NULL DEFAULT '',
    listing_id  TEXT,
    listing_ids TEXT NOT NULL DEFAULT '[]',
    scheduled_at REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'scheduled',
    notes       TEXT NOT NULL DEFAULT '',
    feedback    TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_viewings_broker ON viewings(broker_id);
CREATE INDEX IF NOT EXISTS idx_viewings_sched ON viewings(scheduled_at);
-- covers list_viewings(upcoming): broker + status + scheduled_at range, ordered
CREATE INDEX IF NOT EXISTS idx_viewings_broker_status_sched
    ON viewings(broker_id, status, scheduled_at);
-- covers client_viewings(): WHERE client_id = ?
CREATE INDEX IF NOT EXISTS idx_viewings_client ON viewings(client_id);

CREATE TABLE IF NOT EXISTS deals (
    id             TEXT PRIMARY KEY,
    broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id      TEXT,
    client_name    TEXT NOT NULL DEFAULT '',
    listing_id     TEXT,
    commission_vnd REAL,
    paid           INTEGER NOT NULL DEFAULT 0,
    closed_at      REAL NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_broker ON deals(broker_id);
CREATE INDEX IF NOT EXISTS idx_deals_closed ON deals(closed_at);
-- covers list_deals(): broker + closed_at range, ORDER BY closed_at DESC
CREATE INDEX IF NOT EXISTS idx_deals_broker_closed ON deals(broker_id, closed_at);

CREATE TABLE IF NOT EXISTS templates (
    id         TEXT PRIMARY KEY,
    broker_id  INTEGER NOT NULL REFERENCES brokers(user_id),
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_broker ON templates(broker_id);

CREATE TABLE IF NOT EXISTS match_requests (
    id                  TEXT PRIMARY KEY,
    broker_id           INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id           TEXT NOT NULL REFERENCES clients(id),
    requirements_summary TEXT NOT NULL DEFAULT '',
    urgency             TEXT NOT NULL DEFAULT 'normal',
    status              TEXT NOT NULL DEFAULT 'open',
    closed_reason       TEXT,
    group_message_id    INTEGER,
    responses_seen_at   REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mreq_broker ON match_requests(broker_id);
CREATE INDEX IF NOT EXISTS idx_mreq_status ON match_requests(status);
CREATE INDEX IF NOT EXISTS idx_mreq_groupmsg ON match_requests(group_message_id);
-- covers open_request_for_client(): broker + client + status
CREATE INDEX IF NOT EXISTS idx_mreq_broker_client_status
    ON match_requests(broker_id, client_id, status);

CREATE TABLE IF NOT EXISTS match_responses (
    id                  TEXT PRIMARY KEY,
    request_id          TEXT NOT NULL REFERENCES match_requests(id),
    responder_broker_id INTEGER NOT NULL,
    responder_username  TEXT,
    listing_id          TEXT,
    listing_ids         TEXT NOT NULL DEFAULT '[]',
    match_scores        TEXT NOT NULL DEFAULT '{}',
    messages            TEXT NOT NULL DEFAULT '[]',
    requester_consent   INTEGER NOT NULL DEFAULT 0,
    responder_consent   INTEGER NOT NULL DEFAULT 0,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mresp_request ON match_responses(request_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mresp_unique
    ON match_responses(request_id, responder_broker_id);

CREATE TABLE IF NOT EXISTS pending_checklist (
    id        TEXT PRIMARY KEY,
    broker_id INTEGER NOT NULL REFERENCES brokers(user_id),
    kind      TEXT NOT NULL,
    ref_id    TEXT NOT NULL,
    label     TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pcl_broker ON pending_checklist(broker_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pcl_unique
    ON pending_checklist(broker_id, kind, ref_id);

CREATE TABLE IF NOT EXISTS premium_requests (
    id             TEXT PRIMARY KEY,
    broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
    tier_requested TEXT NOT NULL DEFAULT 'pro',
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    decided_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_premreq_broker ON premium_requests(broker_id);
CREATE INDEX IF NOT EXISTS idx_premreq_status ON premium_requests(status);
-- covers get_pending_premium_request(): broker + pending status
CREATE INDEX IF NOT EXISTS idx_premreq_broker_status
    ON premium_requests(broker_id, status);

-- anti-spam: escalating strike system (fully automatic, no admin involvement)
CREATE TABLE IF NOT EXISTS spam_strikes (
    broker_id    INTEGER PRIMARY KEY,
    strikes      INTEGER NOT NULL DEFAULT 0,
    last_strike_at REAL,
    muted_until  REAL NOT NULL DEFAULT 0,
    banned       INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

-- granular spam events for "3x in 1h" counting (spam_content, duplicate)
CREATE TABLE IF NOT EXISTS spam_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_id  INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spamev_broker_time
    ON spam_events(broker_id, created_at);
"""


def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=None):
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate_brokers(conn)
    _migrate_clients(conn)
    _migrate_viewings(conn)
    _migrate_match_requests(conn)
    _migrate_match_responses(conn)
    _migrate_listings_duplicate_of(conn)
    _migrate_updated_at(conn)
    _migrate_deals_paid(conn)
    _migrate_listings_content_hash(conn)
    _migrate_listings_saved_post(conn)
    conn.commit()
    conn.close()


def _migrate_updated_at(conn):
    """Add updated_at to tables that lacked it + backfill from created_at.

    Idempotent: skips columns/indexes that already exist. tg_events is
    deliberately excluded (append-only audit log — see SCHEMA note).
    Also creates the composite indexes added in the 2026-10-16 optimization
    pass for pre-existing DBs (fresh DBs get them from SCHEMA).
    """
    tables = ("brokers", "viewings", "deals", "templates",
              "match_responses", "pending_checklist", "premium_requests")
    for t in tables:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "updated_at" not in cols:
            conn.execute(
                f"ALTER TABLE {t} ADD COLUMN updated_at REAL NOT NULL DEFAULT 0"
            )
        # backfill anything still unset (0 from the default, or NULL)
        conn.execute(
            f"UPDATE {t} SET updated_at = created_at"
            " WHERE updated_at IS NULL OR updated_at = 0"
        )
    new_indexes = [
        ("idx_listings_broker_status_created",
         "CREATE INDEX IF NOT EXISTS idx_listings_broker_status_created"
         " ON tg_listings(broker_id, status, created_at)"),
        ("idx_viewings_broker_status_sched",
         "CREATE INDEX IF NOT EXISTS idx_viewings_broker_status_sched"
         " ON viewings(broker_id, status, scheduled_at)"),
        ("idx_viewings_client",
         "CREATE INDEX IF NOT EXISTS idx_viewings_client"
         " ON viewings(client_id)"),
        ("idx_deals_broker_closed",
         "CREATE INDEX IF NOT EXISTS idx_deals_broker_closed"
         " ON deals(broker_id, closed_at)"),
        ("idx_mreq_broker_client_status",
         "CREATE INDEX IF NOT EXISTS idx_mreq_broker_client_status"
         " ON match_requests(broker_id, client_id, status)"),
        ("idx_premreq_broker_status",
         "CREATE INDEX IF NOT EXISTS idx_premreq_broker_status"
         " ON premium_requests(broker_id, status)"),
    ]
    for _name, sql in new_indexes:
        conn.execute(sql)


def _migrate_clients(conn):
    """Add urgency + last_contact_at columns to clients (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
    if "urgency" not in cols:
        conn.execute(
            "ALTER TABLE clients ADD COLUMN urgency TEXT NOT NULL DEFAULT 'normal'"
        )
    if "last_contact_at" not in cols:
        conn.execute("ALTER TABLE clients ADD COLUMN last_contact_at REAL")
    if "sent_listings" not in cols:
        conn.execute(
            "ALTER TABLE clients ADD COLUMN sent_listings"
            " TEXT NOT NULL DEFAULT '[]'"
        )
    if "client_choice" not in cols:
        conn.execute(
            "ALTER TABLE clients ADD COLUMN client_choice"
            " TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clients_urgency ON clients(urgency)"
    )


def _migrate_viewings(conn):
    """Add listing_ids + feedback to viewings on pre-existing DBs."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(viewings)")}
    if "listing_ids" not in cols:
        conn.execute(
            "ALTER TABLE viewings ADD COLUMN listing_ids"
            " TEXT NOT NULL DEFAULT '[]'"
        )
    if "feedback" not in cols:
        conn.execute(
            "ALTER TABLE viewings ADD COLUMN feedback TEXT NOT NULL DEFAULT ''"
        )


def _migrate_brokers(conn):
    """Add contact + tier columns to brokers on pre-existing DBs (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(brokers)")}
    for col in ("name", "zalo", "facebook", "pronoun"):
        if col not in cols:
            conn.execute(f"ALTER TABLE brokers ADD COLUMN {col} TEXT")
    if "tier" not in cols:
        conn.execute(
            "ALTER TABLE brokers ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'"
        )
    if "tier_expires_at" not in cols:
        conn.execute("ALTER TABLE brokers ADD COLUMN tier_expires_at REAL")
    if "listing_limit" not in cols:
        conn.execute(
            "ALTER TABLE brokers ADD COLUMN listing_limit INTEGER NOT NULL"
            " DEFAULT 20"
        )
    # cross-broker match analytics (2026-10-16)
    for col, ddl in (
        ("match_requests_sent", "INTEGER NOT NULL DEFAULT 0"),
        ("match_responses_received", "INTEGER NOT NULL DEFAULT 0"),
        ("match_contacts_unlocked", "INTEGER NOT NULL DEFAULT 0"),
        ("last_match_at", "REAL"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE brokers ADD COLUMN {col} {ddl}")


def _migrate_match_requests(conn):
    """Add closed_reason + responses_seen_at to match_requests (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(match_requests)")}
    if "closed_reason" not in cols:
        conn.execute("ALTER TABLE match_requests ADD COLUMN closed_reason TEXT")
    if "responses_seen_at" not in cols:
        conn.execute("ALTER TABLE match_requests ADD COLUMN responses_seen_at REAL")


def _migrate_match_responses(conn):
    """Add listing_ids/match_scores to match_responses (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(match_responses)")}
    if "listing_ids" not in cols:
        conn.execute(
            "ALTER TABLE match_responses"
            " ADD COLUMN listing_ids TEXT NOT NULL DEFAULT '[]'"
        )
    if "match_scores" not in cols:
        conn.execute(
            "ALTER TABLE match_responses"
            " ADD COLUMN match_scores TEXT NOT NULL DEFAULT '{}'"
        )
    # mutual-consent flags for anonymous-until-consent relay (2026-10-16)
    for col in ("requester_consent", "responder_consent"):
        if col not in cols:
            conn.execute(
                f"ALTER TABLE match_responses ADD COLUMN {col}"
                " INTEGER NOT NULL DEFAULT 0"
            )


def _migrate_listings_duplicate_of(conn):
    """Add duplicate_of to tg_listings (nullable, no backfill needed)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_listings)")}
    if "duplicate_of" not in cols:
        conn.execute(
            "ALTER TABLE tg_listings ADD COLUMN duplicate_of TEXT"
        )


def _migrate_deals_paid(conn):
    """Add paid flag to deals for công nợ tracking (2026-10-16).

    0 = chưa thanh toán (công nợ), 1 = đã thanh toán.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(deals)")}
    if "paid" not in cols:
        conn.execute(
            "ALTER TABLE deals ADD COLUMN paid INTEGER NOT NULL DEFAULT 0"
        )


def _migrate_listings_content_hash(conn):
    """Add content_hash to tg_listings for exact-duplicate detection.

    sha256(normalized_text + sorted photo file_ids). Used to suggest
    (never auto-merge) when a broker forwards the same listing twice.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_listings)")}
    if "content_hash" not in cols:
        conn.execute(
            "ALTER TABLE tg_listings ADD COLUMN content_hash TEXT"
        )


def _migrate_listings_saved_post(conn):
    """Add saved_post to tg_listings.

    JSON object mapping language code -> generated FB post text,
    e.g. {"vi": "...", "en": "..."}. Vietnamese is auto-generated at
    submit time; other languages are added on demand from the write menu.
    The write-post menu only shows listings that have a saved post.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_listings)")}
    if "saved_post" not in cols:
        conn.execute(
            "ALTER TABLE tg_listings ADD COLUMN saved_post"
            " TEXT NOT NULL DEFAULT ''"
        )


def _now():
    return time.time()


# ---------------------------------------------------------------- brokers

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
               "tier", "tier_expires_at", "listing_limit",
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


# ---- cross-broker match analytics (2026-10-16) ----

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


# ---------------------------------------------------------------- tiers

TIER_ORDER = {"free": 0, "pro": 1, "max": 2, "enterprise": 3}

# Brokers managing more than this many active listings need Enterprise tier.
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
    if tier_allows(broker_id, "enterprise", path=path):
        return False
    return active_listing_count(broker_id, path=path) > \
        ENTERPRISE_LISTING_THRESHOLD


def active_listing_count(broker_id, path=None):
    """Count of non-deleted, non-draft listings (what the free limit applies to)."""
    return count_broker_listings(
        broker_id, statuses=("submitted", "pending_info", "negotiating",
                             "deposited", "rented", "active"),
        path=path)


def check_listing_limit(broker_id, path=None):
    """(ok, count, limit) — free tier capped, paid tiers unlimited."""
    tier = get_tier(broker_id, path=path)
    if tier != "free":
        return True, active_listing_count(broker_id, path=path), 0
    limit = (get_broker(broker_id, path=path) or {}).get("listing_limit") \
        or config.FREE_LISTING_LIMIT
    count = active_listing_count(broker_id, path=path)
    return count < limit, count, limit


# ---------------------------------------------------------------- premium requests

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


# ---------------------------------------------------------------- listings

def create_listing(broker_id, raw_text="", photo_file_ids=None,
                   parsed=None, missing_fields=None, status="draft",
                   content_hash=None, path=None):
    listing_id = "tg:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO tg_listings (id, broker_id, raw_text, photo_file_ids,"
        " parsed, missing_fields, status, content_hash, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (listing_id, broker_id, raw_text,
         json.dumps(photo_file_ids or [], ensure_ascii=False),
         json.dumps(parsed or {}, ensure_ascii=False),
         json.dumps(missing_fields or [], ensure_ascii=False),
         status, content_hash, now, now),
    )
    conn.execute(
        "UPDATE brokers SET listings_count = listings_count + 1"
        " WHERE user_id = ?", (broker_id,),
    )
    conn.execute(
        "INSERT INTO tg_events (listing_id, old_status, new_status, changed_by, created_at)"
        " VALUES (?, NULL, ?, 'broker', ?)",
        (listing_id, status, now),
    )
    if status == "submitted":
        # created directly as submitted (no missing fields) — count it,
        # since set_listing_status's draft/pending_info→submitted path won't fire
        conn.execute(
            "UPDATE brokers SET approved_count = approved_count + 1"
            " WHERE user_id = ?", (broker_id,),
        )
    conn.commit()
    conn.close()
    return listing_id


def get_listing(listing_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM tg_listings WHERE id = ?", (listing_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["photo_file_ids"] = json.loads(d["photo_file_ids"])
    d["parsed"] = json.loads(d["parsed"])
    d["missing_fields"] = json.loads(d["missing_fields"])
    return d


def update_listing(listing_id, path=None, **fields):
    allowed = {"raw_text", "photo_file_ids", "parsed", "missing_fields",
               "status", "view_count", "inquiry_count", "duplicate_of",
               "content_hash", "saved_post"}
    json_fields = {"photo_file_ids", "parsed", "missing_fields"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in json_fields:
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(listing_id)
    conn = connect(path)
    conn.execute(
        f"UPDATE tg_listings SET {', '.join(sets)} WHERE id = ?", vals
    )
    conn.commit()
    conn.close()


def set_listing_status(listing_id, new_status, changed_by="broker", path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT status, broker_id FROM tg_listings WHERE id = ?", (listing_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    old_status = row["status"]
    if old_status == new_status:
        conn.close()
        return True
    now = _now()
    conn.execute(
        "UPDATE tg_listings SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, listing_id),
    )
    conn.execute(
        "INSERT INTO tg_events (listing_id, old_status, new_status, changed_by, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (listing_id, old_status, new_status, changed_by, now),
    )
    if new_status == "submitted" and old_status in ("draft", "pending_info"):
        # first-time submission only — toggling negotiating/deposited/rented
        # back to submitted must not inflate the qualification counter
        conn.execute(
            "UPDATE brokers SET approved_count = approved_count + 1"
            " WHERE user_id = ?", (row["broker_id"],),
        )
    conn.commit()
    conn.close()
    return True


def update_listing_field(listing_id, field, value, changed_by="broker", path=None):
    """Update one listing field and log the edit to tg_events for audit.

    field: a key inside the `parsed` JSON (e.g. 'price_vnd'), or the
    special cases:
      - 'description' -> updates raw_text
      - 'location'    -> value is a dict with any of
                         district / street / building_name, merged into parsed

    After the update, the field is dropped from missing_fields if now
    filled. If the listing was pending_info and nothing is missing any
    more, it is promoted to 'submitted'. Returns False if not found.
    """
    conn = connect(path)
    row = conn.execute(
        "SELECT parsed, raw_text, missing_fields, status FROM tg_listings"
        " WHERE id = ?", (listing_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    parsed = json.loads(row["parsed"])
    missing = json.loads(row["missing_fields"])
    status = row["status"]
    now = _now()

    def _filled(v):
        return v is not None and v != "" and v != {}

    if field == "description":
        _log_field_edit(conn, listing_id, "description",
                        row["raw_text"], value, changed_by, now)
        conn.execute(
            "UPDATE tg_listings SET raw_text = ?, updated_at = ? WHERE id = ?",
            (value, now, listing_id),
        )
        if _filled(value) and "description" in missing:
            missing.remove("description")
    elif field == "location" and isinstance(value, dict):
        for k in ("district", "street", "building_name"):
            if k in value:
                _log_field_edit(conn, listing_id, k, parsed.get(k),
                                value[k], changed_by, now)
                parsed[k] = value[k]
        conn.execute(
            "UPDATE tg_listings SET parsed = ?, updated_at = ? WHERE id = ?",
            (json.dumps(parsed, ensure_ascii=False), now, listing_id),
        )
    else:
        _log_field_edit(conn, listing_id, field, parsed.get(field),
                        value, changed_by, now)
        parsed[field] = value
        conn.execute(
            "UPDATE tg_listings SET parsed = ?, updated_at = ? WHERE id = ?",
            (json.dumps(parsed, ensure_ascii=False), now, listing_id),
        )
        if _filled(value) and field in missing:
            missing.remove(field)

    conn.execute(
        "UPDATE tg_listings SET missing_fields = ? WHERE id = ?",
        (json.dumps(missing, ensure_ascii=False), listing_id),
    )

    # promote to submitted when the last missing field got filled
    if status == "pending_info" and not missing:
        conn.execute(
            "UPDATE tg_listings SET status = ?, updated_at = ? WHERE id = ?",
            ("submitted", now, listing_id),
        )
        conn.execute(
            "INSERT INTO tg_events (listing_id, old_status, new_status,"
            " changed_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (listing_id, "pending_info", "submitted", changed_by, now),
        )

    conn.commit()
    conn.close()
    return True


def _log_field_edit(conn, listing_id, field, old, new, changed_by, now):
    """Audit-trail entry for a field edit, reusing tg_events."""
    conn.execute(
        "INSERT INTO tg_events (listing_id, old_status, new_status,"
        " changed_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (listing_id, f"edit:{field}:{old}", f"edit:{field}:{new}",
         changed_by, now),
    )


def touch_listing(listing_id, path=None):
    """Refresh a listing: bump created_at/updated_at to now (repost).
    Used by the 'Làm mới tin' button for stale (>30d) listings."""
    now = _now()
    conn = connect(path)
    conn.execute(
        "UPDATE tg_listings SET created_at = ?, updated_at = ? WHERE id = ?",
        (now, now, listing_id),
    )
    conn.commit()
    conn.close()


def list_broker_listings(broker_id, limit=5, offset=0, statuses=None, path=None):
    conn = connect(path)
    if statuses:
        ph = ", ".join("?" for _ in statuses)
        rows = conn.execute(
            f"SELECT * FROM tg_listings WHERE broker_id = ? AND status IN ({ph})"
            " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (broker_id, *statuses, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tg_listings WHERE broker_id = ?"
            " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (broker_id, limit, offset),
        ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = json.loads(d["parsed"])
        d["missing_fields"] = json.loads(d["missing_fields"])
        out.append(d)
    return out


def _parse_saved_post(raw):
    """Parse the saved_post JSON column into a {lang: text} dict."""
    if not raw or not raw.strip():
        return {}
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(v, str) and v.strip()}


def save_post(listing_id, post_text, lang="vi", path=None):
    """Save a generated FB post for a language. Merges into existing
    languages — never overwrites other languages' posts."""
    l = get_listing(listing_id, path=path)
    if not l:
        return False
    posts = _parse_saved_post(l.get("saved_post"))
    posts[lang or "vi"] = post_text or ""
    # drop emptied languages
    posts = {k: v for k, v in posts.items() if v.strip()}
    update_listing(listing_id, path=path,
                   saved_post=json.dumps(posts, ensure_ascii=False))
    return True


def get_saved_post(listing_id, lang="vi", path=None):
    """Return the saved post text for a language, or None if missing."""
    l = get_listing(listing_id, path=path)
    if not l:
        return None
    posts = _parse_saved_post(l.get("saved_post"))
    text = (posts.get(lang or "vi") or "").strip()
    return text or None


def get_saved_post_langs(listing_id, path=None):
    """Return list of language codes that have a saved post, e.g. ['vi', 'en'].
    Vietnamese first, then alphabetical."""
    l = get_listing(listing_id, path=path)
    if not l:
        return []
    posts = _parse_saved_post(l.get("saved_post"))
    langs = [k for k in posts if posts[k].strip()]
    langs.sort(key=lambda k: (k != "vi", k))
    return langs


def has_saved_post(listing_id, path=None):
    """True if the listing has at least one saved post."""
    return bool(get_saved_post_langs(listing_id, path=path))


def list_broker_listings_with_posts(broker_id, limit=5, offset=0,
                                    statuses=None, path=None):
    """Listings that have at least one saved FB post.
    Same shape as list_broker_listings."""
    conn = connect(path)
    status_clause = ""
    params = [broker_id]
    if statuses:
        ph = ", ".join("?" for _ in statuses)
        status_clause = f" AND status IN ({ph})"
        params.extend(statuses)
    params.extend([limit, offset])
    rows = conn.execute(
        "SELECT * FROM tg_listings WHERE broker_id = ?"
        " AND saved_post != '' AND saved_post != '{}'" + status_clause +
        " ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = json.loads(d["parsed"])
        d["missing_fields"] = json.loads(d["missing_fields"])
        out.append(d)
    return out


def count_broker_listings(broker_id, statuses=None, path=None):
    conn = connect(path)
    if statuses:
        ph = ", ".join("?" for _ in statuses)
        n = conn.execute(
            f"SELECT COUNT(*) c FROM tg_listings WHERE broker_id = ? AND status IN ({ph})",
            (broker_id, *statuses),
        ).fetchone()["c"]
    else:
        n = conn.execute(
            "SELECT COUNT(*) c FROM tg_listings WHERE broker_id = ?",
            (broker_id,),
        ).fetchone()["c"]
    conn.close()
    return n


def count_recent_listings(broker_id, hours=1, path=None):
    """How many listings this broker submitted in the last N hours (rate limit)."""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM tg_listings"
        " WHERE broker_id = ? AND created_at > ?",
        (broker_id, _now() - hours * 3600),
    ).fetchone()["c"]
    conn.close()
    return n


def search_listings(broker_id, filters, limit=50, offset=0, path=None):
    """Search a broker's listings by parsed-field filters.

    filters keys: bedrooms (float), min_bedrooms (float, for 4PN+),
    min_price, max_price (VND float),
    district (str), building_name (str), pet_friendly (bool),
    property_type (str), status ("active" | "rented" | exact status).
    "active" expands to draft/pending_info/submitted.
    "inactive" expands to rented/negotiating/deposited.
    """
    ACTIVE = ("draft", "pending_info", "submitted")
    INACTIVE = ("rented", "negotiating", "deposited")
    conds = ["broker_id = ?"]
    vals = [broker_id]

    st = filters.get("status")
    if st == "active":
        ph = ", ".join("?" for _ in ACTIVE)
        conds.append(f"status IN ({ph})")
        vals.extend(ACTIVE)
    elif st == "inactive":
        ph = ", ".join("?" for _ in INACTIVE)
        conds.append(f"status IN ({ph})")
        vals.extend(INACTIVE)
    elif st == "rented":
        conds.append("status = ?")
        vals.append("rented")
    elif isinstance(st, str):
        conds.append("status = ?")
        vals.append(st)
    else:
        # default: hide deleted
        conds.append("status != 'deleted'")

    if "bedrooms" in filters:
        conds.append("CAST(json_extract(parsed, '$.bedrooms') AS REAL) = ?")
        vals.append(float(filters["bedrooms"]))
    if "min_bedrooms" in filters:
        conds.append("CAST(json_extract(parsed, '$.bedrooms') AS REAL) >= ?")
        vals.append(float(filters["min_bedrooms"]))
    if "min_price" in filters:
        conds.append("CAST(json_extract(parsed, '$.price_vnd') AS REAL) >= ?")
        vals.append(float(filters["min_price"]))
    if "max_price" in filters:
        conds.append("CAST(json_extract(parsed, '$.price_vnd') AS REAL) <= ?")
        vals.append(float(filters["max_price"]))
    if "district" in filters:
        conds.append("json_extract(parsed, '$.district') = ?")
        vals.append(filters["district"])
    if "building_name" in filters:
        conds.append("json_extract(parsed, '$.building_name') = ?")
        vals.append(filters["building_name"])
    if "pet_friendly" in filters:
        conds.append("json_extract(parsed, '$.pet_friendly') = ?")
        vals.append(1 if filters["pet_friendly"] else 0)
    if "property_type" in filters:
        conds.append("json_extract(parsed, '$.property_type') = ?")
        vals.append(filters["property_type"])

    sql = ("SELECT * FROM tg_listings WHERE " + " AND ".join(conds) +
           " ORDER BY created_at DESC LIMIT ? OFFSET ?")
    vals.extend([limit, offset])

    conn = connect(path)
    rows = conn.execute(sql, vals).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = json.loads(d["parsed"])
        d["missing_fields"] = json.loads(d["missing_fields"])
        out.append(d)
    return out


def count_search(broker_id, filters, path=None):
    """COUNT(*) for the same filter set as search_listings()."""
    ACTIVE = ("draft", "pending_info", "submitted")
    INACTIVE = ("rented", "negotiating", "deposited")
    conds = ["broker_id = ?"]
    vals = [broker_id]

    st = filters.get("status")
    if st == "active":
        ph = ", ".join("?" for _ in ACTIVE)
        conds.append(f"status IN ({ph})")
        vals.extend(ACTIVE)
    elif st == "inactive":
        ph = ", ".join("?" for _ in INACTIVE)
        conds.append(f"status IN ({ph})")
        vals.extend(INACTIVE)
    elif st == "rented":
        conds.append("status = ?")
        vals.append("rented")
    elif isinstance(st, str):
        conds.append("status = ?")
        vals.append(st)
    else:
        conds.append("status != 'deleted'")

    if "bedrooms" in filters:
        conds.append("CAST(json_extract(parsed, '$.bedrooms') AS REAL) = ?")
        vals.append(float(filters["bedrooms"]))
    if "min_bedrooms" in filters:
        conds.append("CAST(json_extract(parsed, '$.bedrooms') AS REAL) >= ?")
        vals.append(float(filters["min_bedrooms"]))
    if "min_price" in filters:
        conds.append("CAST(json_extract(parsed, '$.price_vnd') AS REAL) >= ?")
        vals.append(float(filters["min_price"]))
    if "max_price" in filters:
        conds.append("CAST(json_extract(parsed, '$.price_vnd') AS REAL) <= ?")
        vals.append(float(filters["max_price"]))
    if "district" in filters:
        conds.append("json_extract(parsed, '$.district') = ?")
        vals.append(filters["district"])
    if "building_name" in filters:
        conds.append("json_extract(parsed, '$.building_name') = ?")
        vals.append(filters["building_name"])
    if "pet_friendly" in filters:
        conds.append("json_extract(parsed, '$.pet_friendly') = ?")
        vals.append(1 if filters["pet_friendly"] else 0)
    if "property_type" in filters:
        conds.append("json_extract(parsed, '$.property_type') = ?")
        vals.append(filters["property_type"])

    sql = "SELECT COUNT(*) c FROM tg_listings WHERE " + " AND ".join(conds)
    conn = connect(path)
    n = conn.execute(sql, vals).fetchone()["c"]
    conn.close()
    return n


def stale_listings(older_than_days=7, statuses=("submitted",), path=None):
    """Listings not updated in N days — candidates for availability nudge."""
    conn = connect(path)
    ph = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT l.*, b.username, b.display_name FROM tg_listings l"
        f" JOIN brokers b ON b.user_id = l.broker_id"
        f" WHERE l.status IN ({ph}) AND l.updated_at < ?"
        " ORDER BY l.updated_at ASC",
        (*statuses, _now() - older_than_days * 86400),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = json.loads(d["parsed"])
        out.append(d)
    return out


def find_potential_duplicates(broker_id, parsed, exclude_id=None, path=None):
    """Find existing listings that look like duplicates of a new one.

    Match criteria (all must hold):
      - same broker, status in (submitted, uncertain), not deleted
      - bedrooms equal (both known)
      - price within ±10% (both known)
      - district equal (both known), OR building_name equal (both known)

    Returns list of listing dicts (newest first). Never auto-merges —
    caller must ask the broker to confirm.
    """
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM tg_listings WHERE broker_id = ?"
        " AND status IN ('submitted', 'uncertain')"
        " AND (duplicate_of IS NULL OR duplicate_of = '')",
        (broker_id,),
    ).fetchall()
    conn.close()

    br = parsed.get("bedrooms")
    price = parsed.get("price_vnd")
    district = (parsed.get("district") or "").strip().lower()
    building = (parsed.get("building_name") or "").strip().lower()

    out = []
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        try:
            op = json.loads(r["parsed"])
        except (TypeError, ValueError):
            continue
        obr = op.get("bedrooms")
        oprice = op.get("price_vnd")
        odistrict = (op.get("district") or "").strip().lower()
        obuilding = (op.get("building_name") or "").strip().lower()

        # bedrooms must match when both known
        if br is not None and obr is not None and float(br) != float(obr):
            continue
        # price within ±10% when both known
        if price and oprice:
            if abs(float(price) - float(oprice)) / float(oprice) > 0.10:
                continue
        # location: same building OR same district (both known)
        loc_match = False
        if building and obuilding and building == obuilding:
            loc_match = True
        elif district and odistrict and district == odistrict:
            loc_match = True
        if not loc_match:
            continue
        # need at least bedrooms or price to agree to avoid over-matching
        if br is None and not price:
            continue

        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = op
        d["missing_fields"] = json.loads(d["missing_fields"])
        out.append(d)
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def find_exact_duplicate_by_hash(broker_id, content_hash, exclude_id=None,
                                 days=30, path=None):
    """Find a listing with the exact same content hash (same broker, recent).

    Used to suggest (never auto-merge) when a broker forwards the same
    listing twice. Returns the newest matching listing dict, or None.
    """
    if not content_hash:
        return None
    cutoff = _now() - days * 86400
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM tg_listings WHERE broker_id = ?"
        " AND content_hash = ?"
        " AND created_at >= ?"
        " AND status != 'deleted'"
        " ORDER BY created_at DESC LIMIT 2",
        (broker_id, content_hash, cutoff),
    ).fetchall()
    conn.close()
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        d = dict(r)
        d["photo_file_ids"] = json.loads(d["photo_file_ids"])
        d["parsed"] = json.loads(d["parsed"])
        d["missing_fields"] = json.loads(d["missing_fields"])
        return d
    return None


# ---------------------------------------------------------------- clients

CLIENT_STATUSES = ("new", "sent", "pending_viewing", "scheduled", "viewed",
                   "negotiating", "deposited", "contracted", "rented",
                   "cancelled",
                   # legacy status kept readable for old rows
                   "viewing")


def create_client(broker_id, name="", phone="", requirements_raw="",
                  requirements=None, urgency="normal", path=None):
    """Create a client. requirements is a parse_query-style filter dict.
    urgency: 'urgent' | 'normal' | 'low'."""
    if urgency not in ("urgent", "normal", "low"):
        urgency = "normal"
    client_id = "cli:" + uuid.uuid4().hex[:12]
    now = _now()
    r = requirements or {}
    conn = connect(path)
    conn.execute(
        "INSERT INTO clients (id, broker_id, name, phone, budget_min,"
        " budget_max, bedrooms, district, property_type, requirements_raw,"
        " status, urgency, notes, viewed_listings, created_at, updated_at,"
        " last_contact_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, '', '[]', ?, ?, ?)",
        (client_id, broker_id, name, phone,
         r.get("min_price"), r.get("max_price"), r.get("bedrooms"),
         r.get("district"), r.get("property_type"), requirements_raw,
         urgency, now, now, now),
    )
    conn.commit()
    conn.close()
    return client_id


def touch_contact(client_id, path=None):
    """Mark now as the last time the broker contacted this client."""
    conn = connect(path)
    cur = conn.execute(
        "UPDATE clients SET last_contact_at = ?, updated_at = ? WHERE id = ?",
        (_now(), _now(), client_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_client(client_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["viewed_listings"] = json.loads(d["viewed_listings"])
    try:
        d["sent_listings"] = json.loads(d.get("sent_listings") or "[]")
    except (ValueError, TypeError):
        d["sent_listings"] = []
    try:
        d["client_choice"] = json.loads(d.get("client_choice") or "")
    except (ValueError, TypeError):
        d["client_choice"] = None
    return d


def list_clients(broker_id, status=None, urgency=None, limit=50, offset=0,
                 path=None):
    """List clients, urgency-first (urgent → normal → low), then newest."""
    conds = ["broker_id = ?"]
    vals = [broker_id]
    if status:
        conds.append("status = ?")
        vals.append(status)
    if urgency:
        conds.append("urgency = ?")
        vals.append(urgency)
    sql = (
        "SELECT * FROM clients WHERE " + " AND ".join(conds) +
        " ORDER BY CASE urgency WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1"
        " ELSE 2 END, updated_at DESC LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])
    conn = connect(path)
    rows = conn.execute(sql, vals).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["viewed_listings"] = json.loads(d["viewed_listings"])
        out.append(d)
    return out


def count_clients(broker_id, status=None, urgency=None, path=None):
    conn = connect(path)
    conds = ["broker_id = ?"]
    vals = [broker_id]
    if status:
        conds.append("status = ?")
        vals.append(status)
    if urgency:
        conds.append("urgency = ?")
        vals.append(urgency)
    n = conn.execute(
        "SELECT COUNT(*) c FROM clients WHERE " + " AND ".join(conds),
        vals,
    ).fetchone()["c"]
    conn.close()
    return n


def stale_clients(broker_id, days=3, limit=20, path=None):
    """Clients not contacted for `days`+ days (uses last_contact_at,
    falling back to created_at), excluding closed ones."""
    cutoff = _now() - days * 86400
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM clients WHERE broker_id = ?"
        " AND status NOT IN ('rented', 'cancelled')"
        " AND COALESCE(last_contact_at, created_at) < ?"
        " ORDER BY COALESCE(last_contact_at, created_at) ASC LIMIT ?",
        (broker_id, cutoff, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["viewed_listings"] = json.loads(d["viewed_listings"])
        out.append(d)
    return out


def idle_new_clients(broker_id, days=2, limit=20, path=None):
    """Clients added `days`+ days ago that were never sent any listing."""
    cutoff = _now() - days * 86400
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM clients WHERE broker_id = ?"
        " AND status NOT IN ('rented', 'cancelled')"
        " AND created_at < ?"
        " AND (viewed_listings IS NULL OR viewed_listings = '[]')"
        " ORDER BY created_at ASC LIMIT ?",
        (broker_id, cutoff, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["viewed_listings"] = json.loads(d["viewed_listings"])
        out.append(d)
    return out


def list_brokers(path=None):
    """All brokers — for cron scripts that fan out per broker."""
    conn = connect(path)
    rows = conn.execute("SELECT * FROM brokers").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_client(client_id, path=None, **fields):
    """Update client fields. requirements=parse_query dict refreshes the
    requirement columns + requirements_raw."""
    allowed = {"name", "phone", "budget_min", "budget_max", "bedrooms",
               "district", "property_type", "requirements_raw", "status",
               "urgency"}
    sets, vals = [], []
    if "requirements" in fields:
        r = fields.pop("requirements") or {}
        fields["budget_min"] = r.get("min_price")
        fields["budget_max"] = r.get("max_price")
        fields["bedrooms"] = r.get("bedrooms")
        fields["district"] = r.get("district")
        fields["property_type"] = r.get("property_type")
    if "urgency" in fields and fields["urgency"] not in ("urgent", "normal",
                                                         "low"):
        fields["urgency"] = "normal"
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(client_id)
    conn = connect(path)
    cur = conn.execute(
        f"UPDATE clients SET {', '.join(sets)} WHERE id = ?", vals
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def add_note(client_id, note, path=None):
    """Append a timestamped note (append-only)."""
    conn = connect(path)
    row = conn.execute(
        "SELECT notes FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    ts = time.strftime("%d/%m %H:%M", time.localtime(_now()))
    entry = f"[{ts}] {note.strip()}"
    notes = (row["notes"] + "\n" + entry).strip() if row["notes"] else entry
    conn.execute(
        "UPDATE clients SET notes = ?, updated_at = ?, last_contact_at = ?"
        " WHERE id = ?",
        (notes, _now(), _now(), client_id),
    )
    conn.commit()
    conn.close()
    return True


def link_listing(client_id, listing_id, path=None):
    """Record that a client viewed / was sent a listing."""
    conn = connect(path)
    row = conn.execute(
        "SELECT viewed_listings FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    seen = json.loads(row["viewed_listings"])
    if listing_id not in seen:
        seen.append(listing_id)
    conn.execute(
        "UPDATE clients SET viewed_listings = ?, updated_at = ?,"
        " last_contact_at = ? WHERE id = ?",
        (json.dumps(seen, ensure_ascii=False), _now(), _now(), client_id),
    )
    conn.commit()
    conn.close()
    return True


def record_sent_listings(client_id, listing_ids, path=None):
    """Append listings to the client's sent_listings with sent_at timestamp."""
    conn = connect(path)
    row = conn.execute(
        "SELECT sent_listings FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    try:
        sent = json.loads(row["sent_listings"] or "[]")
    except (ValueError, TypeError):
        sent = []
    now = _now()
    have = {s.get("id") for s in sent}
    for lid in listing_ids:
        if lid not in have:
            sent.append({"id": lid, "sent_at": now})
            have.add(lid)
    conn.execute(
        "UPDATE clients SET sent_listings = ?, updated_at = ?,"
        " last_contact_at = ? WHERE id = ?",
        (json.dumps(sent, ensure_ascii=False), now, now, client_id),
    )
    conn.commit()
    conn.close()
    return True


def record_client_choice(client_id, listing_id, path=None):
    """Record which sent listing the client chose."""
    conn = connect(path)
    now = _now()
    cur = conn.execute(
        "UPDATE clients SET client_choice = ?, updated_at = ?,"
        " last_contact_at = ? WHERE id = ?",
        (json.dumps({"id": listing_id, "chosen_at": now},
                    ensure_ascii=False), now, now, client_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def clear_client_choice(client_id, path=None):
    """Clear the recorded choice (e.g. client changed their mind)."""
    conn = connect(path)
    cur = conn.execute(
        "UPDATE clients SET client_choice = '', updated_at = ? WHERE id = ?",
        (_now(), client_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def clients_awaiting_choice(broker_id, days=2, limit=20, path=None):
    """Clients with sent listings but no recorded choice, sent >= days ago."""
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM clients WHERE broker_id = ?"
        " AND sent_listings != '[]' AND (client_choice IS NULL"
        " OR client_choice = '')",
        (broker_id,),
    ).fetchall()
    conn.close()
    out = []
    cutoff = _now() - days * 86400
    for r in rows:
        try:
            sent = json.loads(r["sent_listings"] or "[]")
        except (ValueError, TypeError):
            continue
        if not sent:
            continue
        latest = max((s.get("sent_at") or 0) for s in sent)
        if latest <= cutoff:
            d = dict(r)
            d["viewed_listings"] = json.loads(d["viewed_listings"])
            d["sent_listings"] = sent
            d["client_choice"] = None
            out.append(d)
        if len(out) >= limit:
            break
    return out


def delete_client(client_id, path=None):
    conn = connect(path)
    cur = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ---------------------------------------------------------------- viewings

VIEWING_STATUSES = ("scheduled", "done", "cancelled")


def create_viewing(broker_id, client_id=None, client_name="", listing_id=None,
                   listing_ids=None, scheduled_at=None, notes="", path=None):
    """Create a viewing. listing_ids (list) is the multi-listing field;
    listing_id is kept for backward compatibility (first of the list)."""
    viewing_id = "vw:" + uuid.uuid4().hex[:12]
    now = _now()
    ids = list(listing_ids) if listing_ids else []
    if listing_id and listing_id not in ids:
        ids.insert(0, listing_id)
    conn = connect(path)
    conn.execute(
        "INSERT INTO viewings (id, broker_id, client_id, client_name,"
        " listing_id, listing_ids, scheduled_at, status, notes, feedback,"
        " created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, '', ?, ?)",
        (viewing_id, broker_id, client_id, client_name, ids[0] if ids else None,
         json.dumps(ids, ensure_ascii=False), scheduled_at or now, notes,
         now, now),
    )
    conn.commit()
    conn.close()
    return viewing_id


def _parse_viewing_row(row):
    d = dict(row)
    try:
        d["listing_ids"] = json.loads(d.get("listing_ids") or "[]")
    except (ValueError, TypeError):
        d["listing_ids"] = []
    if not d["listing_ids"] and d.get("listing_id"):
        d["listing_ids"] = [d["listing_id"]]
    return d


def get_viewing(viewing_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM viewings WHERE id = ?", (viewing_id,)
    ).fetchone()
    conn.close()
    return _parse_viewing_row(row) if row else None


def list_viewings(broker_id, upcoming_only=True, limit=20, path=None):
    """Upcoming viewings (scheduled, future), soonest first."""
    conn = connect(path)
    if upcoming_only:
        rows = conn.execute(
            "SELECT * FROM viewings WHERE broker_id = ? AND status = 'scheduled'"
            " AND scheduled_at >= ? ORDER BY scheduled_at ASC LIMIT ?",
            (broker_id, _now(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM viewings WHERE broker_id = ?"
            " ORDER BY scheduled_at DESC LIMIT ?",
            (broker_id, limit),
        ).fetchall()
    conn.close()
    return [_parse_viewing_row(r) for r in rows]


def update_viewing(viewing_id, path=None, **fields):
    allowed = {"client_id", "client_name", "listing_id", "listing_ids",
               "scheduled_at", "status", "notes", "feedback"}
    if "listing_ids" in fields and isinstance(fields["listing_ids"], list):
        fields["listing_ids"] = json.dumps(fields["listing_ids"],
                                           ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    if not sets:
        return False
    vals = [fields[k] for k in fields if k in allowed]
    sets += ", updated_at = ?"
    vals.append(_now())
    vals.append(viewing_id)
    conn = connect(path)
    cur = conn.execute(
        f"UPDATE viewings SET {sets} WHERE id = ?", vals
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_viewing(viewing_id, path=None):
    conn = connect(path)
    cur = conn.execute("DELETE FROM viewings WHERE id = ?", (viewing_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def due_viewings(within_seconds=3600, path=None):
    """Scheduled viewings starting within the next N seconds — for reminders."""
    now = _now()
    conn = connect(path)
    rows = conn.execute(
        "SELECT v.*, b.username, b.display_name, b.pronoun FROM viewings v"
        " JOIN brokers b ON b.user_id = v.broker_id"
        " WHERE v.status = 'scheduled'"
        " AND v.scheduled_at > ? AND v.scheduled_at <= ?"
        " ORDER BY v.scheduled_at ASC",
        (now, now + within_seconds),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def due_feedback_viewings(hours_after=0, hours_before=24, path=None):
    """Viewings that ended hours_after..hours_before ago, still scheduled
    and without feedback — prompt the broker for post-viewing feedback."""
    now = _now()
    conn = connect(path)
    rows = conn.execute(
        "SELECT v.*, b.username, b.display_name, b.pronoun FROM viewings v"
        " JOIN brokers b ON b.user_id = v.broker_id"
        " WHERE v.status = 'scheduled'"
        " AND v.scheduled_at <= ? AND v.scheduled_at > ?"
        " AND (v.feedback IS NULL OR v.feedback = '')"
        " ORDER BY v.scheduled_at DESC",
        (now - hours_after * 3600, now - hours_before * 3600),
    ).fetchall()
    conn.close()
    return [_parse_viewing_row(r) for r in rows]


def unfeedbacked_viewings(broker_id, min_hours=24, max_hours=72, path=None):
    """Past viewings (min..max hours ago) still missing feedback — nag list."""
    now = _now()
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM viewings WHERE broker_id = ? AND status = 'scheduled'"
        " AND scheduled_at <= ? AND scheduled_at > ?"
        " AND (feedback IS NULL OR feedback = '')"
        " ORDER BY scheduled_at DESC",
        (broker_id, now - min_hours * 3600, now - max_hours * 3600),
    ).fetchall()
    conn.close()
    return [_parse_viewing_row(r) for r in rows]


def client_viewings(client_id, path=None):
    """All viewings for a client that actually have listings attached,
    newest first. Used for the follow-up reminder display."""
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM viewings WHERE client_id = ?"
        " AND (listing_ids IS NOT NULL AND listing_ids != '[]'"
        " OR listing_id IS NOT NULL)"
        " ORDER BY scheduled_at DESC",
        (client_id,),
    ).fetchall()
    conn.close()
    return [_parse_viewing_row(r) for r in rows]


def viewings_between(broker_id, start_ts, end_ts, path=None):
    """Viewings scheduled within [start_ts, end_ts) — for daily summary."""
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM viewings WHERE broker_id = ?"
        " AND scheduled_at >= ? AND scheduled_at < ?"
        " ORDER BY scheduled_at ASC",
        (broker_id, start_ts, end_ts),
    ).fetchall()
    conn.close()
    return [_parse_viewing_row(r) for r in rows]


def count_listings_created(broker_id, start_ts, end_ts, path=None):
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM tg_listings WHERE broker_id = ?"
        " AND status != 'draft' AND created_at >= ? AND created_at < ?",
        (broker_id, start_ts, end_ts),
    ).fetchone()["c"]
    conn.close()
    return n


def deals_closed_between(broker_id, start_ts, end_ts, path=None):
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM deals WHERE broker_id = ?"
        " AND closed_at >= ? AND closed_at < ? ORDER BY closed_at DESC",
        (broker_id, start_ts, end_ts),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- deals

def create_deal(broker_id, client_id=None, client_name="", listing_id=None,
                commission_vnd=None, closed_at=None, notes="", path=None):
    deal_id = "deal:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO deals (id, broker_id, client_id, client_name, listing_id,"
        " commission_vnd, closed_at, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (deal_id, broker_id, client_id, client_name, listing_id,
         commission_vnd, closed_at or now, notes, now, now),
    )
    conn.commit()
    conn.close()
    return deal_id


def get_deal(deal_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM deals WHERE id = ?", (deal_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_deals(broker_id, start_ts=None, end_ts=None, limit=100, path=None):
    conn = connect(path)
    conds = ["broker_id = ?"]
    vals = [broker_id]
    if start_ts is not None:
        conds.append("closed_at >= ?")
        vals.append(start_ts)
    if end_ts is not None:
        conds.append("closed_at < ?")
        vals.append(end_ts)
    rows = conn.execute(
        "SELECT * FROM deals WHERE " + " AND ".join(conds) +
        " ORDER BY closed_at DESC LIMIT ?",
        (*vals, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_deal(deal_id, path=None):
    conn = connect(path)
    cur = conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def unpaid_deals(broker_id, path=None):
    """Unpaid deals (công nợ) for a broker, oldest first.

    Only deals with a positive commission count — zero/None commissions
    are not debts.
    """
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM deals WHERE broker_id = ? AND paid = 0"
        " AND commission_vnd > 0 ORDER BY closed_at ASC",
        (broker_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_unpaid_debt(broker_id, path=None):
    """True if the broker has any unpaid deal (công nợ)."""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM deals WHERE broker_id = ? AND paid = 0"
        " AND commission_vnd > 0",
        (broker_id,),
    ).fetchone()["c"]
    conn.close()
    return n > 0


def mark_deal_paid(deal_id, path=None):
    """Mark a deal as paid. Returns True if a row was updated."""
    conn = connect(path)
    cur = conn.execute(
        "UPDATE deals SET paid = 1, updated_at = ? WHERE id = ?",
        (_now(), deal_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def deal_exists(broker_id, client_id, listing_id, path=None):
    """Already recorded a deal for this client+listing pair?"""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM deals WHERE broker_id = ? AND client_id = ?"
        " AND listing_id = ?",
        (broker_id, client_id, listing_id),
    ).fetchone()["c"]
    conn.close()
    return n > 0


def suggested_deal_pairs(broker_id, path=None):
    """Candidate (client, listing) pairs for deal entry.

    Client must have status rented/deposited/negotiating AND have viewed at
    least one listing; the most recently viewed listing is paired.
    Pairs that already have a recorded deal are skipped.
    Sorted: rented first, then deposited, then negotiating.
    """
    rank = {"rented": 0, "deposited": 1, "negotiating": 2}
    out = []
    for c in list_clients(broker_id, path=path):
        st = c.get("status")
        if st not in rank:
            continue
        viewed = c.get("viewed_listings") or []
        if not viewed:
            continue
        listing_id = viewed[-1]
        l = get_listing(listing_id, path=path)
        if not l:
            continue
        if deal_exists(broker_id, c["id"], listing_id, path=path):
            continue
        out.append({"client": c, "listing": l, "rank": rank[st]})
    out.sort(key=lambda p: (p["rank"], -p["client"]["updated_at"]))
    return out


# ---------------------------------------------------------------- templates

def create_template(broker_id, name, content, path=None):
    tpl_id = "tpl:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO templates (id, broker_id, name, content, created_at,"
        " updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (tpl_id, broker_id, name, content, now, now),
    )
    conn.commit()
    conn.close()
    return tpl_id


def list_templates(broker_id, path=None):
    conn = connect(path)
    rows = conn.execute(
        "SELECT * FROM templates WHERE broker_id = ? ORDER BY created_at ASC",
        (broker_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_template(tpl_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM templates WHERE id = ?", (tpl_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_template(tpl_id, path=None):
    conn = connect(path)
    cur = conn.execute("DELETE FROM templates WHERE id = ?", (tpl_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- match requests
# Cross-broker matching broadcasts. Privacy: client name/phone are NEVER
# stored here in a shareable form — only requirements_summary + urgency
# go into the group message.

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


# ---- broadcast anti-spam ----

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


# ---- broadcast responses (max 3 responders) ----

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


# ---------------------------------------------------------------- checklist
# Evening "do it now or tomorrow" items. kind: feedback | refresh | call.

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


# ---------------------------------------------------------------- anti-spam
# Escalating strike system. Fully automatic — no admin involvement.
#   Strike 1 → warning
#   Strike 2 → mute 1 hour
#   Strike 3 → mute 24 hours
#   Strike 4 → permanent ban
# Strikes decay to 0 after 30 days of no violations.

STRIKE_DECAY_DAYS = 30
SPAM_EVENT_WINDOW = 3600  # 1 hour window for "3x" counting

# Vietnamese messages for each enforcement action
_SPAM_MESSAGES = {
    "banned": (
        "🚫 Tài khoản của anh đã bị khóa do vi phạm nhiều lần.\n"
        "Anh liên hệ admin để được hỗ trợ nhé."
    ),
    "muted": (
        "🔇 Anh đang bị tạm khóa đến {until}.\n"
        "Hết giờ anh gửi lại bình thường nhé."
    ),
}


def get_spam_status(broker_id, path=None):
    """Return spam state: {strikes, muted_until, banned, last_strike_at}."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM spam_strikes WHERE broker_id = ?", (broker_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"strikes": 0, "muted_until": 0, "banned": False,
                "last_strike_at": None}
    d = dict(row)
    d["banned"] = bool(d["banned"])
    return d


def is_muted_or_banned(broker_id, path=None):
    """Check if broker is currently muted or banned.

    Returns (blocked: bool, message: str). Message is "" when not blocked.
    """
    st = get_spam_status(broker_id, path=path)
    if st["banned"]:
        return True, _SPAM_MESSAGES["banned"]
    now = _now()
    if st["muted_until"] and st["muted_until"] > now:
        until = time.strftime("%H:%M %d/%m", time.localtime(st["muted_until"]))
        return True, _SPAM_MESSAGES["muted"].format(until=until)
    return False, ""


def _apply_strike_decay(conn, broker_id, now):
    """Reset strikes to 0 if no violations in STRIKE_DECAY_DAYS. Returns strikes."""
    row = conn.execute(
        "SELECT strikes, last_strike_at FROM spam_strikes WHERE broker_id = ?",
        (broker_id,),
    ).fetchone()
    if not row:
        return 0
    strikes = row["strikes"]
    last = row["last_strike_at"]
    if strikes > 0 and last and (now - last) > STRIKE_DECAY_DAYS * 86400:
        conn.execute(
            "UPDATE spam_strikes SET strikes = 0, updated_at = ?"
            " WHERE broker_id = ?",
            (now, broker_id),
        )
        return 0
    return strikes


def record_spam_violation(broker_id, violation_type, path=None):
    """Record a strike-worthy violation. Returns action taken.

    violation_type: "rate_limit" | "spam_content" | "duplicate"
    Returns one of: "warn" (strike 1), "mute_1h" (strike 2),
                    "mute_24h" (strike 3), "ban" (strike 4+).
    Applies 30-day strike decay before incrementing.
    """
    now = _now()
    conn = connect(path)
    strikes = _apply_strike_decay(conn, broker_id, now)
    new_strikes = strikes + 1

    row = conn.execute(
        "SELECT broker_id FROM spam_strikes WHERE broker_id = ?",
        (broker_id,),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE spam_strikes SET strikes = ?, last_strike_at = ?,"
            " updated_at = ? WHERE broker_id = ?",
            (new_strikes, now, now, broker_id),
        )
    else:
        conn.execute(
            "INSERT INTO spam_strikes (broker_id, strikes, last_strike_at,"
            " muted_until, banned, created_at, updated_at)"
            " VALUES (?, ?, ?, 0, 0, ?, ?)",
            (broker_id, new_strikes, now, now, now),
        )

    if new_strikes == 1:
        action = "warn"
    elif new_strikes == 2:
        action = "mute_1h"
        conn.execute(
            "UPDATE spam_strikes SET muted_until = ? WHERE broker_id = ?",
            (now + 3600, broker_id),
        )
    elif new_strikes == 3:
        action = "mute_24h"
        conn.execute(
            "UPDATE spam_strikes SET muted_until = ? WHERE broker_id = ?",
            (now + 86400, broker_id),
        )
    else:
        action = "ban"
        conn.execute(
            "UPDATE spam_strikes SET banned = 1, muted_until = 0"
            " WHERE broker_id = ?",
            (broker_id,),
        )
    conn.commit()
    conn.close()
    # Log the violation event for audit
    log_spam_event(broker_id, violation_type, path=path)
    return action


def log_spam_event(broker_id, event_type, path=None):
    """Log a spam-related event (for 3x-in-1h counting)."""
    conn = connect(path)
    conn.execute(
        "INSERT INTO spam_events (broker_id, event_type, created_at)"
        " VALUES (?, ?, ?)",
        (broker_id, event_type, _now()),
    )
    conn.commit()
    conn.close()


def count_recent_spam_events(broker_id, event_type, hours=1, path=None):
    """How many events of this type in the last N hours."""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM spam_events"
        " WHERE broker_id = ? AND event_type = ? AND created_at > ?",
        (broker_id, event_type, _now() - hours * 3600),
    ).fetchone()["c"]
    conn.close()
    return n


def maybe_strike_for_repeated_event(broker_id, event_type, threshold=3,
                                    path=None):
    """Log event; if count in last hour hits threshold, record a strike.

    Returns the strike action ("warn"/"mute_1h"/"mute_24h"/"ban") or None
    if the threshold was not reached.
    """
    log_spam_event(broker_id, event_type, path=path)
    n = count_recent_spam_events(broker_id, event_type, hours=1, path=path)
    if n >= threshold:
        return record_spam_violation(broker_id, event_type, path=path)
    return None


def prune_old_spam_events(days=7, path=None):
    """Delete spam_events older than `days` — housekeeping."""
    conn = connect(path)
    cur = conn.execute(
        "DELETE FROM spam_events WHERE created_at < ?",
        (_now() - days * 86400,),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def count_recent_identical_texts(broker_id, text, hours=1, path=None):
    """How many listings with (normalized) identical raw_text in last N hours.

    Used for duplicate-text spam detection.
    """
    import re
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    if len(norm) < 20:
        return 0  # too short to be meaningful
    conn = connect(path)
    rows = conn.execute(
        "SELECT raw_text FROM tg_listings"
        " WHERE broker_id = ? AND created_at > ?",
        (broker_id, _now() - hours * 3600),
    ).fetchall()
    conn.close()
    n = 0
    for r in rows:
        other = re.sub(r"\s+", " ", (r["raw_text"] or "").strip().lower())
        if other == norm:
            n += 1
    return n


def spam_violation_message(action, violation_type, detail=""):
    """Vietnamese user-facing message for a strike action.

    action: "warn" | "mute_1h" | "mute_24h" | "ban"
    violation_type: "rate_limit" | "spam_content" | "duplicate"
    detail: violation-specific detail
      - rate_limit: "Gói Free tối đa 10 tin/giờ, anh đã gửi 12 tin"
      - spam_content: truncated snippet of the rejected text
      - duplicate: unused (fixed message)
    Every message states the specific reason — never generic.
    """
    reason = _VIOLATION_REASONS.get(violation_type, "vi phạm quy định")
    if action == "warn":
        if violation_type == "rate_limit":
            return (
                "⚠️ Cảnh báo 1/3: Anh gửi quá nhanh!\n"
                f"{detail}.\n"
                "Chậm lại nhé, tái phạm em sẽ tạm khóa 1 giờ ạ."
            )
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return (
                "⚠️ Cảnh báo 1/3: Tin vừa rồi không phải tin cho thuê!\n"
                f'("{snippet}...")\n'
                "Anh chỉ gửi tin cho thuê nhà giúp em nhé.\n"
                "Tái phạm em sẽ tạm khóa 1 giờ ạ."
            )
        # duplicate
        return (
            "⚠️ Cảnh báo 1/3: Anh gửi tin này 3 lần rồi!\n"
            "Em đã bỏ qua các bản trùng. Đừng gửi lặp lại nhé.\n"
            "Tái phạm em sẽ tạm khóa 1 giờ ạ."
        )
    if action == "mute_1h":
        head = f"🔇 Tạm khóa 1 giờ (cảnh báo 2/3): {reason}!"
        if violation_type == "rate_limit":
            return f"{head}\n{detail}.\nHết giờ anh gửi lại bình thường nhé."
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return f'{head}\n("{snippet}...")\nHết giờ anh gửi lại bình thường nhé.'
        return f"{head}\nHết giờ anh gửi lại bình thường nhé."
    if action == "mute_24h":
        head = f"🔇 Tạm khóa 24 giờ (cảnh báo 3/3): {reason}!"
        if violation_type == "rate_limit":
            return (f"{head}\n{detail}.\n"
                    "Đây là cảnh báo cuối cùng ạ.")
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return (f'{head}\n("{snippet}...")\n'
                    "Đây là cảnh báo cuối cùng ạ.")
        return f"{head}\nĐây là cảnh báo cuối cùng ạ."
    # ban
    return (
        f"🚫 Tài khoản của anh đã bị khóa vĩnh viễn (vi phạm: {reason}).\n"
        "Anh liên hệ admin để được hỗ trợ nhé."
    )


_VIOLATION_REASONS = {
    "rate_limit": "gửi tin quá nhanh",
    "spam_content": "gửi tin không phải cho thuê",
    "duplicate": "gửi tin trùng lặp",
}


# ---------------------------------------------------------------- admin metrics

def get_metrics_summary(since, path=None):
    """Aggregate MVP metrics for the admin /metrics dashboard.

    since: unix timestamp — start of the reporting window (e.g. 7 days ago).
    Debt (công nợ) is all-time unpaid, not windowed — Khanh uses it to
    cross-check when brokers upload payment bills.

    Returns dict with broker/match/revenue/warning aggregates. Each debt
    entry: {broker_id, name, deals, total, days_overdue}.
    """
    now = _now()
    conn = connect(path)

    # ---- brokers ----
    brokers_active = conn.execute(
        """SELECT COUNT(DISTINCT b.user_id) c FROM brokers b
           WHERE b.updated_at >= ?
              OR EXISTS (SELECT 1 FROM tg_listings l
                         WHERE l.broker_id = b.user_id AND l.created_at >= ?)
              OR EXISTS (SELECT 1 FROM clients c
                         WHERE c.broker_id = b.user_id AND c.updated_at >= ?)""",
        (since, since, since),
    ).fetchone()["c"]
    brokers_new = conn.execute(
        "SELECT COUNT(*) c FROM brokers WHERE created_at >= ?", (since,),
    ).fetchone()["c"]
    listings_total = conn.execute(
        "SELECT COUNT(*) c FROM tg_listings WHERE status != 'deleted'",
    ).fetchone()["c"]

    # ---- match ----
    match_broadcast = conn.execute(
        "SELECT COUNT(*) c FROM match_requests WHERE created_at >= ?",
        (since,),
    ).fetchone()["c"]
    match_reserve = conn.execute(
        "SELECT COUNT(*) c FROM match_responses WHERE created_at >= ?",
        (since,),
    ).fetchone()["c"]
    match_submit = conn.execute(
        """SELECT COUNT(*) c FROM match_responses
           WHERE created_at >= ?
             AND ((listing_id IS NOT NULL AND listing_id != '')
                  OR (listing_ids NOT IN ('[]', '')))""",
        (since,),
    ).fetchone()["c"]
    match_chosen = conn.execute(
        """SELECT COUNT(*) c FROM match_responses
           WHERE created_at >= ?
             AND requester_consent = 1 AND responder_consent = 1""",
        (since,),
    ).fetchone()["c"]

    # ---- revenue (windowed) ----
    rev = conn.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(commission_vnd), 0) total
           FROM deals WHERE closed_at >= ? AND commission_vnd > 0""",
        (since,),
    ).fetchone()

    # ---- debt (công nợ): all-time unpaid deals, per broker ----
    debt_rows = conn.execute(
        """SELECT d.broker_id,
                  COALESCE(NULLIF(b.display_name, ''), b.username, '') AS name,
                  COUNT(*) AS n_deals,
                  COALESCE(SUM(d.commission_vnd), 0) AS total,
                  MIN(d.closed_at) AS oldest_closed
           FROM deals d
           LEFT JOIN brokers b ON b.user_id = d.broker_id
           WHERE d.paid = 0 AND d.commission_vnd > 0
           GROUP BY d.broker_id
           ORDER BY total DESC""",
    ).fetchall()
    debts = []
    for r in debt_rows:
        days_overdue = int((now - (r["oldest_closed"] or now)) // 86400)
        debts.append({
            "broker_id": r["broker_id"],
            "name": r["name"] or f"ID {r['broker_id']}",
            "deals": r["n_deals"],
            "total": r["total"],
            "days_overdue": max(days_overdue, 0),
        })

    # ---- warnings: deals closed in last 30d needing confirmation ----
    pending = conn.execute(
        """SELECT d.broker_id,
                  COALESCE(NULLIF(b.display_name, ''), b.username, '') AS name,
                  d.client_name, d.closed_at
           FROM deals d
           LEFT JOIN brokers b ON b.user_id = d.broker_id
           WHERE d.closed_at >= ?
           ORDER BY d.closed_at DESC LIMIT 10""",
        (now - 30 * 86400,),
    ).fetchall()
    pending_confirm = [
        {"broker_id": r["broker_id"],
         "broker_name": r["name"] or f"ID {r['broker_id']}",
         "client_name": r["client_name"] or "—",
         "days_ago": int((now - r["closed_at"]) // 86400)}
        for r in pending
    ]
    # brokers with spam strikes / muted / banned
    flagged = conn.execute(
        """SELECT s.broker_id,
                  COALESCE(NULLIF(b.display_name, ''), b.username, '') AS name,
                  s.strikes, s.banned, s.muted_until
           FROM spam_strikes s
           LEFT JOIN brokers b ON b.user_id = s.broker_id
           WHERE s.strikes > 0 OR s.banned = 1
           ORDER BY s.banned DESC, s.strikes DESC LIMIT 10""",
    ).fetchall()
    flagged_brokers = [
        {"broker_id": r["broker_id"],
         "name": r["name"] or f"ID {r['broker_id']}",
         "strikes": r["strikes"],
         "banned": bool(r["banned"]),
         "muted": r["muted_until"] > now}
        for r in flagged
    ]
    conn.close()

    return {
        "brokers_active": brokers_active,
        "brokers_new": brokers_new,
        "listings_total": listings_total,
        "match_broadcast": match_broadcast,
        "match_reserve": match_reserve,
        "match_submit": match_submit,
        "match_chosen": match_chosen,
        "deals_count": rev["n"],
        "commission_total": rev["total"],
        "debts": debts,
        "pending_confirm": pending_confirm,
        "flagged_brokers": flagged_brokers,
    }


if __name__ == "__main__":
    init_db()
    print("db initialised at", config.DB_PATH)
