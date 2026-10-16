"""Tier 2 normalization for TrueNest Assistant Telegram bot.

Runs BEFORE the regex parser (parser.py). Cleans raw broker text and
extracts hard anchors (phone, price, unit code, building) used by dedup.

Pipeline order:  Telegram message -> normalize_all() -> parser.parse_listing()

Pure Python stdlib only (unicodedata, re). No external dependencies.
"""
import re
import unicodedata

# ---------------------------------------------------------------- constants

USD_TO_VND = 25_500
MIN_PRICE_VND = 1_500_000
MAX_PRICE_VND = 150_000_000

# Blacklist for unit extraction: common false positives (case-insensitive)
UNIT_BLACKLIST_RES = [
    re.compile(r"^\d+pn$", re.I),      # 1pn, 2pn, 3pn ...
    re.compile(r"^\d+k$", re.I),       # 100k, 150k ...
    re.compile(r"^\d+m2$", re.I),      # 30m2, 75m2 ...
    re.compile(r"^\d{1,2}$"),         # 01, 02 ...
]

# Major Da Nang projects: (canonical name, [accent-stripped aliases])
BUILDINGS = [
    ("The Monarchy", ["monarchy"]),
    ("Mường Thanh", ["muong thanh", "muongthanh"]),
    ("Hiyori Garden Tower", ["hiyori"]),
    ("Wyndham Soleil", ["wyndham", "soleil"]),
    ("Danang Golden Bay", ["golden bay"]),
    ("FPT Plaza", ["fpt plaza", "fpt"]),
    ("The Ori Garden", ["ori garden"]),
    ("The Sang Residence", ["sang residence", "the sang"]),
    ("Altara Suites", ["altara"]),
    ("A La Carte", ["a la carte", "alacarte"]),
    ("Risemount", ["risemount", "risemount premier", "premier"]),
    ("Shantira", ["shantira", "shantira beach"]),
    ("Nalod", ["nalod"]),
    ("Golden Square", ["golden square"]),
    ("Indochina Riverside", ["indochina"]),
    ("Azura", ["azura"]),
    ("Vinpearl", ["vinpearl"]),
    ("Novotel", ["novotel"]),
    ("Four Points", ["four points"]),
    ("Diamond Sea", ["diamond sea"]),
    ("Movenpick", ["movenpick", "moevenpick"]),
    ("Fusion Suites", ["fusion suites", "fusion"]),
    ("Hilton", ["hilton"]),
    ("Sunrise", ["sunrise"]),
]

# Emoji ranges (to collapse excessive runs)
_EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0x2300, 0x23FF),
]

# Combining marks that are teencode decoration (underline, strikethrough...).
# Vietnamese tone marks (U+0300-U+031B, U+0323) are NOT in this set and are
# preserved so diacritics survive clean_text.
_JUNK_COMBINING = set(range(0x0332, 0x0339)) | set(range(0x20D0, 0x2100))


# ---------------------------------------------------------------- helpers

def _strip_accents(text):
    """Remove Vietnamese diacritics for alias matching (đ -> d handled)."""
    nfkd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D")


