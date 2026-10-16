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
