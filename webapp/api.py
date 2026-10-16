"""API logic for the TrueNest broker webapp.

All data access goes through the parent package's db.py — no duplicated
SQL or schema knowledge here. Functions take plain arguments and return
(JSON-serializable dict, http_status) tuples.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import utils  # noqa: E402
import schema as master_schema  # noqa: E402


# ---------------------------------------------------------------- helpers

def _fmt_price(vnd):
    """12_500_000 -> '12.5tr', 7_000_000 -> '7tr'."""
    if not vnd:
        return "—"
    try:
        tr = float(vnd) / 1_000_000
    except (TypeError, ValueError):
        return "—"
    s = f"{tr:.1f}".rstrip("0").rstrip(".")
    return f"{s}tr"


def _bedroom_label(br, ptype):
    if ptype == "studio":
        return "Studio"
    if br is None:
        return "—"
    try:
        n = int(float(br))
    except (TypeError, ValueError):
        return "—"
    return f"{n}PN"


def _title(parsed):
    """Short title like '2PN An Thượng' or 'Studio Monarchy'."""
    br = _bedroom_label(parsed.get("bedrooms"), parsed.get("property_type"))
    place = parsed.get("building_name") or parsed.get("district") or ""
    return f"{br} {place}".strip()


def listing_summary(row):
    """Compact dict for the list view. Fields follow canonical master schema."""
    p = master_schema.normalize_parsed(row.get("parsed") or {})
    photo_count = len(row.get("photo_file_ids") or [])
    score, _ = master_schema.quality_score(p, photo_count)
    return {
        "id": row["id"],
        "title": _title(p),
        "price": _fmt_price(p.get("price_vnd")),
        "price_vnd": p.get("price_vnd"),
        "bedrooms": p.get("bedrooms"),
        "bedroom_label": _bedroom_label(p.get("bedrooms"),
                                        p.get("property_type")),
        "area_m2": p.get("area_m2"),
        "bathrooms": p.get("bathrooms"),
        "district": p.get("district"),
        "status": row.get("status"),
        "photo_count": photo_count,
        "photo_urls": list(row.get("photo_urls") or []),
        "has_post": bool(db.get_saved_post_langs(row["id"])),
        "created_at": row.get("created_at"),
        "quality_score": score,
        "ai_scored": True,
    }


def listing_detail(row):
    """Full detail dict for the detail view. Fields follow canonical master schema."""
    p = master_schema.normalize_parsed(row.get("parsed") or {})
    d = listing_summary(row)
    photo_count = len(row.get("photo_file_ids") or [])
    score, missing = master_schema.quality_score(p, photo_count)
    d.update({
        "raw_text": row.get("raw_text", ""),
        "address": p.get("street"),
        "building_name": p.get("building_name"),
        "furnishing": p.get("furnishing"),
        "pet_friendly": p.get("pet_friendly"),
        "amenities": p.get("amenities"),
        "highlights": p.get("highlights"),
        "phone": p.get("primary_phone"),
        "deposit_months": p.get("deposit_months"),
        "available_from": p.get("available_from"),
        "property_type": p.get("property_type"),
        "floor_number": p.get("floor_number"),
        "post_langs": db.get_saved_post_langs(row["id"]),
        "missing_fields": row.get("missing_fields") or [],
        "quality_score": score,
        "quality_missing": missing,
        "ai_scored": True,
        "schema_version": "1.0",
    })
    return d


# ---------------------------------------------------------------- endpoints

def get_listings(broker_id, q=None, bedrooms=None, status=None,
                 limit=50, offset=0, min_price=None, max_price=None,
                 min_score=None, district=None, furnishing=None,
                 pet_friendly=None, min_area=None, property_type=None,
                 ids=None):
    """GET /api/listings — filters map to schema FILTER_GROUPS.

    ids: optional list of listing IDs to return (broker ownership checked).
    Used by batch deep links (?view=batch&ids=...).
    """
    # Batch/deep-link mode: return exactly these IDs (ownership-checked).
    if ids:
        items = []
        for lid in ids:
            row = db.get_listing(lid)
            if row and row.get("broker_id") == broker_id:
                items.append(listing_summary(row))
        return {"items": items, "total": len(items),
                "limit": limit, "offset": 0,
                "filter_groups": master_schema.FILTER_GROUPS}, 200

    filters = {}
    if bedrooms:
        if bedrooms == "studio":
            filters["property_type"] = "studio"
        elif bedrooms.endswith("+"):
            try:
                filters["min_bedrooms"] = float(bedrooms[:-1])
            except ValueError:
                pass
        else:
            try:
                filters["bedrooms"] = float(bedrooms)
            except ValueError:
                pass
    if status:
        filters["status"] = status
    if property_type:
        filters["property_type"] = property_type
    if district:
        filters["district"] = district

    if filters:
        rows = db.search_listings(broker_id, filters, limit=200, offset=0)
    else:
        rows = db.list_broker_listings(broker_id, limit=200, offset=0)

    items = []
    for r in rows:
        p = master_schema.normalize_parsed(r.get("parsed") or {})
        photo_count = len(r.get("photo_file_ids") or [])
        score, _ = master_schema.quality_score(p, photo_count)

        # Python-side filters (not in db.search_listings)
        price = p.get("price_vnd")
        if min_price and (not price or price < min_price):
            continue
        if max_price and (not price or price > max_price):
            continue
        if min_score and score < min_score:
            continue
        if furnishing and p.get("furnishing") != furnishing:
            continue
        if pet_friendly is not None and p.get("pet_friendly") != pet_friendly:
            continue
        area = p.get("area_m2")
        if min_area and (not area or area < min_area):
            continue

        items.append(listing_summary(r))

    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["title"].lower()]

    total = len(items)
    items = items[offset:offset + limit]
    return {"items": items, "total": total,
            "limit": limit, "offset": offset,
            "filter_groups": master_schema.FILTER_GROUPS}, 200


def get_listing(broker_id, listing_id):
    """GET /api/listing/<id>"""
    row = db.get_listing(listing_id)
    if not row or row.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    return listing_detail(row), 200


# Fields the webapp is allowed to edit, mapped to update_listing_field keys.
EDITABLE_FIELDS = {
    "price_vnd", "bedrooms", "bathrooms", "area_m2", "district",
    "street", "building_name", "furnished", "pet_friendly",
    "deposit", "description",
}


def update_listing(broker_id, listing_id, fields):
    """PUT /api/listing/<id>  — fields: {name: value}"""
    row = db.get_listing(listing_id)
    if not row or row.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    updated = []
    for name, value in (fields or {}).items():
        if name not in EDITABLE_FIELDS:
            continue
        if name == "description":
            ok = db.update_listing_field(listing_id, "description", value,
                                         changed_by="webapp")
        elif name in ("district", "street", "building_name"):
            ok = db.update_listing_field(
                listing_id, "location", {name: value}, changed_by="webapp")
        else:
            # numeric fields: coerce
            if name in ("price_vnd", "bedrooms", "bathrooms", "area_m2"):
                try:
                    value = float(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    continue
            ok = db.update_listing_field(listing_id, name, value,
                                         changed_by="webapp")
        if ok:
            updated.append(name)
    fresh = db.get_listing(listing_id)
    return {"updated": updated, "listing": listing_detail(fresh)}, 200


def set_status(broker_id, listing_id, status):
    """PUT /api/listing/<id>/status — {status}"""
    row = db.get_listing(listing_id)
    if not row or row.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    ok = db.set_listing_status(listing_id, status, changed_by="webapp")
    if not ok:
        return {"error": "invalid_status"}, 400
    return {"status": status}, 200


def get_post(broker_id, listing_id, lang="vi"):
    """GET /api/post/<id>?lang=vi"""
    row = db.get_listing(listing_id)
    if not row or row.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    text = db.get_saved_post(listing_id, lang=lang)
    return {"lang": lang, "text": text,
            "langs": db.get_saved_post_langs(listing_id)}, 200


def put_post(broker_id, listing_id, lang, text):
    """PUT /api/post/<id> — {lang, text}"""
    row = db.get_listing(listing_id)
    if not row or row.get("broker_id") != broker_id:
        return {"error": "not_found"}, 404
    if lang not in ("vi", "en", "ko", "zh", "ru"):
        return {"error": "invalid_lang"}, 400
    db.save_post(listing_id, text or "", lang=lang)
    return {"lang": lang,
            "langs": db.get_saved_post_langs(listing_id)}, 200


# ---------------------------------------------------------------- trials

def get_trial(broker_id, feature):
    """GET /api/trial/<feature> — trial status for a paywalled feature."""
    if feature not in db.TRIAL_FEATURES:
        return {"error": "unknown_feature"}, 404
    allowed, remaining = db.check_trial(broker_id, feature)
    return {
        "feature": feature,
        "allowed": allowed,
        "remaining": remaining,  # -1 = unlimited (tier covers it)
        "limit": db.TRIAL_LIMITS[feature],
        "required_tier": db.TRIAL_TIER[feature],
    }, 200


def use_trial(broker_id, feature):
    """POST /api/trial/<feature>/use — consume one trial use."""
    if feature not in db.TRIAL_FEATURES:
        return {"error": "unknown_feature"}, 404
    allowed, remaining = db.check_trial(broker_id, feature)
    if not allowed:
        return {"error": "trial_exhausted",
                "required_tier": db.TRIAL_TIER[feature]}, 402
    if remaining == -1:
        # Tier covers it — no trial consumed.
        return {"feature": feature, "used": db.get_trial_usage(broker_id, feature),
                "remaining": -1, "limit": db.TRIAL_LIMITS[feature]}, 200
    used = db.increment_trial_usage(broker_id, feature)
    return {"feature": feature, "used": used,
            "remaining": db.TRIAL_LIMITS[feature] - used,
            "limit": db.TRIAL_LIMITS[feature]}, 200


def require_trial(broker_id, feature):
    """Gate helper for paywalled endpoints.

    Returns None when the broker may proceed (tier covers it or trial
    available — the caller should then call use_trial after success).
    Returns (error_dict, 402) when trials are exhausted.
    """
    if feature not in db.TRIAL_FEATURES:
        return {"error": "unknown_feature"}, 404
    allowed, _ = db.check_trial(broker_id, feature)
    if not allowed:
        return {"error": "trial_exhausted",
                "required_tier": db.TRIAL_TIER[feature]}, 402
    return None


# ---------------------------------------------------------------- share pages

def create_share(broker_id, listing_ids, title="", client_id=None):
    """POST /api/share — create a public share page (trial-gated: send2client)."""
    gate = require_trial(broker_id, "send2client")
    if gate:
        return gate
    valid = []
    for lid in (listing_ids or []):
        row = db.get_listing(lid)
        if row and row.get("broker_id") == broker_id:
            valid.append(lid)
    if not valid:
        return {"error": "no_valid_listings"}, 400
    token = db.create_share_page(broker_id, valid, title=title,
                                 client_id=client_id)
    use_trial(broker_id, "send2client")  # consume trial (no-op if tier-covered)
    import config  # noqa: E402
    url = f"{config.WEBAPP_URL.rstrip('/')}/s/{token}"
    return {"token": token, "url": url,
            "listing_count": len(valid)}, 200


def list_shares(broker_id):
    """GET /api/shares — broker's share pages with views + bookings."""
    out = []
    for p in db.list_share_pages(broker_id):
        bookings = db.list_share_bookings(token=p["token"])
        out.append({
            "token": p["token"],
            "title": p["title"],
            "client_id": p["client_id"],
            "listing_count": len(p["listing_ids"]),
            "view_count": p["view_count"],
            "booking_count": len(bookings),
            "bookings": bookings,
            "created_at": p["created_at"],
            "expires_at": p["expires_at"],
        })
    return {"shares": out}, 200


