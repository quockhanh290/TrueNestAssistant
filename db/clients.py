"""Clients + message templates."""
from .core import connect, _now
import json
import time
import uuid



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
    from .vntime import fmt as _vn_fmt
    ts = _vn_fmt(_now(), "%d/%m %H:%M")
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
