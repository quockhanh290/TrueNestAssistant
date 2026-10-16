"""Da Nang location catalog: wards, streets, buildings, neighborhoods.

Source: data/danang_locations.json (post-merger catalog, effective 2025-07-01).
- 94 commune-level admin units (23 wards, 70 communes, 1 special zone)
- 3682 streets, 2237 alleys, 210 neighborhoods, 952 projects/buildings
- 26 legacy district names kept for search compatibility

Loaded once at startup; all search is accent-insensitive.
"""
import json
import os
import re
import unicodedata

_CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "danang_locations.json")

_DATA = None


def _norm(s):
    nfkd = unicodedata.normalize("NFD", s or "")
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


def _strip_road_prefix(norm_name):
    """Remove leading duong/street markers for cleaner matching."""
    return re.sub(r"^(duong|street|st)\s+", "", norm_name).strip()


def _is_junk_name(name):
    """Filter OSM artifacts: purely numeric or <3 chars."""
    n = (name or "").strip()
    if len(n) < 3:
        return True
    return not re.search(r"[a-zA-ZÀ-ỹ]", n)


def _load():
    global _DATA
    if _DATA is not None:
        return _DATA
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    admin_units = raw.get("admin_units", [])
    wards = [u for u in admin_units if u.get("type") == "ward"]
    communes = [u for u in admin_units
                if u.get("type") in ("commune", "special_zone")]

    # name -> entry indexes
    ward_by_norm = {}
    for u in admin_units:
        ward_by_norm[_norm(u["name"])] = u

    legacy = [d["name"] for d in raw.get("legacy_districts", [])]
    legacy_by_norm = {_norm(n): n for n in legacy}

    # streets: keep name + norm keys for search
    streets = []
    street_by_norm = {}
    for s in raw.get("streets", []):
        name = s.get("name", "").strip()
        if not name:
            continue
        key = _strip_road_prefix(_norm(name))
        entry = {"name": name, "_key": key}
        streets.append(entry)
        # first wins on key collision (prefer shorter/cleaner names)
        if key and key not in street_by_norm:
            street_by_norm[key] = name

    # buildings: filter junk, keep name + norm key
    buildings = []
    for p in raw.get("projects_buildings", []):
        name = (p.get("name") or "").strip()
        if _is_junk_name(name):
            continue
        aliases = [a for a in p.get("aliases", []) if a and a != name]
        keys = [_norm(name)] + [_norm(a) for a in aliases]
        buildings.append({"name": name, "_keys": [k for k in keys if k]})

    neighborhoods = []
    for n in raw.get("neighborhoods", []):
        name = (n.get("name") or "").strip()
        if _is_junk_name(name):
            continue
        neighborhoods.append({"name": name, "_key": _norm(name)})

    # alleys kept for text search only (not button UI)
    alleys = []
    for a in raw.get("alleys", []):
        name = (a.get("name") or "").strip()
        if _is_junk_name(name):
            continue
        alleys.append({"name": name, "_key": _norm(name)})

    _DATA = {
        "wards": wards,
        "communes": communes,
        "admin_units": admin_units,
        "ward_by_norm": ward_by_norm,
        "legacy_districts": legacy,
        "legacy_by_norm": legacy_by_norm,
        "streets": streets,
        "street_by_norm": street_by_norm,
        "buildings": buildings,
        "neighborhoods": neighborhoods,
        "alleys": alleys,
    }
    return _DATA


def reload():
    global _DATA
    _DATA = None
    return _load()


# ------------------------------------------------------------------ wards

def get_wards():
    """The 23 urban wards (for button UI)."""
    return _load()["wards"]


def get_communes():
    """The 70 communes + Hoang Sa special zone."""
    return _load()["communes"]


