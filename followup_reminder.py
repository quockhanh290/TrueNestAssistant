"""Follow-up reminders — standalone script.

Two sections, printed per broker (sending via the bot is wired separately):

  A. Post-viewing feedback prompts — viewings that ended within the last
     24h and still have no feedback.
  B. Stale-client follow-ups — clients not contacted for 3+ days, with
     their actual viewings (listings + per-listing feedback).

Usage: python followup_reminder.py [--dry-run]
"""
import argparse
import datetime
import time

import db


def _fmt_price(v):
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
    return f"{br_s} {loc}, {_fmt_price(p.get('price_vnd'))}/tháng"


def _req_summary(c):
    parts = []
    br = c.get("bedrooms")
    if br is not None:
        try:
            parts.append("Studio" if float(br) == 0 else f"{int(float(br))}PN")
        except (TypeError, ValueError):
            pass
    if c.get("district"):
        parts.append(c["district"])
    if c.get("budget_max"):
        parts.append(f"<{_fmt_price(c['budget_max'])}")
    return " ".join(parts) or "chưa rõ nhu cầu"


def _feedback_map(v):
    import json
    raw = (v.get("feedback") or "").strip()
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _viewing_block(v):
    """One viewing -> lines with per-listing feedback."""
    d = datetime.datetime.fromtimestamp(v["scheduled_at"])
    lines = [f"  🏠 Đã xem ngày {d.day}/{d.month}:"]
    fb = _feedback_map(v)
    for i, lid in enumerate(v.get("listing_ids") or [], 1):
        lines.append(f"    {i}. {_listing_brief(lid)}")
        cmt = fb.get(lid)
        if cmt:
            lines.append(f'       💬 "{cmt}"')
    return lines


def _broker_name(b):
    return b.get("display_name") or b.get("username") or "anh"


def section_feedback():
    """A. viewings ended <24h ago without feedback."""
    due = db.due_feedback_viewings(hours_after=0, hours_before=24)
    if not due:
        print("A. Không có buổi xem nào cần feedback.")
        return
    print("A. Nhắc nhập feedback sau buổi xem:")
    for v in due:
        cname = v.get("client_name") or "khách"
        lids = v.get("listing_ids") or []
        name = v.get("display_name") or v.get("username") or "anh"
        print(f"--- to user_id={v['broker_id']} ({name}) ---")
        print(f"Hôm qua anh dẫn {cname} xem {len(lids)} căn."
              f" Khách feedback sao ạ?")
        for lid in lids:
            print(f"  • {_listing_brief(lid)}  [vw:fb:{v['id']}]")


def section_stale():
    """B. stale clients with their viewing history."""
    brokers = db.list_brokers()
    any_out = False
    for b in brokers:
        stale = db.stale_clients(b["user_id"], days=3)
        if not stale:
            continue
        any_out = True
        name = _broker_name(b)
        print(f"--- to user_id={b['user_id']} ({name}) ---")
        print("⏰ Nhắc follow-up\n")
        urg_e = {"urgent": "🔴", "normal": "🟡", "low": "🟢"}
        for c in stale:
            cname = c.get("name") or "(chưa có tên)"
            print(f"• 👤 {cname} {urg_e.get(c.get('urgency'), '🟡')}"
                  f" — {c.get('phone') or 'chưa có SĐT'}")
            print(f"  💰 {_req_summary(c)}")
            viewings = db.client_viewings(c["id"])[:3]
            for v in viewings:
                for line in _viewing_block(v):
                    print(line)
            print(f"  [📝 Ghi chú] [🏠 Gửi thêm tin] [📅 Đặt lịch xem]")
            print(f"  [client:{c['id']}:0:a:a]")
            print()
    if not any_out:
        print("B. Không có khách nào cần follow-up.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print only (default behavior; sending is separate)")
    ap.parse_args()
    db.init_db()
    section_feedback()
    print()
    section_stale()


if __name__ == "__main__":
    main()
