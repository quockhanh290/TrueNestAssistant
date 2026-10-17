"""Premium tier / entitlement system.

Tiers:
  free — default, 20 active listings max, basic CRUD + button filters
  pro  — 99k/month: unlimited listings + smart features
  max  — 199k/month: pro + cross-broker matching + analytics

Upgrade flow: /premium -> broker picks tier -> transfers -> taps
"[I transferred]" -> admin notified -> /approve <id> <tier> activates.
"""
import html as _html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import db
from db import vntime
from utils import MENU_KB, get_pronoun, natural_delay

TIER_LABEL = {"free": "Free", "pro": "Pro 💎", "max": "Max 💎💎"}
TIER_PRICE = {"pro": "99k/tháng", "max": "199k/tháng"}

# Feature -> minimum tier required
FEATURE_TIER = {
    "natural_query": "pro",      # tìm kiếm bằng ngôn ngữ tự nhiên
    "auto_match": "pro",         # auto-match tin cho khách
    "fb_multilang": "pro",       # viết bài Hàn/Trung/Nga
    "viewings": "pro",           # lịch xem nhà
    "templates": "pro",          # mẫu tin nhắn
    "commission": "pro",         # theo dõi hoa hồng
    "refresh": "pro",            # gợi ý cập nhật tin cũ
    "send2client": "pro",        # gửi tin cho khách
    "followup": "free",          # nhắc follow-up (free theo quyết định)
    "broadcast": "max",          # match liên broker
    "analytics": "max",          # thống kê chi tiết
}

FEATURE_NAME_VI = {
    "natural_query": "Tìm kiếm bằng ngôn ngữ tự nhiên",
    "auto_match": "Tự động gợi ý tin cho khách",
    "fb_multilang": "Viết bài tiếng Hàn/Trung/Nga",
    "viewings": "Lịch xem nhà",
    "templates": "Mẫu tin nhắn",
    "commission": "Theo dõi hoa hồng",
    "refresh": "Gợi ý cập nhật tin cũ",
    "broadcast": "Match liên broker",
    "analytics": "Thống kê chi tiết",
}


def requires_tier(uid, feature):
    """True if the broker's tier unlocks this feature."""
    return db.tier_allows(uid, FEATURE_TIER.get(feature, "max"))


def premium_gate_text(feature, pn="anh"):
    """Upgrade prompt shown when a free user hits a paid feature."""
    fname = FEATURE_NAME_VI.get(feature, "Tính năng này")
    tier = FEATURE_TIER.get(feature, "pro")
    tlabel = TIER_LABEL.get(tier, "Pro 💎")
    price = TIER_PRICE.get(tier, "")
    return (
        f"🔒 <b>{fname}</b> là tính năng {tlabel} ({price}).\n\n"
        f"{pn.capitalize()} nâng cấp để dùng nhé — chỉ vài phút thôi ạ 😊"
    )


def premium_gate_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Xem các gói",
                              callback_data="premium:plans")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ])


async def send_gate(update_or_q, feature, uid, edit=False):
    """Show the upgrade gate for a gated feature."""
    pn = get_pronoun(uid)
    text = premium_gate_text(feature, pn)
    kb = premium_gate_kb()
    # an Update from a button tap has no .message — edit the button's message
    if (not edit and getattr(update_or_q, "message", None) is None
            and getattr(update_or_q, "callback_query", None) is not None):
        update_or_q, edit = update_or_q.callback_query, True
    if edit:
        await update_or_q.edit_message_text(text, parse_mode="HTML",
                                            reply_markup=kb)
    else:
        await update_or_q.message.reply_text(text, parse_mode="HTML",
                                             reply_markup=kb)


