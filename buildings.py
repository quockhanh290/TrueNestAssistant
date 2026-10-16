"""Da Nang building catalog: load, find, fuzzy search, add.

Source: data/building_catalog.json (curated by Khanh).
Matching is accent-insensitive (NFD normalize) and covers aliases.
"""
import json
import os
import re
import unicodedata

_CATALOG = None
_CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "building_catalog.json")


def _norm(s):
    nfkd = unicodedata.normalize("NFD", s or "")
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").lower()


def load_catalog():
    """Load (and cache) the building list. Each entry gets _keys for matching."""
    global _CATALOG
    if _CATALOG is None:
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("buildings", [])
        for b in entries:
            keys = [_norm(b.get("name", ""))]
            keys += [_norm(a) for a in b.get("aliases", []) if a]
            keys = [k for k in keys if k]
            keys.sort(key=len, reverse=True)  # most specific first
            b["_keys"] = keys
            # word-boundary patterns: "ori garden" must not match "hiyori garden"
            b["_patterns"] = [
                (re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"),
                 len(k))
                for k in keys
            ]
        _CATALOG = entries
    return _CATALOG


def reload_catalog():
    global _CATALOG
    _CATALOG = None
    return load_catalog()


def find_building(text):
    """Return the catalog entry whose name/alias appears in text.

    Word-boundary matching ("ori garden" won't match "hiyori garden");
    picks the most specific (longest) key match across all entries.
    Returns None when nothing matches.
    """
    t = _norm(text)
    if not t:
        return None
    best, best_len = None, 0
    for b in load_catalog():
        for pat, klen in b.get("_patterns", []):
            if klen > best_len and pat.search(t):
                best, best_len = b, klen
    return best


def search_buildings(query, limit=5):
    """Fuzzy search: top-N entries matching a partial query.

    Scoring: 3 = name/key starts with query, 2 = query is a substring
    of a key, 1 = all query tokens appear in a key (any order).
    """
    q = _norm(query).strip()
    if not q:
        return []
    scored = []
    for b in load_catalog():
        best_score = -1
        for k in b.get("_keys", []):
            if not k:
                continue
            if k.startswith(q):
                s = 3
            elif q in k:
                s = 2
            else:
                tokens = q.split()
                s = 1 if (tokens and all(tok in k for tok in tokens)) else -1
            if s > best_score:
                best_score = s
        if best_score >= 0:
            scored.append((best_score, b.get("name", ""), b))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [b for _, _, b in scored[:limit]]


def buildings_in_district(district_name, area_hint=""):
    """Catalog entries for a district (accent-insensitive), optionally
    ranked by area-keyword overlap for the guided landmark step."""
    dn = _norm(district_name)
    area_words = [w for w in _norm(area_hint).split() if len(w) > 2]
    scored = []
    for b in load_catalog():
        if _norm(b.get("district", "")) != dn:
            continue
        hay = " ".join(b.get("_keys", []))
        score = sum(1 for w in area_words if w in hay)
        scored.append((score, b.get("name", ""), b))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [b for _, _, b in scored]


def add_building(name):
    """Append a broker-added building to the catalog JSON (atomic write).

    Entry shape: {"name": ..., "aliases": [], "added_by": "broker"}.
    Returns the new (or existing, if already known) entry.
    """
    name = (name or "").strip()
    if not name:
        return None
    existing = find_building(name)
    if existing and _norm(existing.get("name", "")) == _norm(name):
        return existing
    entry = {"name": name, "aliases": [], "added_by": "broker"}
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("buildings", []).append(entry)
    tmp = _CATALOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CATALOG_PATH)
    reload_catalog()
    # return the cached entry (with _keys) for convenience
    return find_building(name) or entry
