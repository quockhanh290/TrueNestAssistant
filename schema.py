"""Canonical master schema for TrueNest listings.

Single source of truth for listing fields. Both the Telegram bot and the
web app use this schema — no field should exist outside it.
"""

# Field: (type, required, weight_in_quality_score, vietnamese_label)
#
# QUALITY WEIGHTS — MUST SUM TO EXACTLY 100 (rebalanced 2026-10-16, v3: address detail by property type)
# ┌─────────────────┬────────┐
# │ price_vnd       │ 10     │ Giá thuê
# │ primary_phone   │  5     │ SĐT liên hệ
# │ photos          │  8     │ Ảnh (≥3)
# │ bedrooms        │  8     │ Số phòng ngủ
# │ bathrooms       │  6     │ Số WC
# │ property_type   │  5     │ Loại hình
# │ district        │  8     │ Khu vực
# │ street          │  8     │ Địa chỉ chi tiết (số nhà + tên đường)
# │ area_m2         │  6     │ Diện tích
# │ furnishing      │  4     │ Nội thất
# │ description     │  6     │ Mô tả (>50 ký tự)
# │ deposit_months  │  2     │ Đặt cọc
# │ amenities       │  8     │ Tiện ích (VD: hồ bơi, gym...)
# │ highlights      │  6     │ Điểm nổi bật
# │ building_name   │  4     │ Tên tòa nhà/dự án (căn hộ)
# │ floor_number    │  2     │ Số tầng (căn hộ)
# │ balcony_direction│ 2     │ Hướng ban công (căn hộ)
# │ view            │  2     │ View (căn hộ)
# ├─────────────────┼────────┤
# │ TOTAL           │ 100    │
# └─────────────────┴────────┘
# pet_friendly/available_from = 0 (tracked but not scored — informational)
#
# ADDRESS DETAIL BY PROPERTY TYPE (Khanh 2026-10-16):
# - Nhà riêng/villa/nhà phố: số nhà + tên đường cụ thể → street (8đ)
# - Căn hộ/chung cư: tên dự án/tòa nhà + số tầng + số phòng,
#   hướng ban công, view → building_name (4đ) + floor_number (2đ)
#   + balcony_direction (2đ) + view (2đ) = 10đ
# Exact address is HIDDEN from clients (share page shows district only).
# It's for internal dedup/matching — brokers can enter truthfully.
MASTER_SCHEMA = {
    # Critical — listing is unusable without these
    "price_vnd":      ("number",  True,  10, "Giá thuê"),
    "primary_phone":  ("string",  True,   5, "SĐT liên hệ"),
    "photos":         ("array",   True,   8, "Ảnh (tối thiểu 3)"),
    # Important
    "bedrooms":       ("number",  False,  8, "Số phòng ngủ"),
    "bathrooms":      ("number",  False,  6, "Số WC"),
    "property_type":  ("string",  False,  5, "Loại hình"),
    "district":       ("string",  False,  8, "Khu vực"),
    "street":         ("string",  False,  8, "Địa chỉ chi tiết"),
    "area_m2":        ("number",  False,  6, "Diện tích"),
    "furnishing":     ("string",  False,  4, "Nội thất"),
    "description":    ("string",  False,  6, "Mô tả chi tiết"),
    "deposit_months": ("number",  False,  2, "Đặt cọc (tháng)"),
    # Amenities & highlights — what clients actually care about
    "amenities":      ("array",   False,  8, "Tiện ích"),
    "highlights":     ("array",   False,  6, "Điểm nổi bật"),
    # Address detail — property-type specific (see comment above)
    "building_name":  ("string",  False,  4, "Tên tòa nhà/dự án"),
    "floor_number":   ("number",  False,  2, "Số tầng"),
    "balcony_direction": ("string", False, 2, "Hướng ban công"),
    "view":           ("string",  False,  2, "View"),
    # Nice to have (informational, not scored)
    "pet_friendly":   ("boolean", False,  0, "Chính sách pet"),
    "available_from": ("string",  False,  0, "Ngày trống"),
}

# Property types for address-detail scoring
HOUSE_TYPES = {"house", "villa", "townhouse", "nhà riêng", "biệt thự", "nhà phố"}
APARTMENT_TYPES = {"apartment", "condo", "căn hộ", "chung cư", "studio"}


def get_detail_fields_for_type(property_type):
    """Return (field, label, weight) tuples for address detail, by property type.
    Used by UI to prompt brokers for the right detail fields."""
    pt = str(property_type or "").lower().strip()
    if pt in HOUSE_TYPES:
        return [
            ("street", "Số nhà + tên đường cụ thể", 8),
        ]
    elif pt in APARTMENT_TYPES:
        return [
            ("building_name", "Tên dự án/tòa nhà", 4),
            ("floor_number", "Số tầng", 2),
            ("balcony_direction", "Hướng ban công", 2),
            ("view", "View (VD: biển, sông, thành phố)", 2),
        ]
    else:
        # Unknown type — suggest all
        return [
            ("street", "Địa chỉ chi tiết", 8),
            ("building_name", "Tên tòa nhà/dự án", 4),
            ("floor_number", "Số tầng", 2),
        ]

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
