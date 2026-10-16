"""Canonical master schema for TrueNest listings.

Single source of truth for listing fields. Both the Telegram bot and the
web app use this schema — no field should exist outside it.
"""

# Field: (type, required, weight_in_quality_score, vietnamese_label)
#
# QUALITY WEIGHTS — MUST SUM TO EXACTLY 100 (rebalanced 2026-10-16, v4)
# Per-item scoring: amenities +0.5 each (max 8), highlights +0.5 each (max 6).
# ┌─────────────────┬────────┐
# │ price_vnd       │  8     │ Giá thuê
# │ primary_phone   │  5     │ SĐT liên hệ
# │ photos          │  6     │ Ảnh (≥3)
# │ bedrooms        │  6     │ Số phòng ngủ
# │ bathrooms       │  6     │ Số WC
# │ property_type   │  5     │ Loại hình
# │ district        │  6     │ Khu vực
# │ street          │  6     │ Địa chỉ chi tiết (số nhà + tên đường)
# │ area_m2         │  9     │ Diện tích (nhà/căn hộ)
# │ furnishing      │  4     │ Nội thất
# │ description     │  4     │ Mô tả (>50 ký tự)
# │ deposit_months  │  2     │ Đặt cọc
# │ amenities       │  8     │ Tiện ích (+0.5 mỗi cái, tối đa 8)
# │ highlights      │  6     │ Điểm nổi bật (+0.5 mỗi cái, tối đa 6)
# │ building_name   │  4     │ Tên tòa nhà/dự án (căn hộ)
# │ floor_number    │  2     │ Số tầng (căn hộ)
# │ balcony_direction│ 2     │ Hướng ban công (căn hộ)
# │ view            │  2     │ View (căn hộ)
# │ unit_number     │  2     │ Số căn VD:A1502 (căn hộ)
# │ management_fee  │  2     │ Phí quản lý (căn hộ)
# │ alley_info      │  3     │ Hẻm/mặt tiền + độ rộng (nhà)
# │ house_floors    │  2     │ Số tầng của nhà (nhà)
# ├─────────────────┼────────┤
# │ TOTAL           │ 100    │
# └─────────────────┴────────┘
# pet_friendly/available_from = 0 (tracked but not scored — informational)
#
# ADDRESS DETAIL BY PROPERTY TYPE (Khanh 2026-10-16):
# - Nhà riêng/villa/nhà phố: số nhà + tên đường, hẻm/mặt tiền + độ rộng,
#   số tầng của nhà, diện tích nhà
# - Căn hộ/chung cư: tên dự án/tòa nhà + số tầng + số căn,
#   hướng ban công, view, phí quản lý, diện tích căn hộ
# Exact address is HIDDEN from clients (share page shows district only).
MASTER_SCHEMA = {
    # Critical — listing is unusable without these
    "price_vnd":      ("number",  True,   8, "Giá thuê"),
    "primary_phone":  ("string",  True,   5, "SĐT liên hệ"),
    "photos":         ("array",   True,   6, "Ảnh (tối thiểu 3)"),
    # Important
    "bedrooms":       ("number",  False,  6, "Số phòng ngủ"),
    "bathrooms":      ("number",  False,  6, "Số WC"),
    "property_type":  ("string",  False,  5, "Loại hình"),
    "district":       ("string",  False,  6, "Khu vực"),
    "street":         ("string",  False,  6, "Địa chỉ chi tiết"),
    "area_m2":        ("number",  False,  9, "Diện tích (nhà/căn hộ)"),
    "furnishing":     ("string",  False,  4, "Nội thất"),
    "description":    ("string",  False,  4, "Mô tả chi tiết"),
    "deposit_months": ("number",  False,  2, "Đặt cọc (tháng)"),
    # Amenities — per-item scoring (see AMENITY_POINT_PER_ITEM)
    "amenities":      ("array",   False,  8, "Tiện ích"),
    "highlights":     ("array",   False,  6, "Điểm nổi bật"),
    # Address detail — apartment
    "building_name":  ("string",  False,  4, "Tên tòa nhà/dự án"),
    "floor_number":   ("number",  False,  2, "Số tầng"),
    "balcony_direction": ("string", False, 2, "Hướng ban công"),
    "view":           ("string",  False,  2, "View"),
    "unit_number":    ("string",  False,  2, "Số căn (VD: A1502)"),
    "management_fee": ("number",  False,  2, "Phí quản lý (tr/tháng)"),
    # Address detail — house/villa
    "alley_info":     ("string",  False,  3, "Hẻm/mặt tiền + độ rộng"),
    "house_floors":   ("number",  False,  2, "Số tầng của nhà"),
    # Nice to have (informational, not scored)
    "pet_friendly":   ("boolean", False,  0, "Chính sách pet"),
    "available_from": ("string",  False,  0, "Ngày trống"),
}