def _plans_text(uid, pn):
    tier = db.get_tier(uid)
    b = db.get_broker(uid) or {}
    cur = " ← <b>gói hiện tại</b>" if True else ""
    lines = ["💎 <b>NÂNG CẤP PREMIUM</b>\n"]
    # Free
    mark = " ✅ <i>(đang dùng)</i>" if tier == "free" else ""
    lines.append(
        f"🆓 <b>Free</b>{mark}\n"
        f"• Không giới hạn số tin\n"
        f"• Quản lý tin/khách cơ bản\n"
        f"• Chọn tin thủ công cho khách\n"
        f"• Viết bài Việt + Anh\n"
        f"• Nhắc follow-up\n"
    )
    # Pro
    mark = " ✅ <i>(đang dùng)</i>" if tier == "pro" else ""
    exp = ""
    if tier == "pro" and b.get("tier_expires_at"):
        exp = f" (hết hạn {vntime.fmt(b['tier_expires_at'], '%d/%m')})"
    lines.append(
        f"\n💎 <b>Pro — 99k/tháng</b>{mark}{exp}\n"
        f"• Auto-match tin cho khách\n"
        f"• Tìm kiếm bằng ngôn ngữ tự nhiên\n"
        f"• Viết bài 5 ngôn ngữ\n"
        f"• Lịch xem, mẫu tin nhắn, hoa hồng\n"
    )
    # Max
    mark = " ✅ <i>(đang dùng)</i>" if tier == "max" else ""
    exp = ""
    if tier == "max" and b.get("tier_expires_at"):
        exp = f" (hết hạn {vntime.fmt(b['tier_expires_at'], '%d/%m')})"
    lines.append(
        f"\n💎💎 <b>Max — 199k/tháng</b>{mark}{exp}\n"
        f"• Tất cả của Pro\n"
        f"• Match liên broker\n"
        f"• Thống kê chi tiết\n"
    )
    lines.append(
        f"\n💳 <b>Chuyển khoản tới:</b>\n"
        f"🏦 {_html.escape(config.PAYMENT_BANK)}\n"
        f"📱 Momo: {_html.escape(config.PAYMENT_MOMO)}\n"
        f"Nội dung: <code>{uid}</code>\n\n"
        f"Chuyển xong bấm nút bên dưới nhé 👇"
    )
    _ = cur
    return "\n".join(lines)


