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
    # "Rent: 18,500,000" / "rent 18500000" (English prefix)
    m = re.search(r"(?:rent|price)\s*[:\-]?\s*(\d[\d.,]{5,})", t)
    if m:
        return float(m.group(1).replace(",", "").replace(".", "")), "medium"
    # "12,000,000" / "12.000.000" / "12000000" near price keywords
    m = re.search(r"(?:giá|gia|price)\s*[:\-]?\s*(\d[\d.,]{5,})", t)
    if m:
        return float(m.group(1).replace(",", "").replace(".", "")), "medium"
    # "18,500,000 VND/month" / "18,500,000 VND" / "18.5M VND"
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})+)\s*(?:vnd|vnđ|đồng)?\s*(?:/month|/mo|/tháng|/thang)?", t)
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
    # +84 variant (tolerates spaces: "+84 905 123 456" or "+84905123456")
    m = re.search(r"\+?84[\s.\-]*((?:\d[\s.\-]*){9})(?!\d)", text)
    if m:
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 9:
            return "0" + digits, "medium"
    return None, None


def parse_telegram(text):
    """Extract Telegram username: "@haunii_apartment" -> "haunii_apartment"."""
    m = re.search(r"(?:telegram|tele)\s*[:\-]?\s*@?([a-zA-Z][a-zA-Z0-9_]{4,31})",
                  text, re.I)
    if m:
        return m.group(1), "medium"
    return None, None


def parse_bedrooms(text):
    t = _norm(text)
    if re.search(r"\bstudio\b", t):
        return 0.0, "high"
    # English: "2-bedroom", "2 bedroom", "2BR", "2 br", "2 bed", "2bd"
    m = re.search(r"(\d+)\s*[-]?\s*(?:bedrooms?|br\b|bed\b|bd\b)", t)
    if m:
        return float(m.group(1)), "high"
    m = re.search(r"(\d+)\s*(?:pn|phòng ngủ|phong ngu|bed)", t)
    if m:
        return float(m.group(1)), "high"
    return None, None


def parse_bathrooms(text):
    t = _norm(text)
    # English: "2-bathroom", "2 bathroom", "2BA", "2 bath"
    m = re.search(r"(\d+)\s*[-]?\s*(?:bathrooms?|ba\b|bath\b)", t)
    if m:
        return float(m.group(1)), "high"
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
    # English with "District" suffix: "Son Tra District", "Hai Chau District"
    for alias, canon in DISTRICT_ALIASES.items():
        if alias + " district" in t or alias + " dist" in t:
            return canon, "high"
    return None, None