def search_wards(query, limit=5):
    """Search all 94 admin units + legacy district names.

    Legacy names map to themselves (for brokers thinking in old districts);
    callers can display them as-is for backward compatibility.
    """
    q = _norm(query).strip()
    if not q:
        return []
    d = _load()
    scored = []
    seen = set()
    # admin units
    for u in d["admin_units"]:
        key = _norm(u["name"])
        if key.startswith(q):
            s = 3
        elif q in key:
            s = 2
        else:
            tokens = q.split()
            s = 1 if (tokens and all(t in key for t in tokens)) else -1
        if s >= 0 and key not in seen:
            seen.add(key)
            # wards rank above communes on ties
            bonus = 0.5 if u.get("type") == "ward" else 0
            scored.append((s + bonus, u["name"],
                           {"name": u["name"], "type": u.get("type")}))
    # legacy district names (search compatibility)
    for norm_name, disp_name in d["legacy_by_norm"].items():
        if norm_name in seen:
            continue
        if norm_name.startswith(q):
            s = 2.5  # slightly below exact ward match
        elif q in norm_name:
            s = 1.5
        else:
            continue
        seen.add(norm_name)
        scored.append((s, disp_name,
                       {"name": disp_name, "type": "legacy_district"}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [e for _, _, e in scored[:limit]]


def find_ward(text):
    """Best ward/legacy match inside free text, or None."""
    t = _norm(text)
    if not t:
        return None
    d = _load()
    best, best_len = None, 0
    for norm_name, u in d["ward_by_norm"].items():
        if len(norm_name) > best_len and norm_name in t:
            # word-boundary guard for short names
            if len(norm_name) <= 4:
                pat = r"(?<![a-z0-9])" + re.escape(norm_name) + r"(?![a-z0-9])"
                if not re.search(pat, t):
                    continue
            best, best_len = u["name"], len(norm_name)
    if best:
        return best
    for norm_name, disp_name in d["legacy_by_norm"].items():
        if len(norm_name) > best_len and norm_name in t:
            best, best_len = disp_name, len(norm_name)
    return best


# ----------------------------------------------------------------- streets

def _score_key(key, q):
    if key.startswith(q):
        return 3
    if q in key:
        return 2
    tokens = q.split()
    if tokens and all(tok in key for tok in tokens):
        return 1
    return -1


def search_streets(query, limit=5):
    """Top-N street matches for a partial query (accent-insensitive)."""
    q = _strip_road_prefix(_norm(query).strip())
    if len(q) < 2:
        return []
    scored = []
    seen = set()
    for s in _load()["streets"]:
        sc = _score_key(s["_key"], q)
        if sc >= 0 and s["_key"] not in seen:
            seen.add(s["_key"])
            scored.append((sc, s["name"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:limit]]


def find_street_in_text(text):
    """Find a real catalog street name mentioned in free text.

    Extracts candidate phrases (1-4 capitalized words) and checks them
    against the street index. Returns the display name or None.
    """
    t = text or ""
    if not t:
        return None
    d = _load()
    # candidate phrases: sequences of capitalized words (VN or ASCII)
    words = re.findall(r"[A-ZÀ-Ỹ][a-zà-ỹ]*|\d+", t)
    cands = set()
    for n in (4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i + n])
            if len(phrase) >= 2:
                cands.add(_strip_road_prefix(_norm(phrase)))
    # longest first for most-specific match
    for c in sorted(cands, key=len, reverse=True):
        if c in d["street_by_norm"]:
            return d["street_by_norm"][c]
    return None


def search_alleys(query, limit=5):
    """Text search over alleys (not for button UI)."""
    q = _norm(query).strip()
    if len(q) < 2:
        return []
    scored = []
    seen = set()
    for a in _load()["alleys"]:
        sc = _score_key(a["_key"], q)
        if sc >= 0 and a["_key"] not in seen:
            seen.add(a["_key"])
            scored.append((sc, a["name"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:limit]]


def search_neighborhoods(query, limit=5):
    q = _norm(query).strip()
    if len(q) < 2:
        return []
    scored = []
    seen = set()
    for n in _load()["neighborhoods"]:
        sc = _score_key(n["_key"], q)
        if sc >= 0 and n["_key"] not in seen:
            seen.add(n["_key"])
            scored.append((sc, n["name"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:limit]]


# --------------------------------------------------------------- buildings

def catalog_buildings():
    """The 952 catalog buildings (junk-filtered) for merging."""
    return _load()["buildings"]


def stats():
    d = _load()
    return {
        "wards": len(d["wards"]),
        "communes": len(d["communes"]),
        "streets": len(d["streets"]),
        "alleys": len(d["alleys"]),
        "neighborhoods": len(d["neighborhoods"]),
        "buildings": len(d["buildings"]),
        "legacy_districts": len(d["legacy_districts"]),
    }
