"""Spam strikes / muting."""
from .core import connect, _now
import time



STRIKE_DECAY_DAYS = 30


SPAM_EVENT_WINDOW = 3600  # 1 hour window for "3x" counting


_SPAM_MESSAGES = {
    "banned": (
        "🚫 Tài khoản của anh đã bị khóa do vi phạm nhiều lần.\n"
        "Anh liên hệ admin để được hỗ trợ nhé."
    ),
    "muted": (
        "🔇 Anh đang bị tạm khóa đến {until}.\n"
        "Hết giờ anh gửi lại bình thường nhé."
    ),
}


def get_spam_status(broker_id, path=None):
    """Return spam state: {strikes, muted_until, banned, last_strike_at}."""
    conn = connect(path)
    row = conn.execute(
        "SELECT * FROM spam_strikes WHERE broker_id = ?", (broker_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"strikes": 0, "muted_until": 0, "banned": False,
                "last_strike_at": None}
    d = dict(row)
    d["banned"] = bool(d["banned"])
    return d


def is_muted_or_banned(broker_id, path=None):
    """Check if broker is currently muted or banned.

    Returns (blocked: bool, message: str). Message is "" when not blocked.
    """
    st = get_spam_status(broker_id, path=path)
    if st["banned"]:
        return True, _SPAM_MESSAGES["banned"]
    now = _now()
    if st["muted_until"] and st["muted_until"] > now:
        from .vntime import fmt as _vn_fmt
        until = _vn_fmt(st["muted_until"], "%H:%M %d/%m")
        return True, _SPAM_MESSAGES["muted"].format(until=until)
    return False, ""


def _apply_strike_decay(conn, broker_id, now):
    """Reset strikes to 0 if no violations in STRIKE_DECAY_DAYS. Returns strikes."""
    row = conn.execute(
        "SELECT strikes, last_strike_at FROM spam_strikes WHERE broker_id = ?",
        (broker_id,),
    ).fetchone()
    if not row:
        return 0
    strikes = row["strikes"]
    last = row["last_strike_at"]
    if strikes > 0 and last and (now - last) > STRIKE_DECAY_DAYS * 86400:
        conn.execute(
            "UPDATE spam_strikes SET strikes = 0, updated_at = ?"
            " WHERE broker_id = ?",
            (now, broker_id),
        )
        return 0
    return strikes


def record_spam_violation(broker_id, violation_type, path=None):
    """Record a strike-worthy violation. Returns action taken.

    violation_type: "rate_limit" | "spam_content" | "duplicate"
    Returns one of: "warn" (strike 1), "mute_1h" (strike 2),
                    "mute_24h" (strike 3), "ban" (strike 4+).
    Applies 30-day strike decay before incrementing.
    """
    now = _now()
    conn = connect(path)
    strikes = _apply_strike_decay(conn, broker_id, now)
    new_strikes = strikes + 1

    row = conn.execute(
        "SELECT broker_id FROM spam_strikes WHERE broker_id = ?",
        (broker_id,),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE spam_strikes SET strikes = ?, last_strike_at = ?,"
            " updated_at = ? WHERE broker_id = ?",
            (new_strikes, now, now, broker_id),
        )
    else:
        conn.execute(
            "INSERT INTO spam_strikes (broker_id, strikes, last_strike_at,"
            " muted_until, banned, created_at, updated_at)"
            " VALUES (?, ?, ?, 0, 0, ?, ?)",
            (broker_id, new_strikes, now, now, now),
        )

    if new_strikes == 1:
        action = "warn"
    elif new_strikes == 2:
        action = "mute_1h"
        conn.execute(
            "UPDATE spam_strikes SET muted_until = ? WHERE broker_id = ?",
            (now + 3600, broker_id),
        )
    elif new_strikes == 3:
        action = "mute_24h"
        conn.execute(
            "UPDATE spam_strikes SET muted_until = ? WHERE broker_id = ?",
            (now + 86400, broker_id),
        )
    else:
        action = "ban"
        conn.execute(
            "UPDATE spam_strikes SET banned = 1, muted_until = 0"
            " WHERE broker_id = ?",
            (broker_id,),
        )
    conn.commit()
    conn.close()
    # Log the violation event for audit
    log_spam_event(broker_id, violation_type, path=path)
    return action


def log_spam_event(broker_id, event_type, path=None):
    """Log a spam-related event (for 3x-in-1h counting)."""
    conn = connect(path)
    conn.execute(
        "INSERT INTO spam_events (broker_id, event_type, created_at)"
        " VALUES (?, ?, ?)",
        (broker_id, event_type, _now()),
    )
    conn.commit()
    conn.close()


def count_recent_spam_events(broker_id, event_type, hours=1, path=None):
    """How many events of this type in the last N hours."""
    conn = connect(path)
    n = conn.execute(
        "SELECT COUNT(*) c FROM spam_events"
        " WHERE broker_id = ? AND event_type = ? AND created_at > ?",
        (broker_id, event_type, _now() - hours * 3600),
    ).fetchone()["c"]
    conn.close()
    return n


def maybe_strike_for_repeated_event(broker_id, event_type, threshold=3,
                                    path=None):
    """Log event; if count in last hour hits threshold, record a strike.

    Returns the strike action ("warn"/"mute_1h"/"mute_24h"/"ban") or None
    if the threshold was not reached.
    """
    log_spam_event(broker_id, event_type, path=path)
    n = count_recent_spam_events(broker_id, event_type, hours=1, path=path)
    if n >= threshold:
        return record_spam_violation(broker_id, event_type, path=path)
    return None


def prune_old_spam_events(days=7, path=None):
    """Delete spam_events older than `days` — housekeeping."""
    conn = connect(path)
    cur = conn.execute(
        "DELETE FROM spam_events WHERE created_at < ?",
        (_now() - days * 86400,),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def count_recent_identical_texts(broker_id, text, hours=1, path=None):
    """How many listings with (normalized) identical raw_text in last N hours.

    Used for duplicate-text spam detection.
    """
    import re
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    if len(norm) < 20:
        return 0  # too short to be meaningful
    conn = connect(path)
    rows = conn.execute(
        "SELECT raw_text FROM tg_listings"
        " WHERE broker_id = ? AND created_at > ?",
        (broker_id, _now() - hours * 3600),
    ).fetchall()
    conn.close()
    n = 0
    for r in rows:
        other = re.sub(r"\s+", " ", (r["raw_text"] or "").strip().lower())
        if other == norm:
            n += 1
    return n


def spam_violation_message(action, violation_type, detail=""):
    """Vietnamese user-facing message for a strike action.

    action: "warn" | "mute_1h" | "mute_24h" | "ban"
    violation_type: "rate_limit" | "spam_content" | "duplicate"
    detail: violation-specific detail
      - rate_limit: "Gói Free tối đa 10 tin/giờ, anh đã gửi 12 tin"
      - spam_content: truncated snippet of the rejected text
      - duplicate: unused (fixed message)
    Every message states the specific reason — never generic.
    """
    reason = _VIOLATION_REASONS.get(violation_type, "vi phạm quy định")
    if action == "warn":
        if violation_type == "rate_limit":
            return (
                "⚠️ Cảnh báo 1/3: Anh gửi quá nhanh!\n"
                f"{detail}.\n"
                "Chậm lại nhé, tái phạm em sẽ tạm khóa 1 giờ ạ."
            )
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return (
                "⚠️ Cảnh báo 1/3: Tin vừa rồi không phải tin cho thuê!\n"
                f'("{snippet}...")\n'
                "Anh chỉ gửi tin cho thuê nhà giúp em nhé.\n"
                "Tái phạm em sẽ tạm khóa 1 giờ ạ."
            )
        # duplicate
        return (
            "⚠️ Cảnh báo 1/3: Anh gửi tin này 3 lần rồi!\n"
            "Em đã bỏ qua các bản trùng. Đừng gửi lặp lại nhé.\n"
            "Tái phạm em sẽ tạm khóa 1 giờ ạ."
        )
    if action == "mute_1h":
        head = f"🔇 Tạm khóa 1 giờ (cảnh báo 2/3): {reason}!"
        if violation_type == "rate_limit":
            return f"{head}\n{detail}.\nHết giờ anh gửi lại bình thường nhé."
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return f'{head}\n("{snippet}...")\nHết giờ anh gửi lại bình thường nhé.'
        return f"{head}\nHết giờ anh gửi lại bình thường nhé."
    if action == "mute_24h":
        head = f"🔇 Tạm khóa 24 giờ (cảnh báo 3/3): {reason}!"
        if violation_type == "rate_limit":
            return (f"{head}\n{detail}.\n"
                    "Đây là cảnh báo cuối cùng ạ.")
        if violation_type == "spam_content":
            snippet = (detail or "")[:60]
            return (f'{head}\n("{snippet}...")\n'
                    "Đây là cảnh báo cuối cùng ạ.")
        return f"{head}\nĐây là cảnh báo cuối cùng ạ."
    # ban
    return (
        f"🚫 Tài khoản của anh đã bị khóa vĩnh viễn (vi phạm: {reason}).\n"
        "Anh liên hệ admin để được hỗ trợ nhé."
    )


_VIOLATION_REASONS = {
    "rate_limit": "gửi tin quá nhanh",
    "spam_content": "gửi tin không phải cho thuê",
    "duplicate": "gửi tin trùng lặp",
}
