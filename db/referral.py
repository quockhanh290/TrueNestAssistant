"""Broker referral/invite system.

Khanh 2026-10-16: 3 successful invites = 1 month Pro free (max 3 months
stacked). Each invitee must create 5 quality listings (AI score >= 50,
has photos, active >= 7 days). Anti-fraud: Telegram user_id uniqueness,
phone normalization, behavioral flags, photo dhash comparison.
"""
import re

import schema
from .core import _migrate_referrals, connect, _now
from .listings import _hamming_hex, list_broker_listings


REFERRAL_REQUIRED = 3          # qualified invitees needed for one reward
REFERRAL_QUALIFY_LISTINGS = 5  # quality listings each invitee must create
REFERRAL_QUALIFY_SCORE = 50    # minimum AI quality score per listing
REFERRAL_QUALIFY_AGE_DAYS = 7  # listing must be active this long
REFERRAL_MAX_STACK = 3         # max reward months stacked
REFERRAL_REWARD_DAYS = 30      # days of Pro per reward
REFERRAL_PHOTO_DUP_THRESHOLD = 3  # similar photos -> fraud
REFERRAL_DHASH_MAX_DISTANCE = 5   # same as find_photos_by_hash default

# statuses that count as an "active" listing for qualification
_ACTIVE_STATUSES = ("submitted",)


def _norm_phone(raw):
    """Normalize one phone candidate to 0xxxxxxxxx, or '' if invalid."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"0\d{9}", digits) else ""


def _phones_in_text(text):
    """Extract normalized VN mobile numbers from free text."""
    out = []
    for m in re.finditer(r"(?:\+?84|0)(?:[\s.\-]*\d){9}", text or ""):
        p = _norm_phone(m.group(0))
        if p and p not in out:
            out.append(p)
    return out


def broker_phones(broker_id, path=None):
    """All normalized phones tied to a broker: profile + listing texts."""
    from .brokers import get_broker
    phones = set()
    b = get_broker(broker_id, path=path) or {}
    p = _norm_phone(b.get("phone") or "")
    if p:
        phones.add(p)
    for lst in list_broker_listings(broker_id, limit=10000, offset=0,
                                    path=path):
        for ph in _phones_in_text(lst.get("raw_text") or ""):
            phones.add(ph)
    return phones


def create_referral(inviter_id, invitee_id, path=None):
    """Record a referral when a new broker joins via an invite link.

    Returns the referral row dict, or None if invalid (self-referral,
    invitee already counted, inviter unknown). Idempotent.
    """
    from .brokers import get_broker
    if inviter_id == invitee_id:
        return None
    if not get_broker(inviter_id, path=path):
        return None
    now = _now()
    conn = connect(path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO referrals (inviter_id, invitee_id,"
            " created_at) VALUES (?, ?, ?)",
            (inviter_id, invitee_id, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM referrals WHERE invitee_id = ?",
            (invitee_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_referral_by_invitee(invitee_id, path=None):
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM referrals WHERE invitee_id = ?",
            (invitee_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_referrals_by_inviter(inviter_id, path=None):
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM referrals WHERE inviter_id = ?"
            " ORDER BY created_at ASC",
            (inviter_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_referral_progress(broker_id, path=None):
    """{invited, qualified, needed} for the /moi progress display."""
    refs = get_referrals_by_inviter(broker_id, path=path)
    qualified = sum(1 for r in refs
                    if r.get("qualified_at") and not r.get("fraud_flag"))
    return {
        "invited": len(refs),
        "qualified": qualified,
        "needed": REFERRAL_REQUIRED,
    }


def _qualifying_listings(broker_id, path=None):
    """Listings that count toward referral qualification."""
    now = _now()
    min_age = REFERRAL_QUALIFY_AGE_DAYS * 86400
    out = []
    for lst in list_broker_listings(broker_id, limit=10000, offset=0,
                                    path=path):
        if lst.get("status") not in _ACTIVE_STATUSES:
            continue
        if now - (lst.get("created_at") or 0) < min_age:
            continue
        photos = (lst.get("photo_urls") or []) + \
                 (lst.get("photo_file_ids") or [])
        if not photos:
            continue
        score, _ = schema.quality_score(lst.get("parsed") or {},
                                        photo_count=len(photos))
        if score < REFERRAL_QUALIFY_SCORE:
            continue
        out.append(lst)
    return out


def check_invitee_qualified(invitee_id, path=None):
    """True if the invitee has enough quality listings.

    Returns (qualified: bool, qualifying_count: int).
    """
    n = len(_qualifying_listings(invitee_id, path=path))
    return n >= REFERRAL_QUALIFY_LISTINGS, n


def mark_qualified(invitee_id, path=None):
    """Stamp qualified_at on the invitee's referral row. Returns row or None."""
    conn = connect(path)
    try:
        cur = conn.execute(
            "UPDATE referrals SET qualified_at = ?"
            " WHERE invitee_id = ? AND qualified_at IS NULL",
            (_now(), invitee_id),
        )
        conn.commit()
        if not cur.rowcount:
            return get_referral_by_invitee(invitee_id, path=path)
        return get_referral_by_invitee(invitee_id, path=path)
    finally:
        conn.close()


