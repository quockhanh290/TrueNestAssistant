"""Midday summary — standalone script (run ~12h).

Per broker, prints this morning's activity and what's left this
afternoon. Sending via the bot is wired separately.

Usage: python midday_summary.py [--dry-run]
"""
import argparse
import datetime
import json
import time

import db

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))
NOON_HOUR = 12


def _broker_name(b):
    return b.get("display_name") or b.get("username") or "anh"


def _bounds():
    now_vn = datetime.datetime.now(VN_TZ)
    midnight = datetime.datetime.combine(now_vn.date(), datetime.time.min,
                                         VN_TZ)
    noon = midnight + datetime.timedelta(hours=NOON_HOUR)
    end = midnight + datetime.timedelta(days=1)
    return (int(midnight.timestamp()), int(noon.timestamp()),
            int(end.timestamp()), now_vn)


def _first_feedback(v):
    raw = (v.get("feedback") or "").strip()
    if not raw:
        return None
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            for lid in v.get("listing_ids") or []:
                if d.get(lid):
                    return d[lid]
            vals = [x for x in d.values() if x]
            return vals[0] if vals else None
    except (ValueError, TypeError):
        return raw
    return None


def summarize_broker(b, midnight, noon, day_end):
    uid = b["user_id"]
    name = _broker_name(b)
    print(f"--- to user_id={uid} ({name}) ---")
    print("🍱 Nghỉ trưa thôi anh!\n")
    # ---- this morning
    n_new = db.count_listings_created(uid, midnight, noon)
    morning_viewings = db.viewings_between(uid, midnight, noon)
    n_clients = len({v.get("client_id") or v.get("client_name")
                     for v in morning_viewings})
    n_units = sum(len(v.get("listing_ids") or []) for v in morning_viewings)
    print("✅ Sáng nay:")
    print(f"• Đăng {n_new} tin mới")
    if morning_viewings:
        print(f"• Dẫn {n_clients} khách xem {n_units} căn")
        for v in morning_viewings:
            fb = _first_feedback(v)
            if fb:
                cname = v.get("client_name") or "khách"
                print(f'  💬 Feedback ({cname}): "{fb}"')
    else:
        print("• Chưa dẫn khách xem căn nào")
    # ---- this afternoon
    afternoon = db.viewings_between(uid, noon, day_end)
    stale = db.stale_clients(uid, days=3, limit=10)
    print("\n⏳ Chiều còn:")
    if afternoon:
        for v in afternoon:
            d = datetime.datetime.fromtimestamp(v["scheduled_at"], VN_TZ)
            cname = v.get("client_name") or "khách"
            print(f"• {d.strftime('%Hh')}: dẫn {cname} xem"
                  f" {len(v.get('listing_ids') or [])} căn")
    else:
        print("• Không còn lịch xem nào")
    if stale:
        print(f"• {len(stale)} khách cần gọi")
    if not afternoon and not stale:
        print("• Chiều rảnh — nghỉ ngơi nhé 😊")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print only (default behavior; sending is separate)")
    ap.parse_args()
    db.init_db()
    midnight, noon, day_end, _ = _bounds()
    brokers = db.list_brokers()
    if not brokers:
        print("No brokers.")
        return
    for b in brokers:
        summarize_broker(b, midnight, noon, day_end)
        print()


if __name__ == "__main__":
    main()
