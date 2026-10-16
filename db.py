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
    created_at     REAL NOT NULL
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
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_broker ON tg_listings(broker_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON tg_listings(status);

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
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clients_broker ON clients(broker_id);
CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);

CREATE TABLE IF NOT EXISTS viewings (
    id          TEXT PRIMARY KEY,
    broker_id   INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id   TEXT,
    client_name TEXT NOT NULL DEFAULT '',
    listing_id  TEXT,
    scheduled_at REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'scheduled',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_viewings_broker ON viewings(broker_id);
CREATE INDEX IF NOT EXISTS idx_viewings_sched ON viewings(scheduled_at);

CREATE TABLE IF NOT EXISTS deals (
    id             TEXT PRIMARY KEY,
    broker_id      INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id      TEXT,
    client_name    TEXT NOT NULL DEFAULT '',
    listing_id     TEXT,
    commission_vnd REAL,
    closed_at      REAL NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_broker ON deals(broker_id);
CREATE INDEX IF NOT EXISTS idx_deals_closed ON deals(closed_at);

CREATE TABLE IF NOT EXISTS templates (
    id         TEXT PRIMARY KEY,
    broker_id  INTEGER NOT NULL REFERENCES brokers(user_id),
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_broker ON templates(broker_id);

CREATE TABLE IF NOT EXISTS match_requests (
    id                  TEXT PRIMARY KEY,
    broker_id           INTEGER NOT NULL REFERENCES brokers(user_id),
    client_id           TEXT NOT NULL REFERENCES clients(id),
    requirements_summary TEXT NOT NULL DEFAULT '',
    urgency             TEXT NOT NULL DEFAULT 'normal',
    status              TEXT NOT NULL DEFAULT 'open',
    group_message_id    INTEGER,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mreq_broker ON match_requests(broker_id);
CREATE INDEX IF NOT EXISTS idx_mreq_status ON match_requests(status);
CREATE INDEX IF NOT EXISTS idx_mreq_groupmsg ON match_requests(group_message_id);
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
    conn.commit()
    conn.close()


def _migrate_clients(conn):
    """Add urgency column to clients on pre-existing DBs (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
    if "urgency" not in cols:
        conn.execute(
            "ALTER TABLE clients ADD COLUMN urgency TEXT NOT NULL DEFAULT 'normal'"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clients_urgency ON clients(urgency)"
    )


def _migrate_brokers(conn):
    """Add contact columns to brokers on pre-existing DBs (no data loss)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(brokers)")}
    for col in ("name", "zalo", "facebook", "pronoun"):
        if col not in cols:
            conn.execute(f"ALTER TABLE brokers ADD COLUMN {col} TEXT")


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
    conn.execute(
        "INSERT INTO brokers (user_id, username, display_name, status, created_at)"
        " VALUES (?, ?, ?, 'new', ?)",
        (user_id, username, display_name, _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM brokers WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def update_broker(user_id, path=None, **fields):
    allowed = {"username", "display_name", "name", "pronoun", "phone", "zalo",
               "facebook", "status", "listings_count", "approved_count"}
    sets = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
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


def get_broker_phone(broker_id, path=None):
    """Broker's saved phone, or None."""
    b = get_broker(broker_id, path=path)
    return b.get("phone") if b else None


def set_broker_phone(broker_id, phone, path=None):
    """Save broker's phone (used for listing auto-fill)."""
    update_broker(broker_id, path=path, phone=phone)


# ---------------------------------------------------------------- listings

def create_listing(broker_id, raw_text="", photo_file_ids=None,
                   parsed=None, missing_fields=None, status="draft", path=None):
    listing_id = "tg:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO tg_listings (id, broker_id, raw_text, photo_file_ids,"
        " parsed, missing_fields, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (listing_id, broker_id, raw_text,
         json.dumps(photo_file_ids or [], ensure_ascii=False),
         json.dumps(parsed or {}, ensure_ascii=False),
         json.dumps(missing_fields or [], ensure_ascii=False),
         status, now, now),
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
               "status", "view_count", "inquiry_count"}
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


# ---------------------------------------------------------------- clients

CLIENT_STATUSES = ("new", "viewing", "negotiating", "deposited", "rented",
                   "cancelled")


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
        " status, urgency, notes, viewed_listings, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, '', '[]', ?, ?)",
        (client_id, broker_id, name, phone,
         r.get("min_price"), r.get("max_price"), r.get("bedrooms"),
         r.get("district"), r.get("property_type"), requirements_raw,
         urgency, now, now),
    )
    conn.commit()
    conn.close()
    return client_id


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
        "UPDATE clients SET notes = ?, updated_at = ? WHERE id = ?",
        (notes, _now(), client_id),
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
            "UPDATE clients SET viewed_listings = ?, updated_at = ? WHERE id = ?",
            (json.dumps(seen, ensure_ascii=False), _now(), client_id),
        )
        conn.commit()
    conn.close()
    return True


def delete_client(client_id, path=None):
    conn = connect(path)
    cur = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ---------------------------------------------------------------- viewings

VIEWING_STATUSES = ("scheduled", "done", "cancelled")


def create_viewing(broker_id, client_id=None, client_name="", listing_id=None,
                   scheduled_at=None, notes="", path=None):
    viewing_id = "vw:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO viewings (id, broker_id, client_id, client_name,"
        " listing_id, scheduled_at, status, notes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)",
        (viewing_id, broker_id, client_id, client_name, listing_id,
         scheduled_at or now, notes, now),
    )
    conn.commit()
    conn.close()
    return viewing_id


def get_viewing(viewing_id, path=None):
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM viewings WHERE id = ?", (viewing_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


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
    return [dict(r) for r in rows]


def update_viewing(viewing_id, path=None, **fields):
    allowed = {"client_id", "client_name", "listing_id", "scheduled_at",
               "status", "notes"}
    sets = ", ".join(f"{k} = ?" for k in fields if k in allowed)
    if not sets:
        return False
    vals = [fields[k] for k in fields if k in allowed]
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


# ---------------------------------------------------------------- deals

def create_deal(broker_id, client_id=None, client_name="", listing_id=None,
                commission_vnd=None, closed_at=None, notes="", path=None):
    deal_id = "deal:" + uuid.uuid4().hex[:12]
    now = _now()
    conn = connect(path)
    conn.execute(
        "INSERT INTO deals (id, broker_id, client_id, client_name, listing_id,"
        " commission_vnd, closed_at, notes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (deal_id, broker_id, client_id, client_name, listing_id,
         commission_vnd, closed_at or now, notes, now),
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
    conn = connect(path)
    conn.execute(
        "INSERT INTO templates (id, broker_id, name, content, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (tpl_id, broker_id, name, content, _now()),
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
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM match_requests"
        " WHERE group_message_id = ? AND status = 'open'",
        (group_message_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_broker_requests(broker_id, status=None, limit=50, path=None):
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
    allowed = {"status", "group_message_id", "requirements_summary"}
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


if __name__ == "__main__":
    init_db()
    print("db initialised at", config.DB_PATH)