# Per-item scoring: amenities +0.5 each (max 8), highlights +0.5 each (max 6)
AMENITY_POINT_PER_ITEM = 0.5
HIGHLIGHT_POINT_PER_ITEM = 0.5

# Property types for address-detail scoring
HOUSE_TYPES = {"house", "villa", "townhouse", "nhà riêng", "biệt thự", "nhà phố"}
APARTMENT_TYPES = {"apartment", "condo", "căn hộ", "chung cư", "studio"}


def get_detail_fields_for_type(property_type):
    """Return (field, label, weight) tuples for address detail, by property type.
    Used by UI to prompt brokers for the right detail fields."""
    pt = str(property_type or "").lower().strip()
    if pt in HOUSE_TYPES:
        return [
            ("street", "Số nhà + tên đường cụ thể", 6),
            ("alley_info", "Hẻm hay mặt tiền? Rộng bao nhiêu mét?", 3),
            ("house_floors", "Nhà mấy tầng?", 2),
        ]
    elif pt in APARTMENT_TYPES:
        return [
            ("building_name", "Tên dự án/tòa nhà", 4),
            ("unit_number", "Số căn (VD: A1502)", 2),
            ("floor_number", "Tầng số mấy?", 2),
            ("balcony_direction", "Hướng ban công", 2),
            ("view", "View (VD: biển, sông, thành phố)", 2),
            ("management_fee", "Phí quản lý (tr/tháng)", 2),
        ]
    else:
        # Unknown type — suggest all
        return [
            ("street", "Địa chỉ chi tiết", 6),
            ("building_name", "Tên tòa nhà/dự án", 4),
            ("alley_info", "Hẻm/mặt tiền + độ rộng", 3),
        ]


def _per_item_score(items, per_item, max_points):
    """Per-item scoring: +per_item each, capped at max_points."""
    lst = items if isinstance(items, list) else []
    # Count non-empty unique items
    unique = {str(a).strip().lower() for a in lst if str(a).strip()}
    return min(len(unique) * per_item, max_points)


def _amenity_score(amenities, max_points):
    """Amenity scoring: +AMENITY_POINT_PER_ITEM each, capped at max_points."""
    return _per_item_score(amenities, AMENITY_POINT_PER_ITEM, max_points)


def _highlight_score(highlights, max_points):
    """Highlight scoring: +HIGHLIGHT_POINT_PER_ITEM each, capped at max_points."""
    return _per_item_score(highlights, HIGHLIGHT_POINT_PER_ITEM, max_points)


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


def _field_score(p, field, ftype, weight, photo_count):
    """Return (points_earned, is_complete) for one field."""
    if field == "photos":
        ok = photo_count >= 3
        return (weight if ok else 0), ok
    if field == "amenities":
        pts = _amenity_score(p.get(field), weight)
        return pts, pts >= weight
    if field == "highlights":
        pts = _highlight_score(p.get(field), weight)
        return pts, pts >= weight
    if field == "description":
        ok = len(str(p.get(field) or "")) > 50
        return (weight if ok else 0), ok
    if ftype == "boolean":
        ok = p.get(field) is not None
        return (weight if ok else 0), ok
    ok = bool(p.get(field))
    return (weight if ok else 0), ok


def quality_score(parsed, photo_count=0):
    """0-100 score based on MASTER_SCHEMA weights. Returns (score, [missing labels])."""
    p = normalize_parsed(parsed)
    score = 0
    missing = []
    for field, (ftype, required, weight, label) in MASTER_SCHEMA.items():
        if weight == 0:
            continue
        pts, ok = _field_score(p, field, ftype, weight, photo_count)
        score += pts
        if not ok:
            if field in ("amenities", "highlights") and pts > 0:
                # Format: strip trailing .0 for clean display
                pts_str = f"{pts:g}"
                missing.append(f"{label} (+{pts_str}đ, thêm để đủ {weight}đ)")
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
        pts, ok = _field_score(p, field, ftype, weight, photo_count)
        score += pts
        if not ok:
            # remaining points achievable for this field
            missing.append((label, weight - pts))
    score = min(score, 100)
    potential = min(score + sum(w for _, w in missing), 100)
    return score, missing, potential
