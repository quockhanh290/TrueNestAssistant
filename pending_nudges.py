"""Pending-task nudges — standalone script.

Reminds brokers about unfinished work (sending via the bot is wired
separately):

  6a. Viewings 24-72h past with no feedback yet.
  6b. Clients added 2+ days ago that were never sent any listing.
  6c. Broadcast requests with responses the broker hasn't viewed in 1+ day.
  6d. Clients sent listings 2+ days ago with no recorded choice yet.

Usage: python pending_nudges.py [--dry-run]
"""
import argparse
import datetime

import db


def _broker_name(b):
    return b.get("display_name") or b.get("username") or "anh"


def section_unfeedbacked():
    rows = []
    for b in db.list_brokers():
        for v in db.unfeedbacked_viewings(b["user_id"],
                                          min_hours=24, max_hours=72):
            rows.append((b, v))
    if not rows:
        print("6a. Không có buổi xem nào thiếu feedback quá 24h.")
        return
    print("6a. Nhắc nhập feedback (buổi xem đã qua 24h+):")
    for b, v in rows:
        name = _broker_name(b)
        cname = v.get("client_name") or "khách"
        d = datetime.datetime.fromtimestamp(v["scheduled_at"])
        print(f"--- to user_id={b['user_id']} ({name}) ---")
        print(f"Ngày {d.day}/{d.month} anh dẫn {cname} xem nhà mà chưa nhập"
              f" feedback. Khách nói sao ạ?  [vw:fb:{v['id']}]")


def section_idle_clients():
    any_out = False
    for b in db.list_brokers():
        idle = db.idle_new_clients(b["user_id"], days=2)
        if not idle:
            continue
        any_out = True
        name = _broker_name(b)
        for c in idle:
            cname = c.get("name") or "(chưa có tên)"
            d = datetime.datetime.fromtimestamp(c["created_at"])
            print(f"--- to user_id={b['user_id']} ({name}) ---")
            print(f"{cname} thêm từ ngày {d.day}/{d.month} rồi mà anh chưa"
                  f" gửi tin nào. Gửi ngay không?"
                  f"  [client:match:{c['id']}]")
    if not any_out:
        print("6b. Không có khách mới nào bị bỏ quên.")


def section_unseen_responses():
    any_out = False
    for b in db.list_brokers():
        unseen = db.unseen_match_responses(b["user_id"], min_hours=24)
        if not unseen:
            continue
        any_out = True
        name = _broker_name(b)
        for r in unseen:
            c = db.get_client(r["client_id"])
            cname = (c.get("name") if c else None) or "khách"
            d = datetime.datetime.fromtimestamp(r["latest_at"])
            print(f"--- to user_id={b['user_id']} ({name}) ---")
            print(f"Yêu cầu tìm nhà cho {cname} đã có {r['n_resp']} phản hồi"
                  f" từ ngày {d.day}/{d.month} mà anh chưa xem."
                  f" Xem ngay nhé!  [mresp:view:{r['id']}]")
    if not any_out:
        print("6c. Không có phản hồi broadcast nào bị bỏ quên.")


def section_awaiting_choice():
    any_out = False
    for b in db.list_brokers():
        waiting = db.clients_awaiting_choice(b["user_id"], days=2)
        if not waiting:
            continue
        any_out = True
        name = _broker_name(b)
        for c in waiting:
            cname = c.get("name") or "(chưa có tên)"
            n = len(c.get("sent_listings") or [])
            print(f"--- to user_id={b['user_id']} ({name}) ---")
            print(f"Đã gửi {n} tin cho {cname} được 2 ngày rồi mà chưa"
                  f" biết khách ưng căn nào. Hỏi lại khách nhé!"
                  f"  [send2client:followup:{c['id']}]")
    if not any_out:
        print("6d. Không có khách nào đang chờ chọn căn.")


def section_stale_listings():
    """6e. Listings not updated in 7+ days — batched availability check.

    Prints one batched message per broker (10 listings/page, always with
    the total count). The sender delivers it with inline buttons; taps
    route to stale:* callbacks in feat_stale.py (stateless).
    """
    import time as _time
    any_out = False
    stale = db.stale_listings(older_than_days=7,
                              statuses=("submitted", "uncertain"))
    by_broker = {}
    for l in stale:
        by_broker.setdefault(l["broker_id"], []).append(l)
    for uid, items in by_broker.items():
        # most-active first so wholesalers see important ones first
        items.sort(key=lambda l: (l.get("inquiry_count", 0) * 10 +
                                  l.get("view_count", 0)),
                   reverse=True)
        any_out = True
        b = db.get_broker(uid) or {}
        name = _broker_name(b)
        total = len(items)
        page = items[:10]
        print(f"--- to user_id={uid} ({name}) ---")
        print(f"6e. [STALE_BATCH total={total} page=0]")
        lines = [f"📋 Anh có {total} tin cũ cần cập nhật (đang hiện 1-"
                 f"{min(10, total)}):", ""]
        for i, l in enumerate(page, start=1):
            p = l.get("parsed") or {}
            br = p.get("bedrooms")
            br_s = ("Studio" if br == 0.0
                    else (f"{int(br)}PN" if br else "?PN"))
            loc = p.get("building_name") or p.get("district") or "?"
            price = p.get("price_vnd")
            price_s = f"{price / 1_000_000:g}tr" if price else "?/tháng"
            days = int((_time.time() - l["updated_at"]) / 86400)
            lines.append(f"{i}. 🏠 {br_s} {loc}, {price_s}"
                         f" — {days} ngày chưa update")
            lines.append(f"   [{i} ✅ -> stale:ok:{l['id']}]"
                         f" [{i} ❌ -> stale:rented:{l['id']}]"
                         f" [{i} ❓ -> stale:unsure:{l['id']}]")
        lines += ["", "Mỗi tin chọn 1 nhé 👇"]
        if total > 10:
            lines.append(f"[Xem thêm 10 tin (11-{min(20, total)}/{total})"
                         f" -> stale:more:1]")
        print("\n".join(lines))
    if not any_out:
        print("6e. Không có tin cũ nào cần cập nhật.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print only (default behavior; sending is separate)")
    ap.parse_args()
    db.init_db()
    section_unfeedbacked()
    print()
    section_idle_clients()
    print()
    section_unseen_responses()
    print()
    section_awaiting_choice()
    print()
    section_stale_listings()


if __name__ == "__main__":
    main()
