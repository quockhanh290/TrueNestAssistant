"""API logic for clients, deals, broker profile, notify prefs, premium requests.

Thin wrappers over db/ — no SQL here. UI calls these via webapp/server.py.
All functions return (dict, http_status) tuples.
"""
import os
import time

import db
import utils


# ---------------------------------------------------------------- referral

def get_referral_api(broker_id):
    """GET /api/referral — invite link + progress + reward status."""
    prog = db.get_referral_progress(broker_id)
    username = (os.getenv("BOT_USERNAME", "") or "").lstrip("@")
    link = f"https://t.me/{username}?start=ref_{broker_id}" if username else ""
    return {
        "link": link,
        "invited": prog["invited"],
        "qualified": prog["qualified"],
        "needed": prog["needed"],
        "reward_months_active": db.active_referral_months(broker_id),
        "max_stack": db.REFERRAL_MAX_STACK,
    }, 200


# ---------------------------------------------------------------- clients

CLIENT_STATUS_VI = {
    "new": "Mới",
    "contacted": "Đã liên hệ",
    "searching": "Đang tìm",
    "sent": "Đã gửi tin",
    "viewed": "Đã xem",
    "negotiating": "Đang đàm phán",
    "closed": "Đã chốt",
    "cancelled": "Hủy",
}


def _client_summary(c):
    """Compact dict for list views."""
    req = []
    br = c.get("bedrooms")
    if br is not None:
        req.append("Studio" if br == 0 else "%dPN" % int(br))
    bmax = c.get("budget_max")
    if bmax:
        t = bmax / 1000000
        req.append("<%s tr" % (int(t) if t == int(t) else round(t, 1)))
    if c.get("district"):
        req.append(c["district"])
    return {
        "id": c["id"],
        "name": c.get("name") or "—",
        "phone": c.get("phone") or "",
        "status": c.get("status"),
        "status_vi": CLIENT_STATUS_VI.get(c.get("status"), c.get("status")),
        "urgency": c.get("urgency"),
        "req_summary": " · ".join(req) or (c.get("requirements_raw") or "—"),
        "notes": c.get("notes") or "",
        "updated_at": c.get("updated_at"),
    }


def list_clients_api(broker_id, status=None):
    """GET /api/clients — broker's clients, urgency-first."""
    clients = db.list_clients(broker_id, status=status, limit=100)
    return {"clients": [_client_summary(c) for c in clients]}, 200


def get_client_api(broker_id, client_id):
    """GET /api/client/<id> — detail + viewings."""
    c = db.get_client(client_id)
    if not c or c.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    out = _client_summary(c)
    out["requirements_raw"] = c.get("requirements_raw") or ""
    out["budget_min"] = c.get("budget_min")
    out["budget_max"] = c.get("budget_max")
    out["bedrooms"] = c.get("bedrooms")
    out["district"] = c.get("district")
    out["property_type"] = c.get("property_type")
    out["sent_listings"] = c.get("sent_listings") or []
    out["viewed_listings"] = c.get("viewed_listings") or []
    # viewings for this client
    try:
        vws = db.client_viewings(client_id)
        out["viewings"] = [
            {
                "id": v["id"],
                "scheduled_at": v.get("scheduled_at"),
                "status": v.get("status"),
                "listing_ids": v.get("listing_ids") or [],
                "notes": v.get("notes") or "",
            }
            for v in vws[:20]
        ]
    except Exception:
        out["viewings"] = []
    return out, 200


def create_client_api(broker_id, data):
    """POST /api/clients — create a client."""
    data = data or {}
    name = (data.get("name") or "").strip()
    if not name:
        return {"error": "name_required",
                "error_vi": "Vui lòng nhập tên khách"}, 400
    req = {}
    try:
        if data.get("budget_max"):
            req["max_price"] = float(data["budget_max"])
        if data.get("budget_min"):
            req["min_price"] = float(data["budget_min"])
    except (TypeError, ValueError):
        pass
    br = data.get("bedrooms")
    if br not in (None, ""):
        try:
            req["bedrooms"] = float(br)
        except (TypeError, ValueError):
            pass
    if data.get("district"):
        req["district"] = data["district"].strip()
    if data.get("property_type"):
        req["property_type"] = data["property_type"].strip()
    cid = db.create_client(
        broker_id,
        name=name,
        phone=(data.get("phone") or "").strip(),
        requirements_raw=(data.get("requirements_raw") or "").strip(),
        requirements=req,
        urgency=data.get("urgency") or "normal",
    )
    return {"id": cid}, 200