# ---------------------------------------------------------------- propose flow

def get_propose(broker_id, request_id):
    """GET /api/propose/<request_id> — broker's propose view data.

    Returns request info, slot status, and own inventory scored by match.
    """
    import time
    import feat_match

    req = db.get_propose_request(request_id)
    if not req:
        return {"error": "not_found"}, 404

    now = time.time()
    expires_at = req.get("expires_at")
    expired = bool(expires_at and expires_at < now)

    has_slot = db.check_broker_slot(request_id, broker_id)
    existing = db.get_propose_response(request_id, broker_id)
    already_submitted = existing["listing_ids"] if existing else []

    # Build client requirements dict for score_match
    client = {
        "budget_min": req.get("budget_min"),
        "budget_max": req.get("budget_max"),
        "bedrooms": req.get("bedrooms"),
        "district": req.get("district"),
        "property_type": req.get("property_type"),
    }

    # Score own inventory — hard-filtered FIRST by the lead's hard criteria
    # (Khanh 2026-10-16: no bypass, prevents irrelevant submissions).
    rows = db.list_broker_listings(broker_id, limit=200, offset=0)
    eligible, failed_summary = feat_match.filter_hard_criteria(rows, client)
    scored = []
    for r in eligible:
        try:
            ms = feat_match.score_match(r, client)
        except Exception:
            ms = 0
        p = master_schema.normalize_parsed(r.get("parsed") or {})
        photo_count = len(r.get("photo_file_ids") or [])
        qs, missing_detailed, potential = master_schema.quality_breakdown(
            p, photo_count)
        item = listing_summary(r)
        item["match_score"] = round(ms, 1)
        item["quality_score"] = qs
        # Detailed quality info for improvement suggestions (Khanh 2026-10-16)
        item["quality_missing"] = [
            {"label": label, "weight": w} for label, w in missing_detailed
        ]
        item["potential_score"] = potential
        scored.append(item)
    scored.sort(key=lambda x: x["match_score"], reverse=True)

    # Slot reopening (Khanh 2026-10-16): if this broker reserved a slot but
    # hard-filtering leaves 0 eligible listings AND they haven't submitted,
    # release the slot so waitlisted brokers get a second chance.
    slot_released = False
    if has_slot and not already_submitted and not scored and not expired:
        if db.release_empty_slot(request_id, broker_id):
            slot_released = True
            has_slot = False
            # Queue channel notification for the bot to send
            db.queue_notification(
                "slot_reopened",
                request_id=request_id,
                payload={
                    "summary": req.get("requirements_summary") or "",
                    "released_broker_id": broker_id,
                },
            )

    return {
        "request": {
            "id": request_id,
            "summary": req.get("requirements_summary") or "",
            "requirements": client,
            "requirements_raw": req.get("requirements_raw") or "",
            "urgency": req.get("urgency") or "normal",
            "expires_at": expires_at,
            "expired": expired,
            "status": req.get("status"),
        },
        "has_slot": has_slot,
        "slot_released": slot_released,
        "already_submitted": already_submitted,
        "listings": scored,
        "failed_summary": failed_summary,
        "max_listings": db.PROPOSE_MAX_LISTINGS,
    }, 200