def parse_street(text):
    """Extract street name from English/Vietnamese listings.

    Handles: "630 Vo Nguyen Giap St", "Vo Nguyen Giap Street",
    "đường Võ Nguyên Giáp", "630 Vo Nguyen Giap".
    Returns street name or None.
    """
    # "Location: 630 Vo Nguyen Giap St, Son Tra" or "Address: ..."
    m = re.search(
        r"(?:location|address|địa chỉ|dia chi)\s*:\s*"
        r"(?:\d+\s+)?([A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]+?)"
        r"(?:\s+(?:st|street|str|đường|duong))?",
        text, re.I)
    if m:
        street = m.group(1).strip().rstrip(",")
        # Don't return if it's just a number or too short
        if len(street) >= 4 and re.search(r"[a-zA-ZÀ-ỹ]", street):
            return street, "medium"
    # "630 Vo Nguyen Giap" pattern: number + capitalized words
    m = re.search(r"\b\d{1,4}\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text)
    if m:
        return m.group(1).strip(), "low"
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
    if re.search(r"full\s*(?:nội thất|noi that|nt|furnish)", t):
        return "full", "high"
    if re.search(r"nội thất cơ bản|noi that co ban|basic furnish", t):
        return "basic", "medium"
    if re.search(r"nhà trống|nha trong|trống|không nội thất|unfurnish", t):
        return "empty", "medium"
    return None, None


def parse_pet(text):
    t = _norm(text)
    if re.search(r"(?:cho\s*)?(?:nuôi\s*)?pet|thú cưng|thu cung", t):
        if re.search(r"không\s*(?:cho\s*)?(?:nuôi\s*)?pet|cấm pet", t):
            return False, "high"
        return True, "medium"
    return None, None


def parse_availability(text):
    """Extract availability from English/Vietnamese listings.

    "Available now", "available immediately" -> "available"
    "Available from [date]" -> "available_from_date" (raw string)
    """
    t = _norm(text)
    if re.search(r"available\s+(?:now|immediately|asap)", t):
        return "available", "high"
    if re.search(r"(?:còn trống|con trong|sẵn sàng|san sang)", t):
        return "available", "high"
    m = re.search(r"available\s+from\s+([a-z0-9\s,/\-]{3,20})", t)
    if m:
        return f"from {m.group(1).strip()}", "medium"
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


# ---------------------------------------------------------------- highlights

import unicodedata as _uc


def _strip_accents(text):
    """Remove Vietnamese diacritics for robust matching (biển -> bien)."""
    nfkd = _uc.normalize("NFD", text)
    stripped = "".join(c for c in nfkd if not _uc.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D")


# (regex on accent-stripped lowercase text, display label) — ordered
# most-specific first within each group. Label may contain {0} for the
# first capture group (e.g. minutes).
_HIGHLIGHT_PATTERNS = [
    # ---- views
    (r"view\s*bien\s*truc\s*dien|view\s*truc\s*dien\s*bien",
     "View biển trực diện"),
    (r"ban\s*cong\s*view\s*bien", "Ban công view biển"),
    (r"view\s*bien", "View biển"),
    (r"view\s*song", "View sông"),
    (r"view\s*thanh\s*pho|view\s*tp", "View thành phố"),
    (r"view\s*nui", "View núi"),
    # ---- proximity
    (r"(?:cach|gan)\s*bien\s*(\d+)\s*(?:phut|p)\b",
     "Cách biển {0} phút đi bộ"),
    (r"sat\s*bien", "Sát biển"),
    (r"mat\s*tien\s*bien", "Mặt tiền biển"),
    (r"gan\s*bien", "Gần biển"),
    (r"gan\s*cho", "Gần chợ"),
    (r"gan\s*truong", "Gần trường học"),
    (r"gan\s*san\s*bay", "Gần sân bay"),
    (r"gan\s*cau\s*rong", "Gần cầu Rồng"),
    (r"trung\s*tam", "Vị trí trung tâm"),
    # ---- amenities
    (r"ho\s*boi\s*vo\s*cuc", "Hồ bơi vô cực"),
    (r"ho\s*boi", "Hồ bơi"),
    (r"phong\s*gym|\bgym\b", "Phòng gym"),
    (r"\bspa\b", "Spa"),
    (r"san\s*tennis", "Sân tennis"),
    (r"\bb[bq]q\b|tiec\s*nuong", "Khu BBQ"),
    (r"cong\s*vien", "Gần công viên"),
    # ---- condition
    (r"moi\s*xay", "Mới xây"),
    (r"moi\s*renovate|vua\s*renovate|moi\s*sua", "Mới renovate"),
    (r"vua\s*son|moi\s*son", "Vừa sơn mới"),
    (r"noi\s*that\s*moi\s*100\s*%?", "Nội thất mới 100%"),
    (r"moi\s*100\s*%", "Mới 100%"),
    # ---- features
    (r"ban\s*cong\s*rong", "Ban công rộng"),
    (r"san\s*thuong", "Sân thượng"),
    (r"thang\s*may", "Có thang máy"),
    (r"cho\s*dau\s*(?:o\s*to|xe\s*hoi)", "Chỗ đậu ô tô"),
    (r"an\s*ninh\s*24\s*/\s*7|bao\s*ve\s*24\s*/\s*24", "An ninh 24/7"),
    # ---- vibe
    (r"yen\s*tinh", "Khu yên tĩnh"),
    (r"thoang\s*mat", "Thoáng mát"),
    (r"nhieu\s*cay\s*xanh", "Nhiều cây xanh"),
    (r"anh\s*sang\s*tu\s*nhien|nhieu\s*anh\s*sang",
     "Nhiều ánh sáng tự nhiên"),
    (r"thoang\s*dang", "Thoáng đãng"),
]


def parse_highlights(text):
    """Extract selling-point highlights from listing text.

    Returns a list of short display strings, ordered by appearance.
    Overlapping matches are deduped (keeps the longest).
    """
    t = _strip_accents(_norm(text))
    found = []  # (position, label)
    for pattern, label in _HIGHLIGHT_PATTERNS:
        for m in re.finditer(pattern, t):
            if "{0}" in label and m.groups():
                disp = label.format(m.group(1))
            else:
                disp = label
            found.append((m.start(), disp))
    found.sort(key=lambda x: x[0])
    labels = []
    for _, lab in found:
        if lab in labels:
            continue
        lab_low = lab.lower()
        # drop any existing label that is a substring of this longer one
        labels = [o for o in labels
                  if not (o != lab and o.lower() in lab_low)]
        # skip if this label is a substring of an existing longer one
        if any(lab != o and lab_low in o.lower() for o in labels):
            continue
        labels.append(lab)
    # "Cách biển X phút" supersedes plain "Gần biển"
    if any(l.startswith("Cách biển") for l in labels):
        labels = [l for l in labels if l != "Gần biển"]
    return labels


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

    tg, c = parse_telegram(text)
    set_field("telegram_username", tg, c)

    br, c = parse_bedrooms(text)
    set_field("bedrooms", br, c)

    ba, c = parse_bathrooms(text)
    set_field("bathrooms", ba, c)

    area, c = parse_area(text)
    set_field("area_m2", area, c)

    dist, c = parse_district(text)
    set_field("district", dist, c)

    street, c = parse_street(text)
    set_field("street", street, c)

    avail, c = parse_availability(text)
    set_field("availability_note", avail, c)

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

    hl = parse_highlights(text)
    if hl:
        fields["highlights"] = hl
        conf["highlights"] = "medium"

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
    """Build the natural 'reflective listening' summary in Vietnamese.

    Returns a fallback prompt when nothing was parsed (0 fields).
    """
    f = parsed["fields"]

    # empty parse: don't show a broken "À em thấy đây là căn này..."
    # exclude photo_count (photos alone aren't parsed content)
    content_fields = {k: v for k, v in f.items()
                      if k not in ("photo_count",)}
    if not content_fields:
        return ("Anh gửi thêm thông tin giúp em nhé? "
                "(giá, số phòng ngủ, địa chỉ...)")

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
    street = f.get("street")
    loc = ""
    if bld:
        loc = f" ở {bld}"
    elif street:
        loc = f" ở {street}"
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


# ---------------------------------------------------------------- query parsing

# keywords that signal "this is a search query, not a new listing"
QUERY_KEYWORDS = [
    "cho xem", "cho e xem", "xem tin", "tìm tin", "tim tin", "lọc tin",
    "loc tin", "tìm giúp", "tin nào", "còn tin", "kiếm tin",
]


def looks_like_query(text):
    """True if the message is a listing search, not a new listing submission."""
    t = _norm(text)
    return any(kw in t for kw in QUERY_KEYWORDS)


def parse_query(text):
    """Extract search filters from a natural-language broker query.

    Examples:
      "cho xem tin 2PN dưới 15tr" -> {"bedrooms": 2.0, "max_price": 15000000.0}
      "tin ở Sơn Trà"             -> {"district": "Sơn Trà"}
      "tin có pet"                -> {"pet_friendly": True}
      "tin còn trống"             -> {"status": "active"}
      "tin đã cho thuê"           -> {"status": "rented"}
    Returns {} if no filters detected.
    """
    t = _norm(text)
    f = {}

    # bedrooms
    if re.search(r"\bstudio\b", t):
        f["bedrooms"] = 0.0
    else:
        m = re.search(r"(\d+)\s*(?:pn|phòng ngủ|phong ngu)", t)
        if m:
            f["bedrooms"] = float(m.group(1))

    # price bounds: "dưới 15tr", "trên 10tr", "từ 8tr đến 12tr", "8-12tr"
    m = re.search(r"(?:dưới|duoi|dưới|dưới)\s*(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|mil)",
                  t)
    if m:
        f["max_price"] = float(m.group(1).replace(",", ".")) * 1_000_000
    m = re.search(r"(?:trên|tren|từ|tu)\s*(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|mil)", t)
    if m:
        f["min_price"] = float(m.group(1).replace(",", ".")) * 1_000_000
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|mil)",
                  t)
    if m:
        f["min_price"] = float(m.group(1).replace(",", ".")) * 1_000_000
        f["max_price"] = float(m.group(2).replace(",", ".")) * 1_000_000

    # district
    dist, _ = parse_district(text)
    if dist:
        f["district"] = dist

    # building
    bld, _ = parse_building(text)
    if bld:
        f["building_name"] = bld

    # pet
    if re.search(r"có pet|nuôi pet|pet friendly|cho pet", t):
        f["pet_friendly"] = True
    elif re.search(r"không pet|ko pet|cấm pet", t):
        f["pet_friendly"] = False

    # status
    if re.search(r"đã cho thuê|da cho thue|đã thuê", t):
        f["status"] = "rented"
    elif re.search(r"còn trống|con trong|đang trống|dang trong|còn tin", t):
        f["status"] = "active"

    # property type
    ptype, _ = parse_property_type(text)
    if ptype:
        f["property_type"] = ptype

    return f


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
    print("--- query parsing ---")
    for q in [
        "cho xem tin 2PN dưới 15tr",
        "tìm tin ở Sơn Trà có pet",
        "tin nào còn trống vậy em",
        "cho e xem tin đã cho thuê",
        "lọc tin monarchy từ 10tr đến 15tr",
    ]:
        print("Q  :", q)
        print("  ->", parse_query(q), "| is_query:", looks_like_query(q))
