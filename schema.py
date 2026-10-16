"""Canonical master schema for TrueNest listings.

Single source of truth for listing fields. Both the Telegram bot and the
web app use this schema — no field should exist outside it.
"""

# Field: (type, required, weight_in_quality_score, vietnamese_label)
#
# QUALITY WEIGHTS — MUST SUM TO EXACTLY 100 (rebalanced 2026-10-16, v2: amenities/highlights scored)
# ┌─────────────────┬────────┐
# │ price_vnd       │ 12     │ Giá thuê
# │ primary_phone   │  5     │ SĐT liên hệ
# │ photos          │ 10     │ Ảnh (≥3)
# │ bedrooms        │  8     │ Số phòng ngủ
# │ bathrooms       │  6     │ Số WC
# │ property_type   │  5     │ Loại hình
# │ district        │ 10     │ Khu vực
# │ street          │  6     │ Địa chỉ chi tiết
# │ area_m2         │  6     │ Diện tích
# │ furnishing      │  6     │ Nội thất
# │ description     │  6     │ Mô tả (>50 ký tự)
# │ deposit_months  │  2     │ Đặt cọc
# │ amenities       │ 10     │ Tiện ích (VD: hồ bơi, gym...)
# │ highlights      │  8     │ Điểm nổi bật
# ├─────────────────┼────────┤
# │ TOTAL           │ 100    │
# └─────────────────┴────────┘
# pet_friendly/building_name/floor_number/available_from = 0
# (tracked but not scored — informational fields)
MASTER_SCHEMA = {
    # Critical — listing is unusable without these
    "price_vnd":      ("number",  True,  12, "Giá thuê"),
    "primary_phone":  ("string",  True,   5, "SĐT liên hệ"),
    "photos":         ("array",   True,  10, "Ảnh (tối thiểu 3)"),
    # Important
    "bedrooms":       ("number",  False,  8, "Số phòng ngủ"),
    "bathrooms":      ("number",  False,  6, "Số WC"),
    "property_type":  ("string",  False,  5, "Loại hình"),
    "district":       ("string",  False, 10, "Khu vực"),
    "street":         ("string",  False,  6, "Địa chỉ chi tiết"),
    "area_m2":        ("number",  False,  6, "Diện tích"),
    "furnishing":     ("string",  False,  6, "Nội thất"),
    "description":    ("string",  False,  6, "Mô tả chi tiết"),
    "deposit_months": ("number",  False,  2, "Đặt cọc (tháng)"),
    # Amenities & highlights — what clients actually care about
    "amenities":      ("array",   False, 10, "Tiện ích"),
    "highlights":     ("array",   False,  8, "Điểm nổi bật"),
    # Nice to have (informational, not scored)
    "pet_friendly":   ("boolean", False,  0, "Chính sách pet"),
    "building_name":  ("string",  False,  0, "Tòa nhà"),
    "floor_number":   ("number",  False,  0, "Tầng"),
    "available_from": ("string",  False,  0, "Ngày trống"),
}

CRITICAL_FIELDS = [k for k, v in MASTER_SCHEMA.items() if v[1]]

# Guard: weights must total exactly 100 — a perfect listing scores 100, no cap needed
_TOTAL_WEIGHT = sum(w for _, _, w, _ in MASTER_SCHEMA.values())
assert _TOTAL_WEIGHT == 100, f"MASTER_SCHEMA weights must sum to 100, got {_TOTAL_WEIGHT}"

# Non-scored storage fields (documented for reference, not part of scoring):
# - photo_file_ids: Telegram file_ids for bot sending
# - photo_urls: public R2 URLs for web app display
# - photo_hashes: {r2_url: 16-char hex dhash} for image duplicate detection.
# - photo_phashes: {r2_url: 16-char hex phash (DCT)} — second signal.
#   None-valued hashes are not stored (PIL missing at upload time).
NON_SCORED_FIELDS = {
    "photo_file_ids": "Telegram file_id list (bot sending)",
    "photo_urls": "R2 public URL list (web app display)",
    "photo_hashes": "{r2_url: dhash hex} — image duplicate detection",
    "photo_phashes": "{r2_url: phash hex} — image duplicate detection",
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


def quality_breakdown(parsed, photo_count=0):
    """Detailed breakdown: (score, [(label, weight), ...] missing, potential_score).

    potential_score = score + sum of weights of all missing fields
    (i.e. score achievable if broker fills everything).
    """
    p = normalize_parsed(parsed)
    score = 0
    missing = []  # [(label, weight)]
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
            missing.append((label, weight))
    score = min(score, 100)
    potential = min(score + sum(w for _, w in missing), 100)
    return score, missing, potential