def update_client_api(broker_id, client_id, fields):
    """PUT /api/client/<id> — update allowed fields."""
    c = db.get_client(client_id)
    if not c or c.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    allowed = {"name", "phone", "requirements_raw", "status",
               "urgency", "notes", "budget_min", "budget_max",
               "bedrooms", "district", "property_type"}
    clean = {k: v for k, v in (fields or {}).items() if k in allowed}
    if not clean:
        return {"error": "no_fields"}, 400
    db.update_client(client_id, **clean)
    return {"ok": True}, 200


def add_client_note_api(broker_id, client_id, note):
    """POST /api/client/<id>/notes — append a note."""
    c = db.get_client(client_id)
    if not c or c.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    note = (note or "").strip()
    if not note:
        return {"error": "empty"}, 400
    db.add_note(client_id, note)
    return {"ok": True}, 200


# ---------------------------------------------------------------- viewings

def create_viewing_api(broker_id, data):
    """POST /api/viewings — schedule a viewing."""
    data = data or {}
    vid = db.create_viewing(
        broker_id,
        client_id=data.get("client_id"),
        client_name=(data.get("client_name") or "").strip(),
        listing_ids=data.get("listing_ids") or [],
        scheduled_at=data.get("scheduled_at"),
        notes=(data.get("notes") or "").strip(),
    )
    return {"id": vid}, 200


def list_viewings_api(broker_id, upcoming_only=True):
    """GET /api/viewings — broker's viewings."""
    vws = db.list_viewings(broker_id, upcoming_only=upcoming_only, limit=50)
    return {"viewings": [
        {
            "id": v["id"],
            "client_id": v.get("client_id"),
            "client_name": v.get("client_name") or "",
            "listing_ids": v.get("listing_ids") or [],
            "scheduled_at": v.get("scheduled_at"),
            "status": v.get("status"),
            "notes": v.get("notes") or "",
        }
        for v in vws
    ]}, 200


# ---------------------------------------------------------------- deals / commission

def list_deals_api(broker_id, month=None):
    """GET /api/deals — deals with monthly summary.

    month: "YYYY-MM" or None for current month.
    """
    import datetime as _dt
    from db import vntime
    # month boundaries are Vietnam midnights, not the host's
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            start = vntime.to_ts(_dt.datetime(y, m, 1))
            # first day of next month
            nm = m + 1
            ny = y + (1 if nm > 12 else 0)
            nm = nm if nm <= 12 else 1
            end = vntime.to_ts(_dt.datetime(ny, nm, 1))
        except (ValueError, TypeError):
            return {"error": "bad_month"}, 400
    else:
        now = vntime.now()
        start = vntime.to_ts(_dt.datetime(now.year, now.month, 1))
        end = time.time() + 86400

    deals = db.list_deals(broker_id, start_ts=start, end_ts=end, limit=100)
    total = 0
    closed = []
    negotiating = []
    for d in deals:
        amt = d.get("commission_vnd") or 0
        paid = bool(d.get("paid"))
        item = {
            "id": d["id"],
            "client_name": d.get("client_name") or "",
            "listing_id": d.get("listing_id") or "",
            "commission_vnd": amt,
            "paid": paid,
            "notes": d.get("notes") or "",
            "closed_at": d.get("closed_at"),
        }
        if paid:
            closed.append(item)
            total += amt
        else:
            negotiating.append(item)
    return {
        "month_total": total,
        "month": month or vntime.now().strftime("%Y-%m"),
        "closed": closed,
        "negotiating": negotiating,
    }, 200


