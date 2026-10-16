"""Regex-based Vietnamese rental listing parser (MVP).

Extracts structured fields from free-form broker posts.
Returns: {field: value} plus per-field confidence and missing critical fields.
"""
import re

# ---------------------------------------------------------------- constants

DISTRICTS = [
    "Sơn Trà", "Hải Châu", "Ngũ Hành Sơn", "Liên Chiểu", "Cẩm Lệ", "Thanh Khê",
    "Hòa Vang",
]
# common short forms brokers use
DISTRICT_ALIASES = {
    "son tra": "Sơn Trà",
    "hai chau": "Hải Châu",
    "ngu hanh son": "Ngũ Hành Sơn",
    "lien chieu": "Liên Chiểu",
    "cam le": "Cẩm Lệ",
    "thanh khe": "Thanh Khê",
    "hoa vang": "Hòa Vang",
}

BUILDINGS = [
    "Monarchy", "Mường Thanh", "Muong Thanh", "Hiyori", "Novotel",
    "Altara", "A La Carte", "Fusion Suites", "Shantira", "Wyndham",
    "Risemount", "Nalod", "Golden Square", "Indochina Riverside",
    "Sunrise", "Azura", "Premier", "Diamond Sea", "Movenpick",
    "Four Points", "Hilton", "Vinpearl", "Sun Peninsula",
]

PROPERTY_TYPES = {
    "studio": "studio",
    "căn hộ": "apartment", "can ho": "apartment", "chung cư": "apartment",
    "chung cu": "apartment", "apartment": "apartment",
    "nhà": "house", "nha": "house", "nhà phố": "house", "nha pho": "house",
    "villa": "villa", "biệt thự": "villa", "biet thu": "villa",
    "phòng trọ": "room", "phong tro": "room", "phòng": "room",
}

CRITICAL = ["price_vnd", "primary_phone", "photos"]


# ---------------------------------------------------------------- helpers

def _norm(text):
    return text.lower()


def parse_price(text):
    """12tr, 12 triệu, 12,000,000, 12.000.000, $500 -> VND float."""
    t = _norm(text)
    # "12tr" / "12 tr" / "12triệu" / "12 triệu"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|trieuj|mil)", t)
    if m:
        return float(m.group(1).replace(",", ".")) * 1_000_000, "high"
    # "$500" / "500$" / "500 usd"
    m = re.search(r"\$\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:usd|\$)", t)
    if m:
        val = float((m.group(1) or m.group(2)).replace(",", "."))
        return val * 25_000, "medium"  # rough USD->VND
    # "12,000,000" / "12.000.000" / "12000000" near price keywords
    m = re.search(r"(?:giá|gia|price)\s*[:\-]?\s*(\d[\d.,]{5,})", t)
    if m:
        return float(m.group(1).replace(",", "").replace(".", "")), "medium"
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})+)\s*(?:đ|vnd|/tháng|/thang)?", t)
    if m:
        return float(m.group(1).replace(",", "").replace(".", "")), "medium"
    return None, None


def parse_phone(text):
    """Vietnamese mobile: 09xx, 08x, 07x, 03x, 05x — tolerates dots/spaces."""
    t = re.sub(r"[.\s\-]", "", text)
    m = re.search(r"(0(?:3|5|7|8|9)\d{8})", t)
    if m:
        return m.group(1), "high"
    # +84 variant
    m = re.search(r"\+84\s*(\d{9})", text)
    if m:
        return "0" + m.group(1), "medium"
    return None, None


def parse_bedrooms(text):
    t = _norm(text)
    if re.search(r"\bstudio\b", t):
        return 0.0, "high"
    m = re.search(r"(\d+)\s*(?:pn|phòng ngủ|phong ngu|bed)", t)
    if m:
        return float(m.group(1)), "high"
    return None, None


def parse_bathrooms(text):
    t = _norm(text)
    m = re.search(r"(\d+)\s*(?:wc|toilet|nhà vệ sinh|nha ve sinh|bath)", t)
    if m:
        return float(m.group(1)), "high"
    return None, None


def parse_area(text):
    t = _norm(text)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m2", t)
    if m:
        return float(m.group(1).replace(",", ".")), "high"
    return None, None


def parse_district(text):
    t = _norm(text)
    for d in DISTRICTS:
        if d.lower() in t:
            return d, "high"
    for alias, canon in DISTRICT_ALIASES.items():
        if alias in t:
            return canon, "medium"
    return None, None


def parse_building(text):
    t = _norm(text)
    for b in BUILDINGS:
        if b.lower() in t:
            # canonicalise Muong Thanh spelling
            if b.lower() in ("muong thanh",):
                return "Mường Thanh", "high"
            return b, "high"
    return None, None


def parse_floor_unit(text):
    t = _norm(text)
    floor, unit = None, None
    m = re.search(r"tầng\s*(\d+)", t)
    if m:
        floor = int(m.group(1))
    # unit codes like B12.04, P308, 401, A-12-05
    m = re.search(r"\b([A-Z]?\d{1,2}[.\-]\d{2,4})\b", text.upper())
    if m:
        unit = m.group(1)
    else:
        m = re.search(r"(?:căn|can|phòng|phong)\s+([A-Z0-9.\-]{2,8})", text, re.I)
        if m and re.search(r"\d", m.group(1)):
            unit = m.group(1).upper()
    return floor, unit


