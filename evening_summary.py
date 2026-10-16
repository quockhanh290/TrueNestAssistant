"""Evening summary — standalone script (run ~21h).

Per broker, prints today's wrap-up and the interactive checklist:

  [Lam luon -> eve:now] [De mai -> eve:later]

Checklist items are persisted in pending_checklist so "de mai" shows up
in the next morning brief. Sending via the bot is wired separately.

Usage: python evening_summary.py [--dry-run]
"""
import argparse
import datetime

import db

VN_TZ = datetime.timezone(datetime.timedelta(hours=7))


def _broker_name(b):
    return b.get("display_name") or b.get("username") or "anh"


def _fmt_money(v):
    if not v:
        return "?"
    try:
        return f"{float(v) / 1_000_000:g}tr"
    except (TypeError, ValueError):
        return "?"


def _listing_brief(lid):
    l = db.get_listing(lid)
    if not l:
        return "?"
    p = l.get("parsed") or {}
    br = p.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = p.get("building_name") or p.get("district") or "?"
    return f"{br_s} {loc} {_fmt_money(p.get('price_vnd'))}"


def _day_bounds():
    now_vn = datetime.datetime.now(VN_TZ)
    start = datetime.datetime.combine(now_vn.date(), datetime.time.min, VN_TZ)
    return (int(start.timestamp()),
            int((start + datetime.timedelta(days=1)).timestamp()),
            now_vn.date())


def summarize_broker(b, day_start, day_end, today):
    uid = b["user_id"]
    name = _broker_name(b)
    # ---- done today
    n_new = db.count_listings_created(uid, day_start, day_end)
    viewings = db.viewings_between(uid, day_start, day_end)
    n_view = len(viewings)
    n_units = sum(len(v.get("listing_ids") or []) for v in viewings)
    deals = db.deals_closed_between(uid, day_start, day_end)
    # ---- pending -> checklist items
    pending_fb = db.unfeedbacked_viewings(uid, min_hours=1, max_hours=72)[:5]
    stale_l = [l for l in db.stale_listings(older_than_days=14,
                                           statuses=("submitted",))
               if l.get("broker_id") == uid][:3]
    stale_c = db.stale_clients(uid, days=3, limit=10)[:3]

    items = []  # (kind, ref_id, label)
    for v in pending_fb:
        cname = v.get("client_name") or "khách"
        items.append(("feedback", v["id"], f"Feedback {cname}"))
    for l in stale_l:
        items.append(("refresh", l["id"],
                      f"Cập nhật giá: {_listing_brief(l['id'])}"))
    for c in stale_c:
        cname = c.get("name") or "khách"
        items.append(("call", c["id"], f"Gọi lại {cname}"))
    for kind, ref, label in items:
        db.add_checklist_item(uid, kind, ref, label)

    print(f"--- to user_id={uid} ({name}) ---")
    print("🌙 Tổng kết hôm nay:\n")
    print("✅ Đã làm:")
    done_bits = [f"{n_new} tin mới", f"{n_view} buổi xem ({n_units} căn)"]
    if deals:
        total = sum(d.get("commission_vnd") or 0 for d in deals)
        done_bits.append(f"{len(deals)} deal chốt ({_fmt_money(total)})")
    print("• " + " | ".join(done_bits))
    print("\n⏳ Chưa xong:")
    if items:
        for i, (_, _, label) in enumerate(items, 1):
            print(f"{i}. {label}")
        print("\nAnh muốn xử lý ngay hay để mai?")
        print("[🔨 Làm luôn -> eve:now] [😴 Để mai -> eve:later]")
    else:
        print("Không có gì tồn đọng. Ngủ ngon! 😴")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print only (default behavior; sending is separate)")
    ap.parse_args()
    db.init_db()
    day_start, day_end, today = _day_bounds()
    brokers = db.list_brokers()
    if not brokers:
        print("No brokers.")
        return
    for b in brokers:
        summarize_broker(b, day_start, day_end, today)
        print()


if __name__ == "__main__":
    main()
