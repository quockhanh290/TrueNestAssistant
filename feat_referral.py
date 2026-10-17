"""Broker referral/invite system — /moi command + auto qualification.

Khanh 2026-10-16: invite 3 brokers (each creates 5 quality listings:
AI score >= 50, has photos, active >= 7 days) -> 1 month Pro free,
max 3 months stacked. Anti-fraud: phone/photo/behavior checks.
"""
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import db
from db import vntime

log = logging.getLogger("linh")


def referral_link(broker_id):
    """Deep link a broker can share: t.me/<bot>?start=ref_<id>."""
    username = (getattr(config, "BOT_USERNAME", "") or "").lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start=ref_{broker_id}"


def _progress_bar(qualified, needed):
    return "✅" * qualified + "⬜" * max(0, needed - qualified)


def _moi_text(uid, broker=None):
    prog = db.get_referral_progress(uid)
    q, n = prog["qualified"], prog["needed"]
    link = referral_link(uid)
    lines = [
        "🎁 <b>Mời bạn dùng TrueNest</b>",
        "",
        "Mỗi người bạn mời nhập <b>5 tin đạt chuẩn</b>",
        "(điểm AI ≥ 50, có ảnh, còn trống ≥ 7 ngày)",
        f"→ đủ <b>{n} người</b>, anh được tặng",
        "<b>1 tháng Pro miễn phí!</b> 🎉",
        "",
        f"Tiến độ: {q}/{n} {_progress_bar(q, n)}",
    ]
    if q >= n:
        lines.append("✅ Anh đã nhận thưởng rồi — mời thêm để tích tháng Pro!")
    if link:
        lines += ["", "Link của anh:", link]
    else:
        lines += ["",
                  "⚠️ Chưa cấu hình BOT_USERNAME — báo Khanh nhé."]
    return "\n".join(lines)


def _moi_kb(uid):
    link = referral_link(uid)
    rows = []
    if link:
        rows.append([InlineKeyboardButton("📋 Lấy link mời",
                                          callback_data="referral:copylink")])
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


async def cmd_moi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/moi — show referral link + progress."""
    uid = update.effective_user.id
    broker = db.get_broker(uid)
    if not broker:
        await update.message.reply_text(
            "Anh/chị chưa đăng ký. Bấm /start để bắt đầu nhé.")
        return
    await update.message.reply_text(
        _moi_text(uid, broker), parse_mode="HTML",
        reply_markup=_moi_kb(uid),
        disable_web_page_preview=True)


async def handle_referral_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback: referral:copylink — resend the raw link for easy copying."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    link = referral_link(uid)
    if not link:
        await q.edit_message_text(
            "⚠️ Chưa cấu hình BOT_USERNAME — báo Khanh nhé.")
        return
    try:
        await q.edit_message_text(
            "📋 <b>Link mời của anh</b> (chạm giữ để copy):\n\n"
            f"<code>{link}</code>\n\n"
            "Gửi cho bạn bè môi giới nhé! 🎁",
            parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=_moi_kb(uid))
    except Exception as e:
        log.warning("referral copylink edit failed: %s", e)


def parse_start_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Hook for /start: record referral if launched via invite link.

    Call from cmd_start AFTER get_or_create_broker. Returns the
    inviter_id if a new referral was recorded, else None.
    """
    u = update.effective_user
    args = getattr(ctx, "args", None) or []
    if not args:
        return None
    ref = (args[0] or "").strip()
    if not ref.startswith("ref_"):
        return None
    try:
        inviter_id = int(ref[4:])
    except ValueError:
        return None
    if inviter_id == u.id:
        return None
    row = db.create_referral(inviter_id, u.id)
    if not row:
        return None
    log.info("referral recorded: %s invited %s", inviter_id, u.id)
    return inviter_id


async def announce_inviter(ctx, inviter_id, invitee_name):
    """Tell the inviter someone joined via their link."""
    try:
        await ctx.bot.send_message(
            inviter_id,
            "🎉 <b>Có bạn mới tham gia!</b>\n\n"
            f"{invitee_name} vừa đăng ký qua link mời của anh.\n"
            "Khi bạn ấy nhập đủ 5 tin đạt chuẩn, anh được tính 1 lượt nhé!",
            parse_mode="HTML")
    except Exception as e:
        log.warning("announce_inviter failed: %s", e)


async def on_listing_submitted(ctx, broker_id):
    """Auto-check hook — call after a listing reaches 'submitted'.

    If this broker was invited and now qualifies: run fraud checks,
    mark qualified, and grant the inviter's reward at 3.
    """
    ref = db.get_referral_by_invitee(broker_id)
    if not ref or ref.get("qualified_at"):
        return
    qualified, count = db.check_invitee_qualified(broker_id)
    if not qualified:
        return
    # fraud gate before counting this invitee
    fraud = db.run_fraud_checks(broker_id)
    if not fraud["ok"]:
        log.warning("referral fraud for invitee %s: %s",
                    broker_id, fraud["reasons"])
        # notify admin-ish: DM the inviter that this one didn't count
        try:
            await ctx.bot.send_message(
                ref["inviter_id"],
                "⚠️ <b>Lượt mời không được tính</b>\n\n"
                "Hệ thống phát hiện dấu hiệu gian lận"
                f" ({', '.join(fraud['reasons'])})."
                " Lượt này không tính vào tiến độ mời bạn.",
                parse_mode="HTML")
        except Exception:
            pass
        return
    for w in fraud["warnings"]:
        log.warning("referral review: %s", w)
    db.mark_qualified(broker_id)
    inviter_id = ref["inviter_id"]
    prog = db.get_referral_progress(inviter_id)
    # progress DM to inviter
    try:
        await ctx.bot.send_message(
            inviter_id,
            "✅ <b>Bạn mời đã đạt chuẩn!</b>\n\n"
            f"Tiến độ mời bạn: {prog['qualified']}/{prog['needed']} "
            f"{_progress_bar(prog['qualified'], prog['needed'])}",
            parse_mode="HTML")
    except Exception as e:
        log.warning("referral progress DM failed: %s", e)
    # reward at threshold
    exp = db.maybe_grant_inviter_reward(inviter_id)
    if exp and exp != "capped":
        date_str = vntime.fmt(exp, "%d/%m/%Y")
        try:
            await ctx.bot.send_message(
                inviter_id,
                "🎉 <b>Chúc mừng!</b>\n\n"
                f"Anh đã mời đủ {db.REFERRAL_REQUIRED} người đạt chuẩn!\n"
                f"Tặng anh <b>1 tháng Pro miễn phí</b> (đến {date_str}). 🎁",
                parse_mode="HTML")
        except Exception as e:
            log.warning("referral reward DM failed: %s", e)
