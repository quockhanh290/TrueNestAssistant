"""Market price insights for share pages.

Honest stats computed from real tg_listings data — never fabricated.
Comparables: same district + same bedrooms, active statuses, all brokers
(anonymized aggregate). Fewer than MIN_COMPARABLES -> insufficient_data.
"""
import json

import db
import schema as master_schema

MIN_COMPARABLES = 5
ACTIVE_STATUSES = ("submitted", "uncertain")


def _pct(sorted_vals, q):
    """Linear-interpolation percentile (works for any n >= 1)."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def get_market_insight(parsed, exclude_id=None, path=None):
    """Price positioning vs comparable listings.

    Returns {"median","p25","p75","count","vs_median_pct","label"} or
    {"insufficient_data": True, ...} when comparables are too few or the
    listing lacks district/bedrooms/price.
    """
    p = master_schema.normalize_parsed(parsed or {})
    district = p.get("district")
    price = p.get("price_vnd")
    try:
        br = float(p.get("bedrooms"))
        price = float(price)
    except (TypeError, ValueError):
        br, price = None, None
    if not district or br is None or not price or price <= 0:
        return {"insufficient_data": True, "reason": "missing_fields"}

    conn = db.connect(path)
    try:
        rows = conn.execute(
            "SELECT id, parsed FROM tg_listings"
            " WHERE status IN ('submitted', 'uncertain')"
            " AND duplicate_of IS NULL"
        ).fetchall()
    finally:
        conn.close()

    prices = []
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        try:
            rp = master_schema.normalize_parsed(
                json.loads(r["parsed"] or "{}"))
        except (ValueError, TypeError):
            continue
        if rp.get("district") != district:
            continue
        try:
            rbr = float(rp.get("bedrooms"))
            rp_price = float(rp.get("price_vnd"))
        except (TypeError, ValueError):
            continue
        if rbr != br or rp_price <= 0:
            continue
        prices.append(rp_price)

    if len(prices) < MIN_COMPARABLES:
        return {"insufficient_data": True, "reason": "too_few",
                "count": len(prices)}

    prices.sort()
    median = _pct(prices, 0.5)
    p25 = _pct(prices, 0.25)
    p75 = _pct(prices, 0.75)
    vs_pct = (price - median) / median * 100

    if vs_pct < -15:
        label = "Rất tốt"
    elif vs_pct < -5:
        label = "Tốt"
    elif vs_pct <= 5:
        label = "Hợp lý"
    elif vs_pct <= 15:
        label = "Cao"
    else:
        label = "Rất cao"

    return {
        "median": median,
        "p25": p25,
        "p75": p75,
        "count": len(prices),
        "vs_median_pct": round(vs_pct, 1),
        "label": label,
    }


def insight_badge_text(insight):
    """Short Vietnamese line for the share-page badge, e.g.
    'thấp hơn 12% so với trung bình khu vực'."""
    if insight.get("insufficient_data"):
        return None
    pct = abs(insight["vs_median_pct"])
    direction = "thấp hơn" if insight["vs_median_pct"] < 0 else "cao hơn"
    if pct < 0.5:
        return "ngang giá trung bình khu vực"
    return f"{direction} {pct:.0f}% so với trung bình khu vực"