def flag_fraud(referral_id, reason, path=None):
    """Mark a referral as fraudulent. Returns True if a row was updated."""
    conn = connect(path)
    try:
        cur = conn.execute(
            "UPDATE referrals SET fraud_flag = 1, fraud_reason = ?"
            " WHERE id = ?",
            (reason, referral_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def check_phone_duplicate(invitee_id, inviter_id, path=None):
    """True if invitee shares any phone number with the inviter.

    On match, flags the referral row with reason 'duplicate_phone'.
    """
    invitee_phones = broker_phones(invitee_id, path=path)
    if not invitee_phones:
        return False
    overlap = invitee_phones & broker_phones(inviter_id, path=path)
    if overlap:
        ref = get_referral_by_invitee(invitee_id, path=path)
        if ref:
            flag_fraud(ref["id"], "duplicate_phone", path=path)
        return True
    return False


def _all_photo_hashes(broker_id, path=None):
    """All perceptual hashes across a broker's listings.

    Returns [(listing_id, dhash, phash)] — either hash may be None.
    """
    out = []
    for lst in list_broker_listings(broker_id, limit=10000, offset=0,
                                    path=path):
        dhashes = lst.get("photo_hashes") or {}
        phashes = lst.get("photo_phashes") or {}
        for url in set(dhashes) | set(phashes):
            out.append((lst.get("id"), dhashes.get(url), phashes.get(url)))
    return out


def check_photo_duplicate(invitee_id, inviter_id, path=None):
    """True if >= threshold of the invitee's photos match inviter's.

    Uses dHash OR pHash Hamming distance (same threshold as dedup).
    Either hash firing counts as a photo match. On match, flags the
    referral row with reason 'duplicate_photos'.
    Returns (is_duplicate: bool, match_count: int).
    """
    invitee_hashes = _all_photo_hashes(invitee_id, path=path)
    if not invitee_hashes:
        return False, 0
    inviter_hashes = [(h, p) for _, h, p in _all_photo_hashes(
        inviter_id, path=path)]
    if not inviter_hashes:
        return False, 0
    matched_photos = 0
    for _, h, p in invitee_hashes:
        for ih, ip in inviter_hashes:
            hit = False
            if h and ih and _hamming_hex(h, ih) <= REFERRAL_DHASH_MAX_DISTANCE:
                hit = True
            if p and ip and _hamming_hex(p, ip) <= REFERRAL_DHASH_MAX_DISTANCE:
                hit = True
            if hit:
                matched_photos += 1
                break
    is_dup = matched_photos >= REFERRAL_PHOTO_DUP_THRESHOLD
    if is_dup:
        ref = get_referral_by_invitee(invitee_id, path=path)
        if ref:
            flag_fraud(ref["id"],
                       f"duplicate_photos:{matched_photos}", path=path)
    return is_dup, matched_photos


def check_behavior_pattern(invitee_id, path=None):
    """Heuristic: exactly the minimum listings, all within 24h of signup.

    Returns a warning string for admin review, or None if nothing odd.
    Never auto-flags — human decides.
    """
    from .brokers import get_broker
    b = get_broker(invitee_id, path=path) or {}
    created = b.get("created_at") or 0
    if not created:
        return None
    day1 = [l for l in list_broker_listings(invitee_id, limit=10000,
                                            offset=0, path=path)
            if (l.get("created_at") or 0) - created < 86400]
    total = len(list_broker_listings(invitee_id, limit=10000, offset=0,
                                     path=path))
    if total == REFERRAL_QUALIFY_LISTINGS and len(day1) == total:
        return (f"suspicious: {total} listings all created within 24h"
                f" of signup (invitee {invitee_id})")
    return None


def run_fraud_checks(invitee_id, path=None):
    """Run all fraud checks for an invitee's referral.

    Returns {"ok": bool, "reasons": [str], "warnings": [str]}.
    Phone/photo duplicates auto-flag the referral; behavior patterns
    only produce warnings for admin review.
    """
    ref = get_referral_by_invitee(invitee_id, path=path)
    if not ref:
        return {"ok": False, "reasons": ["no_referral"],
                "warnings": []}
    reasons, warnings = [], []
    if check_phone_duplicate(invitee_id, ref["inviter_id"], path=path):
        reasons.append("duplicate_phone")
    dup, n = check_photo_duplicate(invitee_id, ref["inviter_id"], path=path)
    if dup:
        reasons.append(f"duplicate_photos:{n}")
    w = check_behavior_pattern(invitee_id, path=path)
    if w:
        warnings.append(w)
    return {"ok": not reasons, "reasons": reasons, "warnings": warnings}


def active_referral_months(broker_id, path=None):
    """Months of referral-granted Pro still active."""
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM referral_rewards"
            " WHERE broker_id = ? AND expires_at > ?",
            (broker_id, _now()),
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


def grant_referral_reward(broker_id, path=None):
    """Grant 1 month of Pro for reaching 3 qualified invitees.

    Extends an existing pro/max tier instead of downgrading it.
    Caps total stacked referral time at REFERRAL_MAX_STACK months.
    Returns expires_at timestamp, or None if already at cap.
    """
    from .brokers import get_broker, set_tier, update_broker
    if active_referral_months(broker_id, path=path) >= REFERRAL_MAX_STACK:
        return None
    now = _now()
    b = get_broker(broker_id, path=path) or {}
    exp = b.get("tier_expires_at")
    if exp and exp > now and (b.get("tier") or "free") in ("pro", "max"):
        new_exp = min(exp + REFERRAL_REWARD_DAYS * 86400,
                      now + REFERRAL_MAX_STACK * REFERRAL_REWARD_DAYS * 86400)
        update_broker(broker_id, path=path, tier_expires_at=new_exp)
    else:
        set_tier(broker_id, "pro", days=REFERRAL_REWARD_DAYS, path=path)
        new_exp = now + REFERRAL_REWARD_DAYS * 86400
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO referral_rewards (broker_id, months, granted_at,"
            " expires_at, reason) VALUES (?, 1, ?, ?, 'referral_3_invites')",
            (broker_id, now, new_exp),
        )
        conn.commit()
    finally:
        conn.close()
    return new_exp


def maybe_grant_inviter_reward(inviter_id, path=None):
    """Grant reward if inviter reached the threshold and isn't at cap.

    Returns expires_at on grant, "capped" if at stack cap, None otherwise.
    """
    prog = get_referral_progress(inviter_id, path=path)
    if prog["qualified"] < REFERRAL_REQUIRED:
        return None
    # avoid double-granting for the same milestone: one reward per
    # completed group of REFERRAL_REQUIRED qualified invitees
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM referral_rewards WHERE broker_id = ?",
            (inviter_id,),
        ).fetchone()
        granted = row["c"] if row else 0
    finally:
        conn.close()
    if granted >= prog["qualified"] // REFERRAL_REQUIRED:
        return None
    exp = grant_referral_reward(inviter_id, path=path)
    return exp if exp else "capped"
