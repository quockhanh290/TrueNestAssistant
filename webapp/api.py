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
                 limit=50, offset=0):
    """GET /api/listings"""
    if q or bedrooms or status:
        filters = {}
        if q:
            # search_listings has no free-text; filter client-side instead
            pass
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
        rows = db.search_listings(broker_id, filters, limit=limit,
                                  offset=offset)
    else:
        rows = db.list_broker_listings(broker_id, limit=limit, offset=offset)
    items = [listing_summary(r) for r in rows]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["title"].lower()]
    total = db.count_broker_listings(broker_id)
    return {"items": items, "total": total,
            "limit": limit, "offset": offset}, 200


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
