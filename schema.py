"""Canonical master schema for TrueNest listings.

Single source of truth for listing fields. Both the Telegram bot and the
web app use this schema — no field should exist outside it.
"""

# Field: (type, required, weight_in_quality_score, vietnamese_label)
MASTER_SCHEMA = {
    # Critical — listing is unusable without these
    "price_vnd":      ("number",  True,  20, "Giá thuê"),
    "primary_phone":  ("string",  True,  15, "SĐT liên hệ"),
    "photos":         ("array",   True,  15, "Ảnh (tối thiểu 3)"),
    # Important
    "bedrooms":       ("number",  False, 10, "Số phòng ngủ"),
    "district":       ("string",  False, 10, "Khu vực"),
    "area_m2":        ("number",  False, 10, "Diện tích"),
    "description":    ("string",  False, 10, "Mô tả chi tiết"),
    # Nice to have
    "bathrooms":      ("number",  False, 5,  "Số WC"),
    "property_type":  ("string",  False, 5,  "Loại hình"),
    "furnishing":     ("string",  False, 5,  "Nội thất"),
    "pet_friendly":   ("boolean", False, 5,  "Chính sách pet"),
    "street":         ("string",  False, 0,  "Đường"),
    "building_name":  ("string",  False, 0,  "Tòa nhà"),
    "deposit_months": ("number",  False, 0,  "Đặt cọc (tháng)"),
    "amenities":      ("array",   False, 0,  "Tiện ích"),
    "highlights":     ("array",   False, 0,  "Điểm nổi bật"),
    "floor_number":   ("number",  False, 0,  "Tầng"),
    "available_from": ("string",  False, 0,  "Ngày trống"),
}

CRITICAL_FIELDS = [k for k, v in MASTER_SCHEMA.items() if v[1]]

# Non-scored storage fields (documented for reference, not part of scoring):
# - photo_file_ids: Telegram file_ids for bot sending
# - photo_urls: public R2 URLs for web app display
# - photo_hashes: {r2_url: 16-char hex dhash} for image duplicate detection.
#   None-valued hashes are not stored (PIL missing at upload time).
NON_SCORED_FIELDS = {
    "photo_file_ids": "Telegram file_id list (bot sending)",
    "photo_urls": "R2 public URL list (web app display)",
    "photo_hashes": "{r2_url: dhash hex} — image duplicate detection",
}

# Filter groups for the web app — each group maps to UI filter controls
FILTER_GROUPS = {
    "price": {
        "label": "💰 Giá thuê",
        "fields": ["price_vnd"],
        "type": "range",  # min-max slider
        "unit": "tr",
    },
    "rooms": {
        "label": "🛏️ Phòng",
        "fields": ["bedrooms", "bathrooms", "property_type"],
        "type": "chips",
    },
    "location": {
        "label": "📍 Vị trí",
        "fields": ["district", "building_name"],
        "type": "select",
    },
    "features": {
        "label": "✨ Tiện ích",
        "fields": ["furnishing", "pet_friendly", "area_m2"],
        "type": "chips",
    },
    "quality": {
        "label": "🤖 Chất lượng AI",
        "fields": ["quality_score"],
        "type": "range",
        "unit": "đ",
    },
    "status": {
        "label": "📊 Trạng thái",
        "fields": ["status"],
        "type": "chips",
    },
}

# Mapping from DB `parsed` keys to schema keys (handles legacy aliases)
FIELD_ALIASES = {
    "furnished": "furnishing",
    "deposit": "deposit_months",
}


def normalize_parsed(parsed):
    """Map legacy/alias keys to canonical schema keys."""
    out = {}
    for k, v in (parsed or {}).items():
        ck = FIELD_ALIASES.get(k, k)
        if ck in MASTER_SCHEMA:
            out[ck] = v
        else:
            out[k] = v  # keep unknown fields, don't drop data
    return out


def quality_score(parsed, photo_count=0):
    """0-100 score based on MASTER_SCHEMA weights. Returns (score, [missing labels])."""
    p = normalize_parsed(parsed)
    score = 0
    missing = []
    for field, (ftype, required, weight, label) in MASTER_SCHEMA.items():
        if weight == 0:
            continue
        if field == "photos":
            ok = photo_count >= 3
        elif field == "description":
            ok = len(str(p.get(field) or "")) > 50
        elif ftype == "boolean":
            ok = p.get(field) is not None
        else:
            ok = bool(p.get(field))
        if ok:
            score += weight
        else:
            missing.append(label)
    return min(score, 100), missing
