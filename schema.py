"""Canonical master schema and listing-quality score for TrueNest."""

# Field metadata: (type, required, weight, Vietnamese label).
# v5 has a 75-point common block and a 25-point property-type block.
QUALITY_TOTAL = 100

COMMON_SCHEMA = {
    "price_vnd":          ("number",  True,  8, "Giá thuê"),
    "photos":             ("array",   True,  7, "Ảnh (tối thiểu 3)"),
    "bedrooms":           ("number",  False, 7, "Số phòng ngủ"),
    "area_m2":            ("number",  False, 6, "Diện tích (nhà/căn hộ)"),
    "district":           ("string",  False, 6, "Khu vực"),
    "ward":               ("string",  False, 3, "Phường"),
    "available_from":     ("string",  False, 5, "Ngày trống"),
    "property_type":      ("string",  False, 4, "Loại hình"),
    "bathrooms":          ("number",  False, 4, "Số WC"),
    "primary_phone":      ("string",  True,  4, "SĐT liên hệ"),
    "furnishing":         ("string",  False, 3, "Nội thất"),
    "pet_friendly":       ("boolean", False, 2, "Chính sách pet"),
    "min_lease_months":   ("number",  False, 2, "Hợp đồng tối thiểu"),
    # The approved table combines these as "Giá điện nước" (2 points).
    "electricity_price":  ("scalar",  False, 1, "Giá điện"),
    "water_price":        ("scalar",  False, 1, "Giá nước"),
    "deposit_months":     ("number",  False, 2, "Đặt cọc (tháng)"),
    "description":        ("string",  False, 2, "Mô tả chi tiết"),
    "amenities":          ("array",   False, 5, "Tiện ích"),
    "highlights":         ("array",   False, 3, "Điểm nổi bật"),
}

TYPE_DETAIL_SCHEMAS = {
    "apartment": {
        "building_name":      ("string", False, 7, "Tên tòa nhà/dự án"),
        "unit_number":        ("string", False, 4, "Số căn (VD: A1502)"),
        "floor_number":       ("number", False, 4, "Số tầng"),
        "management_fee":     ("number", False, 4, "Phí quản lý"),
        "balcony_direction":  ("string", False, 3, "Hướng ban công"),
        "view":               ("string", False, 3, "View"),
    },
    "house": {
        "street":       ("string", False, 10, "Số nhà + tên đường"),
        "alley_info":   ("string", False, 9, "Hẻm/mặt tiền + độ rộng"),
        "house_floors": ("number", False, 6, "Số tầng của nhà"),
    },
}

# Canonical values emitted by the parser/bot.  Balcony direction had no writer
# before v5; stable English compass codes are used for the new plain-value API.
PROPERTY_TYPES = frozenset({"studio", "apartment", "house", "villa", "room"})
FURNISHING_VALUES = frozenset({"full", "basic", "empty"})
BALCONY_DIRECTIONS = frozenset({
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
})

HOUSE_TYPES = {"house", "villa"}
APARTMENT_TYPES = {"apartment", "studio"}

# All canonical fields, used by DB type/value validation. Detail fields keep
# their v5 type-specific weight here; scoring never sums MASTER_SCHEMA itself.
MASTER_SCHEMA = dict(COMMON_SCHEMA)
for _detail_schema in TYPE_DETAIL_SCHEMAS.values():
    MASTER_SCHEMA.update(_detail_schema)

AMENITY_POINT_PER_ITEM = 0.5
HIGHLIGHT_POINT_PER_ITEM = 0.5


def get_detail_fields_for_type(property_type):
    """Return (field, label, weight) tuples for the selected property type."""
    schema = _detail_schema_for_type(property_type)
    return [(field, meta[3], meta[2]) for field, meta in schema.items()]


def _detail_schema_for_type(property_type):
    pt = str(property_type or "").lower().strip()
    if pt in HOUSE_TYPES:
        return TYPE_DETAIL_SCHEMAS["house"]
    if pt in APARTMENT_TYPES:
        return TYPE_DETAIL_SCHEMAS["apartment"]
    return {}


def _per_item_score(items, per_item, max_points):
    lst = items if isinstance(items, list) else []
    unique = {str(a).strip().lower() for a in lst if str(a).strip()}
    return min(len(unique) * per_item, max_points)


FIELD_ALIASES = {
    "furnished": "furnishing",
    "deposit": "deposit_months",
}


def normalize_parsed(parsed):
    """Map legacy keys to canonical schema keys without dropping unknown data."""
    out = {}
    for key, value in (parsed or {}).items():
        out[FIELD_ALIASES.get(key, key)] = value
    return out


def _passes_value_check(field, value):
    """Use the same value gate as DB writes when awarding quality points."""
    if value is None or value == "":
        return False
    try:
        from db.listings import _check_parsed_value
        checked = _check_parsed_value(field, value)
    except (ValueError, TypeError):
        return False
    if checked is None or checked == "":
        return False
    if isinstance(checked, str) and checked.strip().lower() == "x":
        return False
    if field == "street":
        # The house block explicitly requires both a house number and street.
        import re
        text = str(checked).strip()
        return bool(re.search(r"\d", text) and re.search(r"[^\W\d_]", text))
    return True


def _field_score(p, field, ftype, weight, photo_count):
    if field == "photos":
        ok = photo_count >= 3
        return (weight if ok else 0), ok
    if field == "amenities":
        pts = _per_item_score(p.get(field), AMENITY_POINT_PER_ITEM, weight)
        return pts, pts >= weight
    if field == "highlights":
        pts = _per_item_score(p.get(field), HIGHLIGHT_POINT_PER_ITEM, weight)
        return pts, pts >= weight
    if field == "description":
        ok = len(str(p.get(field) or "")) > 50
        return (weight if ok else 0), ok
    ok = _passes_value_check(field, p.get(field))
    return (weight if ok else 0), ok


def _score_rows(parsed):
    yield from COMMON_SCHEMA.items()
    yield from _detail_schema_for_type(parsed.get("property_type")).items()


def quality_score(parsed, photo_count=0):
    """Return the v5 score and missing labels (common 75 + type block 25)."""
    p = normalize_parsed(parsed)
    score = 0
    missing = []
    for field, (ftype, required, weight, label) in _score_rows(p):
        pts, ok = _field_score(p, field, ftype, weight, photo_count)
        score += pts
        if not ok:
            if field in ("amenities", "highlights") and pts > 0:
                missing.append(
                    f"{label} (+{pts:g}đ, thêm để đủ {weight}đ)")
            else:
                missing.append(label)
    return min(score, QUALITY_TOTAL), missing


def quality_breakdown(parsed, photo_count=0):
    """Return score, remaining points by label, and achievable potential."""
    p = normalize_parsed(parsed)
    score = 0
    missing = []
    for field, (ftype, required, weight, label) in _score_rows(p):
        pts, ok = _field_score(p, field, ftype, weight, photo_count)
        score += pts
        if not ok:
            missing.append((label, weight - pts))
    score = min(score, QUALITY_TOTAL)
    potential = min(score + sum(weight for _, weight in missing), QUALITY_TOTAL)
    return score, missing, potential