def _is_emoji(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


# ---------------------------------------------------------------- 1. clean_text

def clean_text(raw):
    """Normalize raw broker text.

    Steps: NFKD decompose -> strip ONLY teencode combining marks
    (U+0332 underline etc.; Vietnamese tone marks are preserved) ->
    NFKC recompose -> drop format chars (Cf) -> collapse excessive
    emoji runs (3+ -> 1) -> collapse whitespace.
    """
    if not raw:
        return ""
    # NFKD decomposes art fonts (𝐀 -> A), fullwidth (Ａ -> A),
    # and separates combining marks (O + U+0332)
    t = unicodedata.normalize("NFKD", raw)
    # strip only junk combining marks; keep Vietnamese diacritics
    t = "".join(
        c for c in t
        if not (unicodedata.combining(c) and ord(c) in _JUNK_COMBINING)
    )
    # back to composed form (ê, ộ ... recompose correctly)
    t = unicodedata.normalize("NFKC", t)
    # drop format chars (ZWJ, ZWNJ, variation selectors in Cf, etc.)
    t = "".join(c for c in t if unicodedata.category(c) != "Cf")
    # collapse excessive emoji runs: 3+ consecutive -> 1
    out, run = [], 0
    for ch in t:
        if _is_emoji(ch):
            run += 1
            if run == 1:
                out.append(ch)
            # 2nd+ emoji in a run of 3+ is dropped; runs of 1-2 kept
            elif run == 2:
                # keep 2nd only if run ends here; decided at run end
                out.append(ch)
        else:
            if run >= 3:
                # trim the kept 2 down to 1
                out.pop()
            run = 0
            out.append(ch)
    if run >= 3:
        out.pop()
    t = "".join(out)
    # collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---------------------------------------------------------------- 2. normalize_phone

def normalize_phone(text):
    """Extract Vietnamese mobile numbers, normalized to 0xxxxxxxxx.

    Handles: o/O between digits (O9O5 -> 0905), teencode spacing
    ("0 9 0 . 5 . . ."), +84 / 84 prefixes. Returns deduplicated list.
    Expects cleaned text but works on raw too.
    """
    if not text:
        return []
    # letter o/O adjacent to a digit is a disguised zero
    t = re.sub(r"(?<=\d)[oO]|[oO](?=\d)", "0", text)
    # candidate: leading 0 / +84 / 84, then 9 more digits with separators
    pat = re.compile(r"(?:\+?84|0)(?:[\s.\-–—_~*]*\d){9}")
    found = []
    for m in pat.finditer(t):
        digits = re.sub(r"\D", "", m.group(0))
        if digits.startswith("84") and len(digits) == 11:
            digits = "0" + digits[2:]
        elif digits.startswith("84") and len(digits) == 12:
            # +84 captured without plus: 84905123456 -> 11 digits
            digits = "0" + digits[2:]
        if re.fullmatch(r"0\d{9}", digits) and digits not in found:
            found.append(digits)
    return found


# ---------------------------------------------------------------- 3. normalize_price

def _parse_num(num_str):
    """Parse '12,000,000'/'12.000.000' -> 12000000 ; '12,5'/'14.5' -> 12.5."""
    n = num_str.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", n):
        return float(n.replace(",", "").replace(".", ""))
    return float(n.replace(",", "."))


def normalize_price(text):
    """Extract rental price, normalized to VND.

    Handles USD ($800 -> x25500), abbreviations (12tr, 14.5m, 12.5mils,
    12 triệu, 8tr5), full numbers (12,000,000 vnđ), ranges (6.5m-7m ->
    lower bound). Validates 1.5M <= price <= 150M.
    Returns {"price_vnd": float, "raw": str} or None.
    """
    if not text:
        return None
    t = text.lower()

    def ok(v, raw):
        if MIN_PRICE_VND <= v <= MAX_PRICE_VND:
            return {"price_vnd": float(v), "raw": raw.strip()}
        return None

    # 1. USD: "$800", "800 usd", "800$"
    m = re.search(r"\$\s*(\d[\d.,]*)|(\d[\d.,]*)\s*(?:usd|\$)", t)
    if m:
        num = m.group(1) or m.group(2)
        try:
            return ok(_parse_num(num) * USD_TO_VND, m.group(0))
        except ValueError:
            pass

    # 2. range "6.5m–7m" / "6.5-7tr": take lower bound
    m = re.search(
        r"(\d[\d.,]*)\s*(?:tr\b|triệu|trieu|mils?|m\b)\s*[–—\-~]\s*\d", t
    )
    if m:
        try:
            unit = re.search(r"(tr\b|triệu|trieu|mils?|m\b)",
                             m.group(0)).group(1)
            mult = 1_000_000  # tr / triệu / m / mil all mean million
            return ok(_parse_num(m.group(1)) * mult, m.group(0))
        except (ValueError, AttributeError):
            pass

    # 3. "XtrY" shorthand: "8tr5" -> 8.5M
    m = re.search(r"\b(\d+)\s*tr\s*(\d)\b", t)
    if m:
        try:
            return ok(float(f"{m.group(1)}.{m.group(2)}") * 1_000_000,
                      m.group(0))
        except ValueError:
            pass

    # 4. abbreviations: 12tr, 12 triệu, 14.5m, 12.5mils, 8.2 mil
    # bare "m" must not be "m2" (area) -> \b already excludes m+digit
    m = re.search(
        r"(\d[\d.,]*)\s*(tr\b|triệu|trieu|mils?|mil\b|m\b)", t
    )
    if m:
        try:
            return ok(_parse_num(m.group(1)) * 1_000_000, m.group(0))
        except ValueError:
            pass

    # 5. full number with currency: "12,000,000 vnđ", "12.000.000đ"
    m = re.search(
        r"(\d{1,3}(?:[.,]\d{3})+)\s*(?:vnđ|vnd|đồng|dong|đ\b)", t
    )
    if m:
        try:
            return ok(_parse_num(m.group(1)), m.group(0))
        except ValueError:
            pass

    return None


# ---------------------------------------------------------------- 4. extract_unit

def extract_unit(text):
    """Extract room/unit code: P302, B12.04, Căn 12A.

    Returns cleaned uppercase code or None. Blacklists false positives
    (1pn, 100k, 30m2, 01, ...).
    """
    if not text:
        return None

    def clean(code):
        code = code.strip().upper().rstrip(".,;:")
        for rx in UNIT_BLACKLIST_RES:
            if rx.match(code):
                return None
        return code or None

    # prefixed: "P.401", "P: 302", "căn 12A", "phòng B12.04", "mã căn A461"
    # NOTE: single "p" must not match inside "phong"/"phòng" (the VN word
    # for room), so it requires a non-letter right after it.
    m = re.search(
        r"\b(?:p(?![a-zA-Zà-ỹÀ-Ỹ])|phòng|phong|căn|can|unit|mã căn|ma can)"
        r"\s*[:.\-]?\s*"
        r"([A-Z0-9]{2,4}(?:\.\d{1,3})?[a-z]?)",
        text, re.I,
    )
    if m:
        code = clean(m.group(1))
        if code:
            # drop bare prefix-only matches like "P" + blacklist already out
            return code

    # standalone letter+digits: "B12.04", "A461", "C699"
    m = re.search(r"\b([A-Z]\d{2,4}(?:\.\d{1,3})?[A-Z]?)\b", text)
    if m:
        return clean(m.group(1))

    return None


# ---------------------------------------------------------------- 5. extract_building

def extract_building(text):
    """Match building/project against Da Nang master list.

    Also matches mini-building patterns ("Tòa K32", "Tòa 601").
    Returns canonical name or None.
    """
    if not text:
        return None
    flat = _strip_accents(text).lower()

    for canonical, aliases in BUILDINGS:
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", flat):
                return canonical

    # mini-building: "Tòa K32", "Tòa 601", "toà k250/2"
    # (flat is accent-stripped, so match "toa" without diacritic)
    m = re.search(r"\btoa\s*(k?\s*\d+(?:[/.]\d+)?)", flat)
    if m:
        code = re.sub(r"\s+", "", m.group(1)).upper()
        return f"Tòa {code}"

    return None


# ---------------------------------------------------------------- 6. normalize_all

def normalize_all(raw_text):
    """Run full Tier 2 normalization. Returns dict with clean text and
    hard anchors (phones, price, unit, building) for the parser/dedup."""
    clean = clean_text(raw_text)
    return {
        "clean_text": clean,
        "phones": normalize_phone(clean),
        "price": normalize_price(clean),
        "unit": extract_unit(clean),
        "building": extract_building(clean),
    }


# ---------------------------------------------------------------- self-test

if __name__ == "__main__":
    samples = [
        # 1. teencode: combining underline U+0332 on phone digits
        "CHO THUÊ CĂN HỘ MONARCHY B12.04 TẦNG 12 1PN FULL NỘI THẤT "
        "GIÁ 12TR/THÁNG 🏠🏠🏠🏠 LH O̲9̲0̲5̲.1̲2̲3̲.4̲5̲6̲",
        # 2. USD price, expat-style English post
        "For rent apartment near My Khe beach, 2BR full furniture, "
        "$800/month, available now. Contact +84 905 123 456",
        # 3. mini building + unit code + tr-shorthand price
        "Cho thuê tòa K32 Tô Hiến Thành, phòng P302, 2PN 75m2 "
        "giá 8tr5, cọc 1. lh 0 7 9 6 . 6 4 6 . 6 3 6",
    ]
    for s in samples:
        r = normalize_all(s)
        print("IN :", s[:80] + ("..." if len(s) > 80 else ""))
        print("  clean :", r["clean_text"][:90])
        print("  phones:", r["phones"])
        print("  price :", r["price"])
        print("  unit  :", r["unit"])
        print("  bldg  :", r["building"])
        print()
    print("normalize.py self-test OK")
