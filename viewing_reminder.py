"""Viewing reminders — standalone script.

Finds scheduled viewings starting within the next hour and prints reminder
messages. Run hourly via cron. Sending via the bot is wired up separately.

Usage: python viewing_reminder.py [--within 3600] [--dry-run]
"""
import argparse
import time

import config
import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--within", type=int, default=3600,
                    help="remind for viewings starting within N seconds")
    ap.add_argument("--dry-run", action="store_true",
                    help="print only, do not mark as reminded")
    args = ap.parse_args()

    db.init_db()
    due = db.due_viewings(within_seconds=args.within)
    if not due:
        print("No upcoming viewings.")
        return

    import datetime
    for v in due:
        d = datetime.datetime.fromtimestamp(v["scheduled_at"])
        mins = int((v["scheduled_at"] - time.time()) / 60)
        cname = v.get("client_name") or "khách"
        listing_txt = ""
        if v.get("listing_id"):
            l = db.get_listing(v["listing_id"])
            if l:
                p = l["parsed"]
                br = p.get("bedrooms")
                br_s = ("studio" if br == 0.0
                        else (f"{int(br)}PN" if br else "?PN"))
                loc = p.get("building_name") or p.get("district") or "?"
                price = p.get("price_vnd")
                price_s = f"{price / 1_000_000:g}tr" if price else "?"
                addr = p.get("street") or ""
                listing_txt = (f"\n🏠 {br_s} {loc}, {price_s}/tháng"
                               + (f"\n📍 {addr}" if addr else ""))
        name = v.get("display_name") or v.get("username") or "anh"
        print(f"--- to user_id={v['broker_id']} ({name}) ---")
        print(f"⏰ Sắp đến giờ dẫn khách rồi anh ơi! (còn ~{mins} phút)")
        print(f"👤 {cname}")
        print(f"🕙 {d.strftime('%H:%M')} ngày {d.day}/{d.month}"
              f"{listing_txt}")
        print()


if __name__ == "__main__":
    main()