def parse_property_type(text):
    t = _norm(text)
    for key, val in PROPERTY_TYPES.items():
        if key in t:
            return val, "medium"
    return None, None


def parse_furnishing(text):
    t = _norm(text)
    if re.search(r"full\s*(?:nội thất|noi that|nt)", t):
        return "full", "high"
    if re.search(r"nội thất cơ bản|noi that co ban", t):
        return "basic", "medium"
    if re.search(r"nhà trống|nha trong|trống|không nội thất", t):
        return "empty", "medium"
    return None, None


def parse_pet(text):
    t = _norm(text)
    if re.search(r"(?:cho\s*)?(?:nuôi\s*)?pet|thú cưng|thu cung", t):
        if re.search(r"không\s*(?:cho\s*)?(?:nuôi\s*)?pet|cấm pet", t):
            return False, "high"
        return True, "medium"
    return None, None


def parse_deposit_lease(text):
    t = _norm(text)
    out = {}
    m = re.search(r"cọc\s*(\d+)", t)
    if m:
        out["deposit_months"] = (int(m.group(1)), "high")
    m = re.search(r"(?:hđ|hợp đồng|hop dong)\s*(\d+)\s*(?:-\s*(\d+))?\s*tháng", t)
    if m:
        out["min_lease_months"] = (int(m.group(1)), "medium")
    return out


# ---------------------------------------------------------------- main

def parse_listing(text, photo_count=0):
    """Parse a broker post. Returns dict:
    {
      "fields": {name: value},
      "confidence": {name: "high"/"medium"/"low"},
      "missing": [critical field names still missing],
    }
    """
    fields, conf = {}, {}

    def set_field(name, value, confidence):
        if value is not None:
            fields[name] = value
            conf[name] = confidence

    price, c = parse_price(text)
    set_field("price_vnd", price, c)

    phone, c = parse_phone(text)
    set_field("primary_phone", phone, c)

    br, c = parse_bedrooms(text)
    set_field("bedrooms", br, c)

    ba, c = parse_bathrooms(text)
    set_field("bathrooms", ba, c)

    area, c = parse_area(text)
    set_field("area_m2", area, c)

    dist, c = parse_district(text)
    set_field("district", dist, c)

    bld, c = parse_building(text)
    set_field("building_name", bld, c)

    floor, unit = parse_floor_unit(text)
    set_field("floor_number", floor, "high" if floor else None)
    set_field("unit_number", unit, "medium" if unit else None)

    ptype, c = parse_property_type(text)
    set_field("property_type", ptype, c)

    furn, c = parse_furnishing(text)
    set_field("furnishing", furn, c)

    pet, c = parse_pet(text)
    if pet is not None:
        fields["pet_friendly"] = pet
        conf["pet_friendly"] = c

    for k, (v, c) in parse_deposit_lease(text).items():
        set_field(k, v, c)

    if photo_count:
        fields["photo_count"] = photo_count
        conf["photo_count"] = "high"

    missing = []
    if "price_vnd" not in fields:
        missing.append("price_vnd")
    if "primary_phone" not in fields:
        missing.append("primary_phone")
    if photo_count < 1:
        missing.append("photos")

    return {"fields": fields, "confidence": conf, "missing": missing}


def reflective_summary(parsed):
    """Build the natural 'reflective listening' summary in Vietnamese."""
    f = parsed["fields"]
    parts = []

    # what kind of place
    br = f.get("bedrooms")
    ptype = f.get("property_type", "căn")
    if br == 0.0:
        place = "căn studio"
    elif br:
        place = f"căn {int(br)}PN"
    elif ptype == "house":
        place = "căn nhà"
    elif ptype == "villa":
        place = "căn villa"
    else:
        place = "căn này"

    bld = f.get("building_name")
    dist = f.get("district")
    loc = ""
    if bld:
        loc = f" ở {bld}"
    elif dist:
        loc = f" ở {dist}"

    floor = f.get("floor_number")
    if floor:
        loc += f", tầng {floor}"

    price = f.get("price_vnd")
    price_str = ""
    if price:
        if price >= 1_000_000:
            price_str = f", {price / 1_000_000:g}tr/tháng"

    furn = f.get("furnishing")
    furn_str = {"full": ", full nội thất", "basic": "",
                "empty": ""}.get(furn, "")

    parts.append(f"À em thấy đây là {place}{loc}{price_str}{furn_str}")

    # one soft confirm for a medium-confidence field
    pet = f.get("pet_friendly")
    if pet and parsed["confidence"].get("pet_friendly") == "medium":
        parts.append("Có vẻ như cho nuôi pet nữa đúng không anh? 🏠")
    else:
        parts.append("đúng không anh? 🏠")

    return " ".join(parts)


if __name__ == "__main__":
    samples = [
        "CHO THUÊ MONARCHY B12.04 1PN 12TR FULL NT tầng 12, cho nuôi pet. LH 0905123456",
        "Cho thuê căn hộ 2PN 75m2 ở Sơn Trà, giá 15 triệu/tháng, cọc 1. Zalo 0796.646.636",
        "Nhà 3 tầng Hải Châu cho thuê",
    ]
    for s in samples:
        r = parse_listing(s, photo_count=5)
        print("IN :", s)
        print("OUT:", r["fields"])
        print("MISS:", r["missing"])
        print("SAY:", reflective_summary(r))
        print()
