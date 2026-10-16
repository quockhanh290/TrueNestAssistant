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
