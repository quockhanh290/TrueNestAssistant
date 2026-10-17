"""Admin MVP metrics dashboard (/metrics).

Simple text dashboard proving the MVP works. Admin-only — Khanh uses it
to track brokers, matches, revenue and debts (công nợ cross-check).
"""
import html
import time

from telegram import Update
from telegram.ext import ContextTypes

import config
import db

WINDOW_DAYS = 7


def _fmt_vnd(v):
    """Compact VND for dashboard: 2400000 -> '2.4tr', 150000 -> '150K'."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "0đ"
    if v >= 1_000_000_000:
        return f"{v / 1e9:.1f}".rstrip("0").rstrip(".") + "tỷ"
    if v >= 1_000_000:
        return f"{v / 1e6:.1f}".rstrip("0").rstrip(".") + "tr"
    if v >= 1_000:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}đ"


async def cmd_metrics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only /metrics — MVP dashboard for the last 7 days."""
    uid = update.effective_user.id
    if not config.ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Chưa cấu hình admin (ADMIN_TELEGRAM_ID).")
        return
    if uid != config.ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Lệnh này chỉ dành cho admin ạ 😊")
        return

    since = time.time() - WINDOW_DAYS * 86400
    m = db.get_metrics_summary(since)

    per_broadcast = (m["match_reserve"] / m["match_broadcast"]
                     if m["match_broadcast"] else 0)

    lines = [
        f"📊 <b>TrueNest Metrics ({WINDOW_DAYS} ngày qua)</b>",
        "",
        "👥 <b>Broker:</b>",
        f"• Active: <b>{m['brokers_active']}</b>",
        f"• Mới: <b>{m['brokers_new']}</b>",
        f"• Tổng tin: <b>{m['listings_total']}</b>",
        "",
        "🤝 <b>Match:</b>",
        f"• Broadcast: <b>{m['match_broadcast']}</b>",
        f"• Reserve: <b>{m['match_reserve']}</b> ({per_broadcast:.1f}/broadcast)",
        f"• Submit: <b>{m['match_submit']}</b>",
        f"• Khách chọn: <b>{m['match_chosen']}</b>",
        "",
        "💰 <b>Doanh thu:</b>",
        "• Concierge: 0 job (chưa triển khai)",
        f"• Hoa hồng: <b>{m['deals_count']}</b> deal × "
        f"{_fmt_vnd(m['commission_total'])}",
    ]

    # ---- công nợ: per-broker list for bill cross-check ----
    if m["debts"]:
        total_debt = sum(d["total"] for d in m["debts"])
        lines.append(
            f"• Công nợ: <b>{len(m['debts'])}</b> broker — "
            f"{_fmt_vnd(total_debt)} (chưa thanh toán)"
        )
        for d in m["debts"][:10]:
            lines.append(
                f"  └ {html.escape(d['name'])}: "
                f"<b>{_fmt_vnd(d['total'])}</b> "
                f"({d['deals']} deal, quá hạn {d['days_overdue']} ngày)"
            )
    else:
        lines.append("• Công nợ: không có 🎉")

    lines += ["", "⚠️ <b>Cảnh báo:</b>"]
    if m["pending_confirm"]:
        by_broker = {}
        for p in m["pending_confirm"]:
            by_broker[p["broker_name"]] = by_broker.get(p["broker_name"], 0) + 1
        who = ", ".join(
            f"{html.escape(n)} ({c})" for n, c in list(by_broker.items())[:5]
        )
        lines.append(
            f"• {len(m['pending_confirm'])} deal cần xác nhận (30 ngày): {who}"
        )
    else:
        lines.append("• Không có deal nào cần xác nhận")
    if m["flagged_brokers"]:
        bits = []
        for f in m["flagged_brokers"][:5]:
            label = html.escape(f["name"])
            if f["banned"]:
                bits.append(f"{label} (BAN)")
            elif f["muted"]:
                bits.append(f"{label} (mute)")
            else:
                bits.append(f"{label} ({f['strikes']} strike)")
        lines.append(f"• Broker vi phạm: {', '.join(bits)}")
    else:
        lines.append("• Không có broker vi phạm")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ================================================== /baocao (17/10)