def _plans_kb(uid):
    tier = db.get_tier(uid)
    kb = []
    if tier == "free":
        kb.append([InlineKeyboardButton("💎 Đăng ký Pro (99k)",
                                        callback_data="premium:want:pro")])
        kb.append([InlineKeyboardButton("💎💎 Đăng ký Max (199k)",
                                        callback_data="premium:want:max")])
    elif tier == "pro":
        kb.append([InlineKeyboardButton("💎💎 Nâng lên Max (199k)",
                                        callback_data="premium:want:max")])
    kb.append([InlineKeyboardButton("✅ Tôi đã chuyển khoản",
                                    callback_data="premium:paid")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    return InlineKeyboardMarkup(kb)


async def cmd_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/premium — show tier plans and upgrade instructions."""
    uid = update.effective_user.id
    db.get_or_create_broker(uid, update.effective_user.username,
                            update.effective_user.full_name)
    pn = get_pronoun(uid)
    await natural_delay(update)
    text = _plans_text(uid, pn)
    kb = _plans_kb(uid)
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def premium_plans_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    await q.edit_message_text(
        _plans_text(uid, pn), parse_mode="HTML",
        reply_markup=_plans_kb(uid))


async def premium_want_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broker picked a tier — remember it for the pending request."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    tier = q.data.rsplit(":", 1)[-1]
    if tier not in ("pro", "max"):
        return
    ctx.user_data["wanted_tier"] = tier
    pn = get_pronoun(uid)
    tlabel = TIER_LABEL.get(tier, tier)
    await q.edit_message_text(
        f"{pn.capitalize()} chọn gói <b>{tlabel}</b> nhé 💎\n\n"
        f"💳 Chuyển khoản tới:\n"
        f"🏦 {_html.escape(config.PAYMENT_BANK)}\n"
        f"📱 Momo: {_html.escape(config.PAYMENT_MOMO)}\n"
        f"Nội dung: <code>{uid}</code>\n\n"
        f"Chuyển xong bấm nút bên dưới, em kích hoạt ngay ạ 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tôi đã chuyển khoản",
                                  callback_data=f"premium:paid:{tier}")],
            [InlineKeyboardButton("⬅️ Xem lại các gói",
                                  callback_data="premium:plans")],
        ]))


async def premium_paid_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broker says they transferred — create pending request, notify admin."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    # The chosen tier travels in the button itself (premium:paid:<tier>) so
    # it survives a bot restart; user_data is only a fallback for buttons
    # sent before this change.
    parts = (q.data or "").split(":")
    tier = parts[2] if len(parts) > 2 else ctx.user_data.get("wanted_tier",
                                                              "pro")
    if tier not in ("pro", "max"):
        tier = "pro"
    existing = db.get_pending_premium_request(uid)
    if existing:
        await q.edit_message_text(
            f"Em đã nhận yêu cầu gói <b>{TIER_LABEL.get(existing['tier_requested'])}</b>"
            f" rồi ạ, đang chờ duyệt. {pn.capitalize()} đợi em chút nhé 😊",
            parse_mode="HTML", reply_markup=MENU_KB)
        return
    rid = db.create_premium_request(uid, tier_requested=tier)
    # notify admin
    broker = db.get_broker(uid) or {}
    uname = f"@{broker.get('username')}" if broker.get("username") else str(uid)
    dname = broker.get("display_name") or broker.get("name") or ""
    if config.ADMIN_TELEGRAM_ID:
        try:
            await ctx.bot.send_message(
                config.ADMIN_TELEGRAM_ID,
                f"💰 <b>Yêu cầu premium mới</b>\n\n"
                f"👤 {uname} {('(' + dname + ')') if dname else ''}\n"
                f"🆔 <code>{uid}</code>\n"
                f"📦 Gói: <b>{TIER_LABEL.get(tier)}</b>\n"
                f"🔑 Request: <code>{rid}</code>\n\n"
                f"Duyệt: <code>/approve {uid} {tier}</code>",
                parse_mode="HTML")
        except Exception:
            pass
    ctx.user_data.pop("wanted_tier", None)
    await q.edit_message_text(
        f"Em đã ghi nhận rồi ạ ✅\n\n"
        f"Gói <b>{TIER_LABEL.get(tier)}</b> sẽ được kích hoạt ngay sau khi"
        f" em xác nhận chuyển khoản. {pn.capitalize()} đợi em chút nhé 😊",
        parse_mode="HTML", reply_markup=MENU_KB)


async def cmd_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/approve <telegram_id> <pro|max> — admin activates a tier (30 days)."""
    uid = update.effective_user.id
    if not config.ADMIN_TELEGRAM_ID or uid != config.ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Lệnh này chỉ dành cho admin ạ 😊")
        return
    args = (ctx.args or [])
    if len(args) < 2:
        pending = db.list_pending_premium_requests()
        if not pending:
            await update.message.reply_text(
                "Cú pháp: /approve &lt;telegram_id&gt; &lt;pro|max&gt;",
                parse_mode="HTML")
            return
        lines = ["⏳ <b>Yêu cầu đang chờ:</b>"]
        for r in pending[:10]:
            lines.append(
                f"• <code>{r['broker_id']}</code> —"
                f" {TIER_LABEL.get(r['tier_requested'])}"
                f" (<code>/approve {r['broker_id']}"
                f" {r['tier_requested']}</code>)")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("ID không hợp lệ.")
        return
    tier = args[1].lower()
    if tier not in ("pro", "max"):
        await update.message.reply_text("Gói phải là pro hoặc max.")
        return
    broker = db.get_broker(target)
    if not broker:
        await update.message.reply_text("Không tìm thấy broker này.")
        return
    # Grant exactly once, with the tier the ADMIN typed. Closing the pending
    # request used to grant a second time with the tier the broker asked
    # for, silently overriding the admin.
    req = db.get_pending_premium_request(target)
    if req:
        decided = db.decide_premium_request(req["id"], True, tier=tier,
                                            days=30)
        exp = decided.get("expires_at")
    else:
        exp = db.set_tier(target, tier, days=30)
    exp_txt = vntime.fmt(exp) if exp else "không giới hạn"
    try:
        await ctx.bot.send_message(
            target,
            f"🎉 Gói <b>{TIER_LABEL.get(tier)}</b> của anh đã được kích hoạt!\n"
            f"Dùng tới {exp_txt}. Dùng /premium để xem chi tiết nhé 😊",
            parse_mode="HTML")
    except Exception:
        pass
    await update.message.reply_text(
        f"Đã kích hoạt {TIER_LABEL.get(tier)} cho {target}"
        f" (hết hạn {exp_txt}) ✅")
