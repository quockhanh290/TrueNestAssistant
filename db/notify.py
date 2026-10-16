"""Outbox + notification prefs."""
from .core import connect, _now, NOTIFY_PREFS, NOTIFY_PREF_LABELS, _migrate_match_notifications, _migrate_broker_notify_prefs, _migrate_outbox
import json
import uuid



def was_notified(request_id, broker_id, path=None):
    """True if this broker was already proactively notified about this request."""
    conn = connect(path)
    _migrate_match_notifications(conn)
    row = conn.execute(
        "SELECT 1 FROM match_notifications WHERE request_id = ? AND broker_id = ?",
        (request_id, broker_id),
    ).fetchone()
    conn.close()
    return bool(row)


def mark_notified(request_id, broker_id, path=None):
    """Record that this broker was notified about this request."""
    conn = connect(path)
    _migrate_match_notifications(conn)
    conn.execute(
        "INSERT OR IGNORE INTO match_notifications (request_id, broker_id, sent_at)"
        " VALUES (?, ?, ?)",
        (request_id, broker_id, _now()),
    )
    conn.commit()
    conn.close()


def get_notify_prefs(broker_id, path=None):
    """Return {pref: bool} for a broker. Defaults all True for unknown brokers."""
    conn = connect(path)
    _migrate_broker_notify_prefs(conn)
    row = conn.execute(
        f"SELECT {', '.join(NOTIFY_PREFS)} FROM brokers WHERE user_id = ?",
        (broker_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {p: True for p in NOTIFY_PREFS}
    return {p: bool(row[p]) for p in NOTIFY_PREFS}


def set_notify_pref(broker_id, pref, value, path=None):
    """Set one notification preference. Returns False on unknown pref."""
    if pref not in NOTIFY_PREFS:
        return False
    conn = connect(path)
    _migrate_broker_notify_prefs(conn)
    conn.execute(
        f"UPDATE brokers SET {pref} = ?, updated_at = ? WHERE user_id = ?",
        (1 if value else 0, _now(), broker_id),
    )
    conn.commit()
    conn.close()
    return True


def queue_notification(ntype, request_id=None, payload=None, path=None):
    """Queue a notification for the bot to send. Returns the notification id."""
    import uuid as _uuid
    conn = connect(path)
    _migrate_outbox(conn)
    nid = f"notif:{_uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO outbox_notifications (id, ntype, request_id, payload,"
        " created_at) VALUES (?, ?, ?, ?, ?)",
        (nid, ntype, request_id, json.dumps(payload or {}), _now()),
    )
    conn.commit()
    conn.close()
    return nid


def pop_unsent_notifications(limit=20, path=None):
    """Fetch unsent notifications (for the bot poller). Does NOT mark sent."""
    conn = connect(path)
    _migrate_outbox(conn)
    rows = conn.execute(
        "SELECT * FROM outbox_notifications WHERE sent_at IS NULL"
        " ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except (ValueError, TypeError):
            d["payload"] = {}
        out.append(d)
    return out


def mark_notification_sent(nid, path=None):
    """Mark a notification as sent."""
    conn = connect(path)
    conn.execute(
        "UPDATE outbox_notifications SET sent_at = ? WHERE id = ?",
        (_now(), nid),
    )
    conn.commit()
    conn.close()
