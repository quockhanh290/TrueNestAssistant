"""Proactive bot notifications + /thongbao preferences.

Khanh 2026-10-16: bot must proactively notify brokers when needed —
matching leads, quality drops, trial expiry, new bookings.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

import db
from utils import get_pronoun, webapp_url

log = logging.getLogger("linh")


def _prefs_text(uid):
    prefs = db.get_notify_prefs(uid)
    lines = ["🔔 <b>Thông báo của anh:</b>", ""]
    for pref, label in db.NOTIFY_PREF_LABELS.items():
        state = "✅ Bật" if prefs.get(pref) else "❌ Tắt"
        lines.append(f"• {label}: {state}")
    return "\n".join(lines)


def _prefs_kb(uid):
    prefs = db.get_notify_prefs(uid)
    rows = []
    for pref, label in db.NOTIFY_PREF_LABELS.items():
        on = prefs.get(pref, True)
        rows.append([InlineKeyboardButton(
            f"{'✅' if on else '❌'} {label}",
            callback_data=f"notify:pref:{pref}")])
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


async def cmd_thongbao(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show notification preferences with toggle buttons."""
    uid = update.effective_user.id
    await update.message.reply_text(
        _prefs_text(uid), parse_mode="HTML",
        reply_markup=_prefs_kb(uid))


async def notify_pref_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Toggle one preference. Callback: notify:pref:<pref> or notify:off:<pref>."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    parts = (q.data or "").split(":")
    pref = parts[2] if len(parts) > 2 else ""
    if pref not in db.NOTIFY_PREFS:
        return
    if parts[1] == "off":
        # one-tap unsubscribe from a proactive DM
        db.set_notify_pref(uid, pref, False)
        await q.edit_message_text(
            f"Đã tắt thông báo <b>{db.NOTIFY_PREF_LABELS[pref]}</b>.\n"
            f"Bật lại bằng /thongbao nhé.",
            parse_mode="HTML")
        return
    # toggle
    prefs = db.get_notify_prefs(uid)
    new_val = not prefs.get(pref, True)
    db.set_notify_pref(uid, pref, new_val)
    try:
        await q.edit_message_text(
            _prefs_text(uid), parse_mode="HTML",
            reply_markup=_prefs_kb(uid))
    except Exception as e:
        log.warning("prefs edit failed: %s", e)


async def notify_quality_drop(ctx, broker_id, listing_id, old_score, new_score,
                              top_missing):
    """DM broker when a listing's quality score drops below 50."""
    prefs = db.get_notify_prefs(broker_id)
    if not prefs.get("notify_quality", True):
        return
    lst = db.get_listing(listing_id)
    if not lst:
        return
    p = lst.get("parsed") or {}
    title = p.get("building_name") or p.get("district") or "Tin"
    tips = "\n".join(f"• {m}" for m in (top_missing or [])[:3])
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"📉 Tin <b>{title}</b> của anh đang có điểm {new_score}đ"
                f" (trước {old_score}đ)\n\n"
                f"💡 Bổ sung để tăng điểm:\n{tips}\n\n"
                f"Tin điểm cao dễ được khách chọn hơn!"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✏️ Bổ sung ngay",
                    web_app=WebAppInfo(url=webapp_url(
                        view="listing", id=listing_id)))]]),
        )
    except Exception as e:
        log.warning("quality drop notify failed: %s", e)


async def notify_trial_expiring(ctx, broker_id, feature, remaining):
    """DM broker when 1 trial remains for a gated feature."""
    prefs = db.get_notify_prefs(broker_id)
    if not prefs.get("notify_trial", True):
        return
    feature_names = {
        "send2client": "Gửi tin cho khách",
        "xbroker_match": "Match liên broker",
    }
    tier = db.TRIAL_TIER.get(feature, "pro") if hasattr(db, "TRIAL_TIER") else "pro"
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"🎁 Anh còn <b>1/3</b> lượt dùng thử"
                f" <b>{feature_names.get(feature, feature)}</b>\n\n"
                f"Nâng cấp gói {tier.upper()} để dùng không giới hạn nhé!"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⭐ Xem gói",
                    callback_data="menu:premium")],
                [InlineKeyboardButton(
                    "🔕 Tắt thông báo này",
                    callback_data="notify:off:notify_trial")],
            ]),
        )
    except Exception as e:
        log.warning("trial expiring notify failed: %s", e)


async def notify_new_booking(ctx, broker_id, booking):
    """DM broker in real-time when a client books via share page.

    booking: dict with name, phone, listing_id, preferred_date, token.
    """
    prefs = db.get_notify_prefs(broker_id)
    if not prefs.get("notify_booking", True):
        return
    lst = db.get_listing(booking.get("listing_id")) if booking.get("listing_id") else None
    p = (lst.get("parsed") if lst else {}) or {}
    title = p.get("building_name") or p.get("district") or "tin"
    date = booking.get("preferred_date") or "chưa chọn ngày"
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"📅 <b>Khách vừa đặt lịch xem!</b>\n\n"
                f"👤 {booking.get('name')}\n"
                f"📱 {booking.get('phone')}\n"
                f"🏠 {title}\n"
                f"📅 Muốn xem: {date}"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👀 Xem chi tiết",
                    web_app=WebAppInfo(url=webapp_url(view="shares")))]]),
        )
    except Exception as e:
        log.warning("booking notify failed: %s", e)
