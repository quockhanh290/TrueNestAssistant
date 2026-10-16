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
"""


def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=None):
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate_brokers(conn)
    conn.commit()
    conn.close()


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


if __name__ == "__main__":
    init_db()
    print("db initialised at", config.DB_PATH)
