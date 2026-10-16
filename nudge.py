"""Availability nudge — standalone script.

Finds listings not updated in NUDGE_DAYS and prints reminder messages.
Run daily via cron. Sending via the bot is wired up separately.

Usage: python nudge.py [--days 7] [--dry-run]
"""
import argparse
import time

import config
import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.NUDGE_DAYS)
    ap.add_argument("--dry-run", action="store_true",
                    help="print only, do not mark as nudged")
    args = ap.parse_args()

    db.init_db()
    stale = db.stale_listings(older_than_days=args.days)
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
        print(f"--- to user_id={l['broker_id']} ({name}) ---")
        print(f"Tin {br_s} {loc} ({price_s}) đã {days} ngày rồi, còn trống không anh?")
        print("[Còn trống ✓] [Đã cho thuê]")
        print()


if __name__ == "__main__":
    main()