def get_xbroker_requests(broker_id):
    """GET /api/xbroker — open broadcast requests needing cross-broker help.

    Trial-gated: uses the existing xbroker_match trial (3 free → Max).
    """
    trial_ok, remaining = db.check_trial(broker_id, "xbroker_match")
    reqs = db.list_open_xbroker_requests(exclude_broker_id=broker_id)
    items = []
    for r in reqs:
        items.append({
            "id": r["id"],
            "summary": r.get("requirements_summary") or "",
            "urgency": r.get("urgency") or "normal",
            "response_count": r.get("response_count", 0),
            "max_responders": db.MAX_RESPONDERS,
            "created_at": r.get("created_at"),
            "budget_max": r.get("budget_max"),
            "bedrooms": r.get("bedrooms"),
            "district": r.get("district"),
        })
    return {
        "requests": items,
        "trial": {"allowed": trial_ok, "remaining": remaining,
                  "required_tier": "max"},
    }, 200


def submit_propose(broker_id, request_id, listing_ids):
    """POST /api/propose/<request_id> — save broker's proposed listings."""
    import time

    req = db.get_propose_request(request_id)
    if not req:
        return {"error": "not_found"}, 404

    now = time.time()
    if req.get("expires_at") and req["expires_at"] < now:
        return {"error": "expired",
                "error_vi": "Hết giờ rồi ạ, slot đã chuyển cho người tiếp theo."}, 410

    if not db.check_broker_slot(request_id, broker_id):
        return {"error": "no_slot",
                "error_vi": "Anh chưa giữ slot cho yêu cầu này."}, 403

    if not isinstance(listing_ids, list):
        return {"error": "bad_request"}, 400
    # Deduplicate, preserve order, cap at max
    seen = set()
    listing_ids = [lid for lid in listing_ids
                   if not (lid in seen or seen.add(lid))]
    listing_ids = listing_ids[:db.PROPOSE_MAX_LISTINGS]

    # Validate ownership
    valid = []
    for lid in listing_ids:
        row = db.get_listing(lid)
        if row and row.get("broker_id") == broker_id:
            valid.append(lid)

    # Hard-filter server-side too — frontend filtering alone is bypassable
    # (Khanh 2026-10-16: hard criteria cannot be disabled).
    import feat_match
    client = {
        "budget_min": req.get("budget_min"),
        "budget_max": req.get("budget_max"),
        "bedrooms": req.get("bedrooms"),
        "district": req.get("district"),
        "property_type": req.get("property_type"),
    }
    rows_by_id = {lid: db.get_listing(lid) for lid in valid}
    eligible, _ = feat_match.filter_hard_criteria(
        [r for r in rows_by_id.values() if r], client)
    eligible_ids = {r["id"] for r in eligible}
    valid = [lid for lid in valid if lid in eligible_ids]
    if not valid:
        return {"error": "no_eligible",
                "error_vi": "Không có tin nào đạt tiêu chí cứng của lead."}, 422

    # Compute match scores for storage
    scores = {}
    for lid in valid:
        row = rows_by_id[lid]
        try:
            scores[lid] = round(feat_match.score_match(row, client), 1)
        except Exception:
            scores[lid] = 0

    db.save_propose_response(request_id, broker_id, valid, scores)
    return {"ok": True, "submitted_count": len(valid),
            "submitted_ids": valid}, 200
