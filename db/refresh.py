"""Refresh log, velocity, false-refresh reputation."""
from .core import connect, _now, _migrate_refresh_log, _migrate_refresh_reputation
import time



def log_refresh_claim(listing_id, broker_id, claimed_status, path=None,
                      velocity_flag=False):
    """Record a refresh claim. claimed_status: 'available' | 'rented'."""
    conn = connect(path)
    _migrate_refresh_log(conn)
    conn.execute(
        "INSERT INTO listing_refresh_log"
        " (listing_id, broker_id, claimed_status, velocity_flag, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (listing_id, broker_id, claimed_status,
         1 if velocity_flag else 0, _now()),
    )
    conn.commit()
    conn.close()


VELOCITY_WINDOW_MIN = 10


VELOCITY_THRESHOLD = 5


def count_recent_refreshes(broker_id, window_min=VELOCITY_WINDOW_MIN,
                           path=None):
    """Count refresh claims by broker in the last window_min minutes."""
    conn = connect(path)
    _migrate_refresh_log(conn)
    cutoff = _now() - window_min * 60
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM listing_refresh_log"
        " WHERE broker_id = ? AND created_at >= ?",
        (broker_id, cutoff),
    ).fetchone()
    conn.close()
    return row["c"] if row else 0


def check_refresh_velocity(broker_id, path=None):
    """True if broker's refresh rate looks suspicious (bot should warn)."""
    return count_recent_refreshes(broker_id, path=path) >= VELOCITY_THRESHOLD


FALSE_REFRESH_PENALTY = 10


FALSE_REFRESH_BAN_COUNT = 3


FALSE_REFRESH_BAN_DAYS = 7


def flag_false_refresh(listing_id, path=None):
    """Penalize a broker whose refresh claim proved false.

    Called when a listing marked "available" via refresh is later found to
    be rented (dedup, client feedback, admin check). Returns a dict with
    the penalty details, or None if the listing/broker is unknown.
    """
    import time
    conn = connect(path)
    _migrate_refresh_reputation(conn)
    row = conn.execute(
        "SELECT broker_id FROM tg_listings WHERE id = ?", (listing_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    broker_id = row["broker_id"]
    conn.execute(
        "UPDATE brokers SET false_refresh_reports = false_refresh_reports + 1"
        " WHERE user_id = ?",
        (broker_id,),
    )
    brow = conn.execute(
        "SELECT false_refresh_reports FROM brokers WHERE user_id = ?",
        (broker_id,),
    ).fetchone()
    count = (brow["false_refresh_reports"] or 0) if brow else 1
    banned_until = None
    if count >= FALSE_REFRESH_BAN_COUNT:
        banned_until = time.time() + FALSE_REFRESH_BAN_DAYS * 86400
        conn.execute(
            "UPDATE brokers SET refresh_cooldown_until = ? WHERE user_id = ?",
            (banned_until, broker_id),
        )
    conn.commit()
    conn.close()
    return {
        "broker_id": broker_id,
        "false_count": count,
        "penalty_points": FALSE_REFRESH_PENALTY,
        "banned_until": banned_until,
    }


def get_refresh_cooldown(broker_id, path=None):
    """Timestamp until which broker cannot propose, or None."""
    import time
    conn = connect(path)
    _migrate_refresh_reputation(conn)
    row = conn.execute(
        "SELECT refresh_cooldown_until FROM brokers WHERE user_id = ?",
        (broker_id,),
    ).fetchone()
    conn.close()
    if not row or not row["refresh_cooldown_until"]:
        return None
    if row["refresh_cooldown_until"] < time.time():
        return None
    return row["refresh_cooldown_until"]
