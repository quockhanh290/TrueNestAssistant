"""Trial usage / upsell gating."""
from .core import connect, _now
from .brokers import tier_allows



TRIAL_LIMITS = {
    "xbroker_match": 3,   # match liên broker (feat_premium: broadcast -> max)
    "send2client": 3,     # gửi tin cho khách (feat_premium: send2client -> pro)
}


TRIAL_TIER = {
    "xbroker_match": "max",
    "send2client": "pro",
}


TRIAL_FEATURES = tuple(TRIAL_LIMITS)


def get_trial_usage(broker_id, feature, path=None):
    """Number of trial uses consumed for a feature (0 if never used)."""
    if feature not in TRIAL_LIMITS:
        raise ValueError(f"unknown trial feature: {feature}")
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT used_count FROM trial_usage"
            " WHERE broker_id = ? AND feature = ?",
            (broker_id, feature),
        ).fetchone()
        return row["used_count"] if row else 0
    finally:
        conn.close()


def increment_trial_usage(broker_id, feature, path=None):
    """Record one trial use; returns the new used count."""
    if feature not in TRIAL_LIMITS:
        raise ValueError(f"unknown trial feature: {feature}")
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO trial_usage (broker_id, feature, used_count, updated_at)"
            " VALUES (?, ?, 1, ?)"
            " ON CONFLICT(broker_id, feature) DO UPDATE SET"
            " used_count = used_count + 1, updated_at = excluded.updated_at",
            (broker_id, feature, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT used_count FROM trial_usage"
            " WHERE broker_id = ? AND feature = ?",
            (broker_id, feature),
        ).fetchone()
        return row["used_count"]
    finally:
        conn.close()


def consume_trial(broker_id, feature, path=None):
    """Use one trial if one is left: (ok, used_after).

    One conditional UPDATE (`... WHERE used_count < limit`) decides, so N
    parallel calls can never consume more than the limit. The old
    check_trial-then-increment pair let 12 parallel taps use 12 of 3.
    The tier check stays with the caller (tier-covered = no consumption).
    """
    if feature not in TRIAL_LIMITS:
        raise ValueError(f"unknown trial feature: {feature}")
    limit = TRIAL_LIMITS[feature]
    now = _now()
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO trial_usage (broker_id, feature, used_count, updated_at)"
            " VALUES (?, ?, 0, ?) ON CONFLICT(broker_id, feature) DO NOTHING",
            (broker_id, feature, now),
        )
        cur = conn.execute(
            "UPDATE trial_usage SET used_count = used_count + 1, updated_at = ?"
            " WHERE broker_id = ? AND feature = ? AND used_count < ?",
            (now, broker_id, feature, limit),
        )
        ok = cur.rowcount == 1
        used = conn.execute(
            "SELECT used_count FROM trial_usage"
            " WHERE broker_id = ? AND feature = ?",
            (broker_id, feature),
        ).fetchone()["used_count"]
        conn.commit()
        return ok, used
    finally:
        conn.close()


def refund_trial(broker_id, feature, path=None):
    """Give one consumed trial back (the paid action failed after
    consume_trial). Never goes below 0."""
    conn = connect(path)
    try:
        conn.execute(
            "UPDATE trial_usage SET used_count = used_count - 1, updated_at = ?"
            " WHERE broker_id = ? AND feature = ? AND used_count > 0",
            (_now(), broker_id, feature),
        )
        conn.commit()
    finally:
        conn.close()


def check_trial(broker_id, feature, path=None):
    """(allowed, remaining) for a trial-gated feature.

    - Broker whose tier already includes the feature -> (True, -1) = unlimited.
    - Uses remaining -> (True, limit - used).
    - Exhausted -> (False, 0).
    """
    if feature not in TRIAL_LIMITS:
        raise ValueError(f"unknown trial feature: {feature}")
    if tier_allows(broker_id, TRIAL_TIER[feature], path=path):
        return True, -1
    used = get_trial_usage(broker_id, feature, path=path)
    limit = TRIAL_LIMITS[feature]
    if used < limit:
        return True, limit - used
    return False, 0