# Admin view of share-page reports from clients, with a "Gỡ phạt" button
# for each report whose automatic strike was applied.

REPORTS_SHOWN = 20
_UNPEN_PREFIX = "rpt:unpen:"


def _is_admin(uid):
    return bool(config.ADMIN_TELEGRAM_ID) and uid == config.ADMIN_TELEGRAM_ID


def _short(s, n=40):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def _report_line(r):
    """One report as an HTML line; every user-supplied value is escaped."""
    from db import vntime
    p = r.get("listing_parsed") or {}
    title = (p.get("building_name") or p.get("district")
             or r.get("listing_id") or "?")
    who = (r.get("broker_name") or
           (("@" + r["broker_username"]) if r.get("broker_username") else "")
           or str(r.get("broker_id")))
    reason = db.REPORT_REASON_VI.get(r.get("reason"), r.get("reason") or "?")
    token = r.get("token") or ""
    base = (getattr(config, "WEBAPP_URL", "") or "").rstrip("/")
    link_txt = html.escape(f"/s/{token[:8]}…")
    link = (f'<a href="{html.escape(base + "/s/" + token, quote=True)}">'
            f"{link_txt}</a>") if base else link_txt
    state = {
        "applied": "⚠️ đã phạt",
        "revoked": "↩️ đã gỡ phạt",
        "reserved": "⏳ chờ áp phạt",
    }.get(r.get("penalty"), "không phạt")
    return (
        f"#{int(r['id'])} · {vntime.fmt(r['created_at'], '%H:%M %d/%m')}\n"
        f"🏠 {html.escape(_short(title))} · 👤 {html.escape(_short(who, 30))}"
        f" (<code>{html.escape(str(r.get('broker_id')))}</code>)\n"
        f"Lý do: {html.escape(reason)} · Link: {link} · {state}")


def _baocao_message():
    """(text, keyboard or None) for the newest reports."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    reports = db.list_recent_reports(REPORTS_SHOWN)
    if not reports:
        return "📭 Chưa có báo cáo nào từ trang chia sẻ.", None
    lines = [f"🚩 <b>{len(reports)} báo cáo gần nhất</b> (giờ VN)\n"]
    lines += [_report_line(r) for r in reports]
    text = "\n\n".join(lines)
    if len(text) > 4000:          # Telegram's limit is 4096
        text = text[:3990].rsplit("\n\n", 1)[0] + "\n\n…"
    kb = [[InlineKeyboardButton(f"↩️ Gỡ phạt #{int(r['id'])}",
                                callback_data=f"{_UNPEN_PREFIX}{int(r['id'])}")]
          for r in reports if r.get("penalty") == "applied"]
    return text, (InlineKeyboardMarkup(kb) if kb else None)


async def cmd_baocao(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only /baocao — newest share-page reports."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Lệnh này chỉ dành cho admin ạ 😊")
        return
    text, kb = _baocao_message()
    await update.message.reply_text(text, parse_mode="HTML",
                                    reply_markup=kb,
                                    disable_web_page_preview=True)


async def baocao_unpen_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """rpt:unpen:<report_id> — admin takes back that report's strike."""
    q = update.callback_query
    if not _is_admin(q.from_user.id):
        await q.answer("Không có quyền.", show_alert=True)
        return
    try:
        rid = int((q.data or "")[len(_UNPEN_PREFIX):])
    except ValueError:
        await q.answer()
        return
    res = db.revoke_report_penalty(rid)
    if not res:
        await q.answer("Báo cáo này không còn lượt phạt để gỡ.",
                       show_alert=True)
        return
    await q.answer("Đã gỡ phạt ✓")
    tail = " Đã mở khoá đề xuất." if res["unlocked"] else ""
    await ctx.bot.send_message(
        q.from_user.id,
        f"↩️ Đã gỡ phạt báo cáo #{rid} cho môi giới"
        f" <code>{html.escape(str(res['broker_id']))}</code>:"
        f" còn {int(res['false_count'])} lượt phạt.{tail}",
        parse_mode="HTML")
