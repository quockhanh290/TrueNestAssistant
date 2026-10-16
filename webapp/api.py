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
