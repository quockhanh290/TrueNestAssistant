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


async def notify_velocity_warning(ctx, broker_id, count, window_min):
    """DM broker when refresh velocity looks suspicious (Khanh 2026-10-16)."""
    prefs = db.get_notify_prefs(broker_id)
    if not prefs.get("notify_quality", True):
        return
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"⚠️ Anh vừa cập nhật <b>{count} tin</b>"
                f" trong {window_min} phút\n\n"
                "Tốc độ này khó có thể kiểm tra kỹ từng tin.\n"
                "Hệ thống sẽ ưu tiên kiểm tra ngẫu nhiên các tin này.\n\n"
                "Nếu phát hiện báo sai, điểm uy tín sẽ bị trừ."),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔕 Tắt thông báo này",
                    callback_data="notify:off:notify_quality")],
            ]),
        )
    except Exception as e:
        log.warning("velocity warning notify failed: %s", e)


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


async def notify_stale_listings(ctx, broker_id, stale):
    """DM broker about listings older than 14 days.

    stale: list of (listing_id, title, age_days). Respects the
    notify_quality preference (freshness is a quality signal).
    """
    prefs = db.get_notify_prefs(broker_id)
    if not prefs.get("notify_quality", True):
        return
    if not stale:
        return
    n = len(stale)
    lines = "\n".join(
        f"• {t} ({int(a)} ngày)" for _, t, a in stale[:5]
    )
    if n > 5:
        lines += f"\n• ... và {n - 5} tin khác"
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"📅 <b>{n} tin của anh đã cũ (&gt;14 ngày)</b>\n\n"
                f"{lines}\n\n"
                f"Tin cũ khó được khách chọn. Cập nhật trạng thái nhé!"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔄 Cập nhật trong web app",
                    web_app=WebAppInfo(url=webapp_url()))]]),
        )
    except Exception as e:
        log.warning("stale notify failed: %s", e)


async def sweep_stale_listings(ctx):
    """Weekly sweeper: DM every broker that has listings >14 days stale.

    Intended trigger: bot job_queue weekly run (parent wires the schedule).
    Uses updated_at (last status refresh), falling back to created_at.
    """
    import time
    now = time.time()
    cutoff = now - 14 * 86400
    try:
        brokers = db.list_brokers()
    except Exception as e:
        log.warning("stale sweep: list_brokers failed: %s", e)
        return
    for b in brokers:
        uid = b.get("user_id")
        if not uid:
            continue
        try:
            rows = db.list_broker_listings(
                uid, limit=200, offset=0,
                statuses=("submitted", "active", "uncertain"))
        except Exception:
            continue
        stale = []
        for r in rows:
            ts = r.get("updated_at") or r.get("created_at") or 0
            age_d = (now - ts) / 86400
            if age_d > 14:
                p = r.get("parsed") or {}
                title = (p.get("building_name") or p.get("district")
                         or "Tin")
                stale.append((r["id"], title, age_d))
        if stale:
            await notify_stale_listings(ctx, uid, stale)


async def notify_false_refresh(ctx, broker_id, listing_title, old_score,
                               new_score, false_count):
    """DM broker a reputation warning after a false refresh claim.

    Called when a listing the broker marked "available" via refresh is
    later found to be rented. -10 profile points per strike; 3 strikes ->
    7-day propose cooldown.
    """
    from utils import broker_profile_score  # noqa: E402
    _ = broker_profile_score  # referenced for clarity; scores passed in
    if false_count >= db.FALSE_REFRESH_BAN_COUNT:
        tail = ("🚫 Anh đã bị hạn chế quyền đề xuất trong 7 ngày.")
    else:
        left = db.FALSE_REFRESH_BAN_COUNT - false_count
        tail = (f"Báo sai {left} lần nữa sẽ bị hạn chế quyền propose.")
    try:
        await ctx.bot.send_message(
            chat_id=broker_id,
            text=(
                f"⚠️ <b>Cảnh báo uy tín</b>\n\n"
                f"Tin \"{listing_title}\" anh báo \"còn trống\"\n"
                f"nhưng thực tế đã cho thuê.\n\n"
                f"Điểm uy tín: {old_score} → {new_score} (-10đ)\n"
                f"{tail}"),
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning("false refresh notify failed: %s", e)


async def penalize_false_refresh(ctx, listing_id):
    """Apply the full false-refresh penalty pipeline for a listing.

    Returns the penalty dict from db.flag_false_refresh, or None.
    Intended callers: dedup flow, client feedback handler, admin check.
    """
    from utils import broker_profile_score  # noqa: E402
    lst = db.get_listing(listing_id)
    if not lst:
        return None
    broker_id = lst.get("broker_id")
    before = broker_profile_score(broker_id).get("score")
    result = db.flag_false_refresh(listing_id)
    if not result:
        return None
    after = broker_profile_score(broker_id).get("score")
    p = lst.get("parsed") or {}
    title = p.get("building_name") or p.get("district") or "Tin"
    await notify_false_refresh(ctx, broker_id, title, before, after,
                               result["false_count"])
    return result