def create_deal_api(broker_id, data):
    """POST /api/deals — record a deal/commission."""
    data = data or {}
    try:
        amount = float(data.get("commission_amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    did = db.create_deal(
        broker_id,
        client_id=data.get("client_id"),
        client_name=(data.get("client_name") or "").strip(),
        listing_id=data.get("listing_id"),
        commission_vnd=amount,
        notes=(data.get("notes") or "").strip(),
    )
    return {"id": did}, 200


# ---------------------------------------------------------------- broker profile

def get_profile_api(broker_id):
    """GET /api/profile — broker info + reputation + stats."""
    b = db.get_broker(broker_id) or {}
    score = utils.broker_profile_score(broker_id)
    stats = {}
    try:
        listings = db.list_broker_listings(broker_id, limit=10000, offset=0)
        stats["total_listings"] = len(listings)
        stats["active_listings"] = len(
            [l for l in listings if l.get("status") in ("submitted",)])
        stats["rented_listings"] = len(
            [l for l in listings if l.get("status") == "rented"])
    except Exception:
        stats = {"total_listings": 0, "active_listings": 0,
                 "rented_listings": 0}
    # view count from shares
    try:
        shares = db.list_share_pages(broker_id)
        stats["share_views"] = sum(s.get("view_count") or 0 for s in shares)
    except Exception:
        stats["share_views"] = 0
    return {
        "name": b.get("display_name") or b.get("username") or "",
        "phone": b.get("phone") or "",
        "pronoun": b.get("pronoun") or "anh",
        "tier": db.get_tier(broker_id),
        "score": score.get("score"),
        "completeness": score.get("completeness"),
        "freshness": score.get("freshness"),
        "complete_listings": score.get("complete_listings"),
        "fresh_listings": score.get("fresh_listings"),
        "false_refresh_reports": score.get("false_refresh_reports") or 0,
        "stats": stats,
    }, 200


def update_profile_api(broker_id, fields):
    """PUT /api/profile — update display name / phone / pronoun."""
    allowed = {"display_name", "phone", "pronoun"}
    clean = {k: v for k, v in (fields or {}).items() if k in allowed}
    if not clean:
        return {"error": "no_fields"}, 400
    db.update_broker(broker_id, **clean)
    return {"ok": True}, 200


# ---------------------------------------------------------------- notify prefs

def get_notify_prefs_api(broker_id):
    """GET /api/notify/prefs."""
    prefs = db.get_notify_prefs(broker_id)
    labels = {
        "notify_match": "🎯 Lead phù hợp",
        "notify_quality": "📉 Điểm tin giảm",
        "notify_trial": "🎁 Sắp hết lượt thử",
        "notify_booking": "📅 Khách đặt lịch",
    }
    return {"prefs": [
        {"key": k, "label": labels.get(k, k), "enabled": bool(v)}
        for k, v in prefs.items()
    ]}, 200


def set_notify_pref_api(broker_id, pref, value):
    """PUT /api/notify/prefs — toggle one preference."""
    if pref not in db.NOTIFY_PREFS:
        return {"error": "unknown_pref"}, 400
    db.set_notify_pref(broker_id, pref, bool(value))
    return {"ok": True, "pref": pref, "enabled": bool(value)}, 200


# ---------------------------------------------------------------- premium

def request_premium_api(broker_id, tier):
    """POST /api/premium/request — broker asks for Pro/Max upgrade."""
    if tier not in ("pro", "max"):
        return {"error": "bad_tier"}, 400
    existing = db.get_pending_premium_request(broker_id)
    if existing:
        return {"error": "already_pending",
                "error_vi": "Yêu cầu nâng cấp đang chờ duyệt"}, 409
    rid = db.create_premium_request(broker_id, tier_requested=tier)
    # Notify Khanh via outbox -> bot DM (same as bot flow's direct DM).
    # Without this, webapp upgrade requests sit silently in the DB.
    try:
        broker = db.get_broker(broker_id) or {}
        db.queue_notification(
            "premium_request", None,
            {"broker_id": broker_id,
             "request_id": rid,
             "tier": tier,
             "broker_name": (broker.get("display_name")
                             or broker.get("username")
                             or str(broker_id))})
    except Exception:
        pass
    return {"id": rid, "tier": tier}, 200
