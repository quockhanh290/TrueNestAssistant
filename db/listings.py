"""Listings: CRUD, search, photos, posts, dedup."""
import json

from .core import connect, _now
from .refresh import log_refresh_claim
import uuid



def active_listing_count(broker_id, path=None):
    """Count of non-deleted, non-draft listings (what the free limit applies to)."""
    return count_broker_listings(
        broker_id, statuses=("submitted", "pending_info", "negotiating",
                             "deposited", "rented", "active"),
        path=path)


def check_listing_limit(broker_id, path=None):
    """(ok, count, limit) — free tier capped, paid tiers unlimited."""
    from .brokers import get_broker, get_tier  # lazy: avoids circular import
    tier = get_tier(broker_id, path=path)
    if tier != "free":
        return True, active_listing_count(broker_id, path=path), 0
    limit = (get_broker(broker_id, path=path) or {}).get("listing_limit") \
        or config.FREE_LISTING_LIMIT
    count = active_listing_count(broker_id, path=path)
    return count < limit, count, limit


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
    d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
    d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
    d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
    d["parsed"] = json.loads(d["parsed"])
    d["missing_fields"] = json.loads(d["missing_fields"])
    return d


def update_listing(listing_id, path=None, **fields):
    allowed = {"raw_text", "photo_file_ids", "photo_urls", "photo_hashes",
               "photo_phashes",
               "parsed", "missing_fields",
               "status", "view_count", "inquiry_count", "duplicate_of",
               "content_hash", "saved_post"}
    json_fields = {"photo_file_ids", "photo_urls", "photo_hashes",
                   "photo_phashes",
                   "parsed", "missing_fields"}
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


def refresh_listing(listing_id, broker_id=None, claimed_status="available",
                    velocity_flag=False, path=None):
    """Bump updated_at to now without changing any data.

    Used by the propose flow (Khanh 2026-10-16, revised): broker confirms the
    listing is still accurate after (claimed) real-world verification,
    resetting its freshness age to 0. Every claim is audit-logged;
    false "available" claims feed the reputation penalty system.
    Returns True if the listing exists.
    """
    conn = connect(path)
    row = conn.execute(
        "SELECT 1 FROM tg_listings WHERE id = ?", (listing_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE tg_listings SET updated_at = ? WHERE id = ?",
        (_now(), listing_id),
    )
    conn.commit()
    conn.close()
    if broker_id is not None:
        log_refresh_claim(listing_id, broker_id, claimed_status,
                          velocity_flag=velocity_flag, path=path)
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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
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


def add_photo_url(listing_id, url, path=None):
    """Append a public R2 photo URL to the listing's photo_urls.

    Idempotent — won't add duplicates. Returns True if added.
    """
    if not url:
        return False
    l = get_listing(listing_id, path=path)
    if not l:
        return False
    urls = l.get("photo_urls") or []
    if url in urls:
        return False
    urls.append(url)
    update_listing(listing_id, path=path, photo_urls=urls)
    return True


def add_photo_hash(listing_id, url, dhash, phash=None, path=None):
    """Record perceptual hashes for a photo URL.

    Stores photo_hashes[url] = dhash (when given) and
    photo_phashes[url] = phash (when given). Skips when the respective
    hash is None (PIL missing at upload time) — upload still works,
    just no dedup for that photo. Returns True if anything was stored.
    """
    if not url or (not dhash and not phash):
        return False
    l = get_listing(listing_id, path=path)
    if not l:
        return False
    stored = False
    if dhash:
        hashes = l.get("photo_hashes") or {}
        if hashes.get(url) != dhash:
            hashes[url] = dhash
            update_listing(listing_id, path=path, photo_hashes=hashes)
            stored = True
    if phash:
        phashes = l.get("photo_phashes") or {}
        if phashes.get(url) != phash:
            phashes[url] = phash
            update_listing(listing_id, path=path, photo_phashes=phashes)
            stored = True
    return stored


def _hamming_hex(h1, h2):
    """Hamming distance between two 16-char hex dhashes (local, no PIL)."""
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except (TypeError, ValueError):
        return 64


def find_photos_by_hash(dhash, max_distance=5, path=None, exclude_id=None,
                        phash=None):
    """Find photos whose dHash OR pHash is within max_distance (hamming).

    Checks both hash columns: dHash catches small edits/crops, pHash
    catches resizes/recompressions/recolors. Either firing suggests a
    duplicate — callers decide, never auto-merge.

    Returns [(listing_id, url, distance)] ordered by distance (the best
    of the two hash distances). Skips exclude_id. Scans the whole
    tg_listings table — fine at broker-bot scale; revisit if listings
    grow past ~50k.
    """
    if not dhash and not phash:
        return []
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT id, photo_hashes, photo_phashes FROM tg_listings"
            " WHERE (photo_hashes IS NOT NULL AND photo_hashes != '{}')"
            " OR (photo_phashes IS NOT NULL AND photo_phashes != '{}')"
        ).fetchall()
    except Exception:
        # photo_phashes column missing (migration not run yet) — dHash only.
        rows = conn.execute(
            "SELECT id, photo_hashes FROM tg_listings"
            " WHERE photo_hashes IS NOT NULL AND photo_hashes != '{}'"
        ).fetchall()
    conn.close()
    out = []
    out = []
    for r in rows:
        lid = r["id"]
        if exclude_id and lid == exclude_id:
            continue
        # photo_phashes may be absent on DBs created before the migration.
        keys = r.keys()
        try:
            hashes = json.loads(r["photo_hashes"] or "{}")
        except (json.JSONDecodeError, TypeError):
            hashes = {}
        try:
            ph_raw = r["photo_phashes"] if "photo_phashes" in keys else None
            phashes = json.loads(ph_raw or "{}")
        except (json.JSONDecodeError, TypeError):
            phashes = {}
        urls = set(hashes) | set(phashes)
        for url in urls:
            best = 64
            h = hashes.get(url)
            if dhash and h:
                best = min(best, _hamming_hex(dhash, h))
            p = phashes.get(url)
            if phash and p:
                best = min(best, _hamming_hex(phash, p))
            if best <= max_distance:
                out.append((lid, url, best))
    out.sort(key=lambda t: t[2])
    return out


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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
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
        d["photo_urls"] = json.loads(d.get("photo_urls") or "[]")
        d["photo_hashes"] = json.loads(d.get("photo_hashes") or "{}")
        d["photo_phashes"] = json.loads(d.get("photo_phashes") or "{}")
        d["parsed"] = json.loads(d["parsed"])
        d["missing_fields"] = json.loads(d["missing_fields"])
        return d
    return None
