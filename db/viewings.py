"""Viewing appointments."""
import uuid

from .core import connect, _now
import json



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
