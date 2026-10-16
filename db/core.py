"""DB core: connection, schema, migrations, metrics."""
import json
import sqlite3
import time

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
CREATE TABLE IF NOT EXISTS trial_usage (
    broker_id  INTEGER NOT NULL,
    feature    TEXT NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (broker_id, feature)
);

-- shareable listing pages: broker creates a public link (/s/<token>) to
-- send curated listings to a client via any channel (Zalo/SMS/...).
-- 30-day expiry; view_count + share_bookings track engagement.
CREATE TABLE IF NOT EXISTS share_pages (
    token       TEXT PRIMARY KEY,
    broker_id   INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id   TEXT,
    listing_ids TEXT NOT NULL DEFAULT '[]',
    title       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    view_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sharepages_broker ON share_pages(broker_id);

-- viewing requests submitted from a public share page (no auth).
-- Surfaced to the broker via GET /api/shares.
CREATE TABLE IF NOT EXISTS share_bookings (
    id             TEXT PRIMARY KEY,
    token          TEXT NOT NULL REFERENCES share_pages(token),
    broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
    listing_id     TEXT,
    name           TEXT NOT NULL DEFAULT '',
    phone          TEXT NOT NULL DEFAULT '',
    preferred_date TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'new',
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sharebookings_token ON share_bookings(token);
CREATE INDEX IF NOT EXISTS idx_sharebookings_broker ON share_bookings(broker_id);
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
    _migrate_listings_photo_urls(conn)
    _migrate_listings_photo_hashes(conn)
    _migrate_trial_usage(conn)
    _migrate_share_pages(conn)
    _migrate_outbox(conn)
    _migrate_match_notifications(conn)
    _migrate_broker_notify_prefs(conn)
    _migrate_refresh_reputation(conn)
    _migrate_refresh_log(conn)
    _migrate_listing_reports(conn)
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
    # contextual hints (2026-10-16): track which first-time feature hints
    # the broker has already seen, so we only show each once.
    if "seen_hints" not in cols:
        conn.execute(
            "ALTER TABLE brokers ADD COLUMN seen_hints TEXT NOT NULL"
            " DEFAULT '[]'"
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
    """Add closed_reason + responses_seen_at + expires_at to match_requests (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(match_requests)")}
    if "closed_reason" not in cols:
        conn.execute("ALTER TABLE match_requests ADD COLUMN closed_reason TEXT")
    if "responses_seen_at" not in cols:
        conn.execute("ALTER TABLE match_requests ADD COLUMN responses_seen_at REAL")
    if "expires_at" not in cols:
        conn.execute("ALTER TABLE match_requests ADD COLUMN expires_at REAL")


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


def _migrate_listings_photo_urls(conn):
    """Add photo_urls to tg_listings.

    JSON array of public R2 URLs for the listing's photos, uploaded in
    the background after submit. The web app renders these directly;
    the bot keeps using photo_file_ids (Telegram file_id) for sending.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_listings)")}
    if "photo_urls" not in cols:
        conn.execute(
            "ALTER TABLE tg_listings ADD COLUMN photo_urls"
            " TEXT NOT NULL DEFAULT '[]'"
        )


def _migrate_listings_photo_hashes(conn):
    """Add photo_hashes to tg_listings.

    JSON object mapping R2 URL -> 16-char hex dhash, used for image
    duplicate detection. NULL hashes (PIL missing at upload time) are
    simply not stored; the mapping may be an empty object.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_listings)")}
    if "photo_hashes" not in cols:
        conn.execute(
            "ALTER TABLE tg_listings ADD COLUMN photo_hashes"
            " TEXT NOT NULL DEFAULT '{}'"
        )


def _migrate_trial_usage(conn):
    """Create trial_usage table for per-feature free-trial tracking.

    Idempotent: CREATE TABLE IF NOT EXISTS.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trial_usage (
            broker_id  INTEGER NOT NULL,
            feature    TEXT NOT NULL,
            used_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (broker_id, feature)
        )
    """)


def _migrate_share_pages(conn):
    """Create share_pages + share_bookings for public listing share links.

    Idempotent: CREATE TABLE IF NOT EXISTS.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS share_pages (
            token       TEXT PRIMARY KEY,
            broker_id   INTEGER NOT NULL REFERENCES brokers(user_id),
            client_id   TEXT,
            listing_ids TEXT NOT NULL DEFAULT '[]',
            title       TEXT NOT NULL DEFAULT '',
            created_at  REAL NOT NULL,
            expires_at  REAL NOT NULL,
            view_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sharepages_broker"
        " ON share_pages(broker_id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS share_bookings (
            id             TEXT PRIMARY KEY,
            token          TEXT NOT NULL REFERENCES share_pages(token),
            broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
            listing_id     TEXT,
            name           TEXT NOT NULL DEFAULT '',
            phone          TEXT NOT NULL DEFAULT '',
            preferred_date TEXT NOT NULL DEFAULT '',
            note           TEXT NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     REAL NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sharebookings_token"
        " ON share_bookings(token)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sharebookings_broker"
        " ON share_bookings(broker_id)"
    )


def _now():
    return time.time()


def _migrate_outbox(conn):
    """Create outbox_notifications table (webapp writes, bot polls+sends)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outbox_notifications (
            id         TEXT PRIMARY KEY,
            ntype      TEXT NOT NULL,
            request_id TEXT,
            payload    TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            sent_at    REAL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_unsent"
        " ON outbox_notifications(sent_at) WHERE sent_at IS NULL"
    )


def _migrate_match_notifications(conn):
    """Track per-(request, broker) proactive notifications to avoid duplicates."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS match_notifications (
            request_id TEXT NOT NULL,
            broker_id  INTEGER NOT NULL,
            sent_at    REAL NOT NULL,
            PRIMARY KEY (request_id, broker_id)
        )"""
    )


NOTIFY_PREFS = ("notify_match", "notify_quality", "notify_trial", "notify_booking")

NOTIFY_PREF_LABELS = {
    "notify_match": "Lead phù hợp",
    "notify_quality": "Chất lượng tin",
    "notify_trial": "Lượt dùng thử",
    "notify_booking": "Khách đặt lịch",
}


def _migrate_broker_notify_prefs(conn):
    """Add notification preference columns to brokers (default on)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(brokers)")}
    for pref in NOTIFY_PREFS:
        if pref not in cols:
            conn.execute(
                f"ALTER TABLE brokers ADD COLUMN {pref} INTEGER NOT NULL DEFAULT 1"
            )


def _migrate_refresh_reputation(conn):
    """Reputation penalty for false refresh claims (Khanh 2026-10-16).

    false_refresh_reports: count of listings claimed "available" via refresh
      but later found rented. -10 profile points each; 3 -> 7-day propose ban.
    refresh_cooldown_until: timestamp until which broker cannot propose.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(brokers)")}
    if "false_refresh_reports" not in cols:
        conn.execute(
            "ALTER TABLE brokers ADD COLUMN false_refresh_reports"
            " INTEGER NOT NULL DEFAULT 0"
        )
    if "refresh_cooldown_until" not in cols:
        conn.execute(
            "ALTER TABLE brokers ADD COLUMN refresh_cooldown_until REAL"
        )


def _migrate_refresh_log(conn):
    """Audit log of every refresh claim (Khanh 2026-10-16)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS listing_refresh_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id     TEXT NOT NULL,
            broker_id      INTEGER NOT NULL,
            claimed_status TEXT NOT NULL,
            velocity_flag  INTEGER NOT NULL DEFAULT 0,
            created_at     REAL NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_log_listing"
        " ON listing_refresh_log(listing_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_refresh_log_broker_time"
        " ON listing_refresh_log(broker_id, created_at)"
    )
    # Add velocity_flag to existing tables (idempotent)
    try:
        conn.execute(
            "ALTER TABLE listing_refresh_log"
            " ADD COLUMN velocity_flag INTEGER NOT NULL DEFAULT 0"
        )
    except Exception:
        pass  # column already exists


def _migrate_listing_reports(conn):
    """Client reports of incorrect listings on share pages (Khanh 2026-10-16)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS listing_reports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            token      TEXT NOT NULL,
            listing_id TEXT NOT NULL,
            broker_id  INTEGER NOT NULL,
            reason     TEXT NOT NULL,
            created_at REAL NOT NULL,
            reviewed   INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_broker"
        " ON listing_reports(broker_id, reviewed)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_listing"
        " ON listing_reports(listing_id)"
    )


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
