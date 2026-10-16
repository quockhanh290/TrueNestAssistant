"""Morning brief — standalone script (run ~8h).

Per broker, prints today's agenda: viewings, stale clients, old
listings, plus yesterday's deferred checklist items.

Sending via the bot is wired separately.

Usage: python morning_brief.py [--dry-run]
"""
import argparse
import datetime

import db

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))


def _broker_name(b):
    return b.get("display_name") or b.get("username") or "anh"


def _short_loc(lid):
    l = db.get_listing(lid)
    if not l:
        return "?"
    p = l.get("parsed") or {}
    return p.get("building_name") or p.get("street") or p.get("district") or "?"


def _day_bounds():
    now_vn = datetime.datetime.now(VN_TZ)
    start = datetime.datetime.combine(now_vn.date(), datetime.time.min, VN_TZ)
    return int(start.timestamp()), int((start + datetime.timedelta(days=1)).timestamp())


def brief_broker(b, day_start, day_end):
    uid = b["user_id"]
    name = _broker_name(b)
    # purge checklist items older than 2 days, then read
    db.clear_old_checklist(days=2)
    deferred = db.list_checklist(uid)
    viewings = db.viewings_between(uid, day_start, day_end)
    stale = db.stale_clients(uid, days=3, limit=10)
    old_listings = db.stale_listings(older_than_days=14,
                                     statuses=("submitted",))
    # scope stale_listings to this broker
    old_listings = [l for l in old_listings if l.get("broker_id") == uid]

    print(f"--- to user_id={uid} ({name}) ---")
    print("☀️ Chào buổi sáng anh!\n")
    print("📅 Hôm nay:")
    if viewings:
        for v in viewings:
            d = datetime.datetime.fromtimestamp(v["scheduled_at"], VN_TZ)
            cname = v.get("client_name") or "khách"
            lids = v.get("listing_ids") or []
            locs = ", ".join(_short_loc(lid) for lid in lids[:3])
            print(f"• {d.strftime('%Hh')}: Dẫn {cname} xem {len(lids)} căn"
                  + (f" ({locs})" if locs else ""))
    else:
        print("• Chưa có lịch xem nào")
    if stale:
        oldest_days = []
        for c in stale:
            base = c.get("last_contact_at") or c.get("created_at") or 0
            import time as _t
            oldest_days.append(int((_t.time() - base) / 86400))
        lo, hi = min(oldest_days), max(oldest_days)
        span = f"{lo}-{hi}" if hi != lo else f"{lo}"
        print(f"• {len(stale)} khách cần follow-up ({span} ngày chưa liên lạc)")
    if old_listings:
        print(f"• {len(old_listings)} tin >14 ngày chưa cập nhật")
    if deferred:
        print("\n📌 Việc để lại từ hôm qua:")
        for i, it in enumerate(deferred, 1):
            print(f"[{i}. {it.get('label') or it['kind']}"
                  f" -> eve:go:{it['kind']}:{it['ref_id']}]")
    if not viewings and not stale and not old_listings and not deferred:
        print("• Hôm nay trống lịch — tranh thủ đăng tin mới nhé! 😊")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print only (default behavior; sending is separate)")
    ap.parse_args()
    db.init_db()
    day_start, day_end = _day_bounds()
    brokers = db.list_brokers()
    if not brokers:
        print("No brokers.")
        return
    for b in brokers:
        brief_broker(b, day_start, day_end)
        print()


if __name__ == "__main__":
    main()
