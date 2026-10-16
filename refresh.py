"""Old-listing refresh suggestions — standalone script.

Finds submitted listings not updated in REFRESH_DAYS and prints reminder
messages with action buttons. Run weekly via cron. Sending via the bot is
wired up separately (see rf:* callbacks in bot.py).

Usage: python refresh.py [--days 14] [--dry-run]
"""
import argparse
import time

import config
import db

REFRESH_DAYS = 14


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=REFRESH_DAYS)
    ap.add_argument("--dry-run", action="store_true",
                    help="print only, do not mark as nudged")
    args = ap.parse_args()

    db.init_db()
    stale = db.stale_listings(older_than_days=args.days,
                              statuses=("submitted",))
    if not stale:
        print("No stale listings.")
        return

    for l in stale:
        p = l["parsed"]
        br = p.get("bedrooms")
        br_s = "studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
        loc = p.get("building_name") or p.get("district") or "?"
        price = p.get("price_vnd")
        price_s = f"{price / 1_000_000:g}tr" if price else "?"
        days = int((time.time() - l["updated_at"]) / 86400)
        name = l.get("display_name") or l.get("username") or "anh"
        print(f"--- to user_id={l['broker_id']} ({name}) listing={l['id']} ---")
        print(f"💡 Tin này đã {days} ngày rồi:")
        print(f"🏠 {br_s} {loc}, {price_s}/tháng")
        print()
        print("Anh muốn:")
        print(f"[🔄 Làm mới tin -> rf:renew:{l['id']}] "
              f"[🔑 Đã cho thuê -> rf:rented:{l['id']}]")
        print(f"[💰 Giảm giá -> rf:discount:{l['id']}] "
              f"[Bỏ qua -> rf:skip:]")
        print()


if __name__ == "__main__":
    main()
