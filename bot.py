"""TrueNest Assistant — Telegram bot "Linh" for broker listing management.

Thin orchestrator: menu/start/help, onboarding, contacts, central routers
(on_text, on_callback), and main(). Feature logic lives in feat_* modules.

Run:  TELEGRAM_BOT_TOKEN=... python bot.py
"""
import asyncio
import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import db
import parser as listing_parser
from normalize import normalize_phone

# Feature modules
import feat_intake
import feat_listings
import feat_write
import feat_clients
import feat_match
import feat_metrics
import feat_viewings
import feat_templates
import feat_refresh
import feat_stale
import feat_deals
import feat_evening
import feat_payment
import feat_notify
import feat_premium
import feat_referral
import feat_sendclient
import hints
from utils import (
    MENU_KB, STATUS_EMOJI, STATUS_LABEL, LIST_FILTERS,
    CLIENT_STATUS_EMOJI, CLIENT_STATUS_LABEL,
    completeness_score, freshness_badge, get_pronoun,
    profile_score_text,
    rel_time, parse_listing_cb,
    _buffers, COLLECT_WINDOW,
    natural_delay, react_heart, maybe_send_hint,
    fmt_price, listing_line, _confirm_summary,
    get_forward_source, strip_forward_noise,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("linh")

HELP_TEXT = (
    "📖 <b>HƯỚNG DẪN SỬ DỤNG</b>\n\n"
    "📝 <b>Nhập căn cho thuê mới:</b>\n"
    "- Thêm căn mới vào kho tin của anh\n"
    "- 2 cách: viết từ đầu (em hỏi từng bước) hoặc nhập từ tin có sẵn (forward/paste bài FB)\n"
    "- Em sẽ tóm tắt lại để anh xác nhận, thiếu gì em hỏi thêm (tối đa 2 câu)\n\n"
    "🏠 <b>Quản lý căn:</b>\n"
    "- Xem tất cả căn của anh\n"
    "- Lọc theo phòng ngủ, giá tiền, khu vực, trạng thái\n"
    "- Đánh dấu “đã cho thuê” / “còn trống” để em cập nhật\n"
    "- Xem / thêm / xóa ảnh ngay trong chi tiết từng tin\n"
    "- 💎 Gói Pro: gõ “cho xem tin 2PN dưới 15tr” để em tìm giúp\n\n"
    "👥 <b>Khách hàng:</b>\n"
    "- Lưu thông tin khách + nhu cầu tìm nhà\n"
    "- Theo dõi trạng thái: mới → đang xem → đã cọc → đã thuê\n"
    "- ⏰ Em tự nhắc khi 3+ ngày chưa liên lạc với khách\n"
    "- 💎 Gói Pro: em tự gợi ý tin phù hợp cho từng khách\n\n"
    "✍️ <b>Viết bài đăng từ căn đã có:</b>\n"
    "- Chọn 1 căn trong kho tin của anh\n"
    "- Em viết bài đăng FB hoàn chỉnh từ thông tin căn đó\n"
    "- Free: Việt, Anh\n"
    "- 💎 Gói Pro: thêm Hàn, Trung, Nga\n\n"
    "📅 <b>Lịch xem nhà</b> 💎:\n"
    "- Đặt lịch dẫn khách xem tin, em nhắc trước 1 tiếng\n"
    "- Sau buổi xem em hỏi feedback từng căn\n"
    "/viewings — xem lịch sắp tới\n\n"
    "💬 <b>Mẫu tin nhắn</b> 💎:\n"
    "- Mẫu trả lời khách nhanh, bấm là copy được ngay\n"
    "/templates — xem / thêm mẫu\n\n"
    "💰 <b>Hoa hồng</b> 💎:\n"
    "- Theo dõi deal đã chốt theo từng tháng\n"
    "/commission — báo cáo hoa hồng\n\n"
    "🤝 <b>Match liên broker</b> 💎💎:\n"
    "- Khách không khớp tin của anh? Em đăng lên nhóm môi giới\n"
    "- Broker khác có tin phù hợp sẽ phản hồi (ẩn danh)\n\n"
    "🔔 <b>Trợ lý thật sự:</b>\n"
    "- Sáng 8h: nhắc việc hôm nay | Trưa 12h: tổng kết buổi sáng\n"
    "- Tối 21h: tổng kết ngày + checklist mai\n"
    "- Nhắc feedback sau buổi xem, nhắc tin cũ cần cập nhật\n\n"
    "💎 <b>Premium:</b> /premium — xem các gói Pro (99k) và Max (199k)\n\n"
    "⌨️ <b>Lệnh nhanh:</b>\n"
    "/menu — mở menu chính\n"
    "/edit — sửa thông tin tin đã đăng\n"
    "/clients — danh sách khách hàng\n"
    "/premium — nâng cấp gói\n"
    "/help — xem hướng dẫn này\n"
    "/contacts — xem / sửa thông tin liên hệ\n"
    "/phone — đổi SĐT nhanh"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await feat_intake.release_pending_steps(ctx, u.id, update.effective_chat.id)
    existing = db.get_broker(u.id)
    broker = db.get_or_create_broker(u.id, u.username, u.full_name)
    # Referral: /start ref_<inviter_id> from an invite link
    inviter_id = feat_referral.parse_start_referral(update, ctx)
    if inviter_id and not existing:
        await feat_referral.announce_inviter(
            ctx, inviter_id, u.full_name or u.username or "Bạn mới")
    # New broker → simplified 3-step onboarding (under 30 seconds)
    if not existing:
        await _onboard2_start(update, ctx)
        return
    pn = get_pronoun(u.id, broker)
    await natural_delay(update)
    await update.message.reply_text(
        f"Chào {pn}! Em là {config.BOT_NAME} 🏠\n\n"
        "Em là trợ lý quản lý tin cho thuê dành cho môi giới Đà Nẵng — "
        "không phải bot bấm nút, mà như trợ lý thật sự.\n\n"
        f"Em giúp {pn}:\n"
        "📝 Lưu tin — gửi text + ảnh như đăng group FB, em tự bóc thông tin\n"
        "👥 Quản lý khách — theo dõi, nhắc follow-up, lưu feedback từng căn\n"
        "⏰ Nhắc việc — sáng/trưa/tối em báo cáo, không để sót việc nào\n"
        "✍️ Viết bài FB đẹp — Việt/Anh free, thêm Hàn/Trung/Nga ở gói Pro\n\n"
        "🆓 Dùng free thoải mái, không giới hạn số tin.\n"
        "💎 Gói Pro 99k/tháng: mở khóa tính năng thông minh.\n\n"
        f"👉 Để bắt đầu, {pn} cứ gửi tin đầu tiên cho em nhé! (text kèm ảnh)\n\n"
        "Gõ /menu để mở menu, /help để xem hướng dẫn, /premium để nâng cấp.",
        reply_markup=MENU_KB,
    )
    # onboarding: collect phone, then pronoun + display name (once each)
    if not broker.get("phone"):
        ctx.user_data["onboarding"] = {"step": "phone"}
        await asyncio.sleep(0.8)
        await update.message.reply_text(
            f"Cho em xin SĐT của {pn} để có khách em liên hệ cho dễ nhé? 📱",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Bỏ qua", callback_data="onboard:skip_phone")]]),
        )
    elif not broker.get("pronoun"):
        await _onboard_ask_pronoun_msg(update, ctx)


# ---------------------------------------------------------------- simplified onboarding (new brokers, 3 steps)

async def _onboard2_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 1: welcome + pronoun choice. Only for brand-new brokers."""
    await natural_delay(update)
    await update.message.reply_text(
        "👋 Chào anh! Em là Linh, trợ lý quản lý tin cho thuê.\n\n"
        "Em giúp anh:\n"
        "📝 Lưu tin nhanh (gửi text/ảnh là xong)\n"
        "👥 Quản lý khách + nhắc follow-up\n"
        "🤝 Kết nối với môi giới khác khi cần\n\n"
        "Anh xưng hô với em là \"anh\" hay \"chị\" ạ?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Anh", callback_data="onboard2:pronoun:anh"),
            InlineKeyboardButton("Chị", callback_data="onboard2:pronoun:chi"),
        ]]),
    )


async def onboard2_pronoun_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 1 done → Step 2: ask for phone (skippable)."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pronoun = "chị" if q.data.rsplit(":", 1)[-1] == "chi" else "anh"
    db.update_broker(uid, pronoun=pronoun)
    ctx.user_data["onboarding2"] = {"step": "phone"}
    await q.edit_message_text(
        f"Rõ ạ! Số điện thoại của {pronoun} là gì?\n"
        "(để khách liên hệ khi cần — anh có thể bỏ qua)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭️ Bỏ qua", callback_data="onboard2:skip_phone"),
        ]]),
    )


async def onboard2_skip_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 2 skipped → Step 3: prompt first listing."""
    q = update.callback_query
    await q.answer()
    await _onboard2_finish(q, ctx, update.callback_query.from_user.id,
                           via_callback=True)


async def _onboard2_finish(update_or_q, ctx, uid, via_callback=False):
    """Step 3: score explainer + done → CTA to send first listing + show menu."""
    ctx.user_data.pop("onboarding2", None)
    broker = db.get_broker(uid) or {}
    pn = broker.get("pronoun") or "anh"
    text = (
        f"💎 {pn.capitalize()} biết không? Hồ sơ của {pn} có <b>điểm uy tín</b>.\n"
        f"Điểm càng cao → càng được ưu tiên giới thiệu "
        f"<b>khách hàng thật</b> sau này.\n\n"
        f"Cách tăng điểm:\n"
        f"✅ Điền đầy đủ thông tin tin đăng\n"
        f"✅ Cập nhật tình trạng tin thường xuyên\n\n"
        f"Xong! {pn.capitalize()} gửi tin đầu tiên cho em nhé —\n"
        "cứ gửi text + ảnh như đăng group là được 📸"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Gửi tin đầu tiên",
                              callback_data="menu:new")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ])
    if via_callback:
        await update_or_q.edit_message_text(text, reply_markup=kb,
                                            parse_mode="HTML")
    else:
        await update_or_q.message.reply_text(text, reply_markup=kb,
                                             parse_mode="HTML")


async def _handle_onboarding2(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                              ob2: dict, text: str):
    """Step 2: collect phone number (typed)."""
    uid = update.effective_user.id
    broker = db.get_broker(uid) or {}
    pn = broker.get("pronoun") or "anh"
    t = text.strip().lower()
    if t in ("bỏ qua", "bo qua", "skip"):
        await _onboard2_finish(update, ctx, uid)
        return
    phones = normalize_phone(text)
    if not phones:
        await update.message.reply_text(
            "SĐT này chưa đúng định dạng, anh kiểm tra lại giúp em nhé? 📱\n"
            "(10 số, VD: 0905123456)")
        return
    db.set_broker_phone(uid, phones[0])
    if not broker.get("zalo"):
        db.update_broker(uid, zalo=phones[0])
    await natural_delay(update)
    await update.message.reply_text("Em lưu SĐT rồi nhé ✓")
    await _onboard2_finish(update, ctx, uid)


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await feat_intake.release_pending_steps(ctx, u.id, update.effective_chat.id,
                                            keep_guided=True)
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    pn = get_pronoun(u.id)
    await update.message.reply_text(f"{pn.capitalize()} cần gì ạ?",
                                    reply_markup=MENU_KB)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await natural_delay(update)
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")]]),
    )


async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pn = get_pronoun(q.from_user.id)
    await q.edit_message_text(f"{pn.capitalize()} cần gì ạ?", reply_markup=MENU_KB)


async def show_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await natural_delay(update)
    await q.edit_message_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")]]),
    )


async def show_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await natural_delay(update)
    uid = q.from_user.id
    pn = get_pronoun(uid)
    await q.edit_message_text(
        profile_score_text(uid, pn),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")]]),
    )


# ---------------------------------------------------------------- onboarding & contacts

def _pronoun_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Anh", callback_data="onboard:pronoun:anh"),
        InlineKeyboardButton("Chị", callback_data="onboard:pronoun:chi"),
    ]])


def _dname_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Dùng tên Telegram",
                              callback_data="onboard:dname:tg")],
        [InlineKeyboardButton("Tên khác",
                              callback_data="onboard:dname:custom")],
    ])


def _dname_question(pn, broker):
    username = (broker or {}).get("username")
    uname = f"@{username}" if username else "tên Telegram"
    return (f"Em gọi {pn} bằng tên Telegram ({uname}) nhé, "
            f"hay {pn} muốn tên khác?")


async def _onboard_ask_pronoun_msg(update: Update,
                                   ctx: ContextTypes.DEFAULT_TYPE):
    """Pronoun question via a normal message (from /start or typed flow)."""
    ctx.user_data["onboarding"] = {"step": "pronoun"}
    await asyncio.sleep(0.8)
    await update.message.reply_text(
        "Anh muốn em gọi là anh hay chị ạ?",
        reply_markup=_pronoun_kb())


async def _handle_onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             ob: dict, text: str):
    """Collect broker phone, then pronoun + display name (once each)."""
    uid = update.effective_user.id
    step = ob.get("step")

    if step == "phone":
        if text.strip().lower() in ("bỏ qua", "bo qua", "skip"):
            await _onboard_ask_pronoun_msg(update, ctx)
            return
        phones = normalize_phone(text)
        if not phones:
            await update.message.reply_text(
                "SĐT này chưa đúng định dạng, anh kiểm tra lại giúp em nhé? 📱\n"
                "(10 số, VD: 0905123456)")
            return
        db.set_broker_phone(uid, phones[0])
        # Zalo defaults to phone when unset
        if not (db.get_broker(uid) or {}).get("zalo"):
            db.update_broker(uid, zalo=phones[0])
        await natural_delay(update)
        await update.message.reply_text(
            "Em lưu SĐT rồi nhé ✓ Từ giờ tin nào em cũng tự điền SĐT này cho anh.")
        await _onboard_ask_pronoun_msg(update, ctx)

    elif step == "pronoun":
        t = text.strip().lower()
        if t in ("anh", "a"):
            pronoun = "anh"
        elif t in ("chị", "chi", "c"):
            pronoun = "chị"
        else:
            await update.message.reply_text(
                "Anh chọn giúp em một trong hai nút bên dưới nhé 👆",
                reply_markup=_pronoun_kb())
            return
        db.update_broker(uid, pronoun=pronoun)
        ctx.user_data["onboarding"] = {"step": "dname"}
        broker = db.get_broker(uid)
        await update.message.reply_text(
            _dname_question(pronoun, broker), reply_markup=_dname_kb())

    elif step == "dname":
        # typed directly (without tapping the buttons) = custom name
        name = text.strip()[:50]
        await _onboard_finish_name(update, ctx, uid, name, via_callback=False)


async def _onboard_finish_name(update_or_q, ctx, uid, name, via_callback):
    broker = db.get_broker(uid) or {}
    pn = broker.get("pronoun") or "anh"
    if name:
        db.update_broker(uid, display_name=name)
        greet = f"Dạ, từ giờ em gọi {pn} là {name} nhé 😊"
    else:
        greet = f"Dạ ok {pn} 😊"
    ctx.user_data.pop("onboarding", None)
    text = f"{greet} {pn.capitalize()} cần gì cứ bảo em."
    if via_callback:
        await update_or_q.edit_message_text(text, reply_markup=MENU_KB)
    else:
        await natural_delay(update_or_q)
        await update_or_q.message.reply_text(text, reply_markup=MENU_KB)


async def onboard_skip_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["onboarding"] = {"step": "pronoun"}
    await q.edit_message_text(
        "Dạ ok anh, để sau cũng được ạ 😊\n\n"
        "Anh muốn em gọi là anh hay chị ạ?",
        reply_markup=_pronoun_kb())


async def onboard_pronoun_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pronoun = "chị" if q.data.rsplit(":", 1)[-1] == "chi" else "anh"
    db.update_broker(uid, pronoun=pronoun)
    ctx.user_data["onboarding"] = {"step": "dname"}
    broker = db.get_broker(uid)
    await q.edit_message_text(
        _dname_question(pronoun, broker), reply_markup=_dname_kb())


async def onboard_dname_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    choice = q.data.rsplit(":", 1)[-1]  # tg | custom
    broker = db.get_broker(uid) or {}
    pn = broker.get("pronoun") or "anh"
    if choice == "tg":
        username = broker.get("username")
        dname = f"@{username}" if username else (broker.get("display_name") or "")
        await _onboard_finish_name(q, ctx, uid, dname, via_callback=True)
    else:
        ctx.user_data["onboarding"] = {"step": "dname"}
        await q.edit_message_text(f"Vậy {pn} muốn em gọi là gì ạ?")


def _contacts_text(broker: dict) -> str:
    import html as _html
    name = _html.escape(broker.get("name") or "—")
    phone = _html.escape(broker.get("phone") or "—")
    zalo_raw = broker.get("zalo")
    if zalo_raw:
        zalo = _html.escape(zalo_raw)
        zalo_note = ""
    elif broker.get("phone"):
        zalo = _html.escape(broker.get("phone"))
        zalo_note = " (giống SĐT)"
    else:
        zalo = "—"
        zalo_note = ""
    fb = _html.escape(broker.get("facebook") or "—")
    pn = (broker.get("pronoun") or "anh").upper()
    return (
        f"📇 <b>THÔNG TIN CỦA {pn}</b>\n\n"
        f"👤 Tên: {name}\n"
        f"📱 SĐT: {phone}\n"
        f"💬 Zalo: {zalo}{zalo_note}\n"
        f"📘 Facebook: {fb}\n\n"
        "Bấm vào từng mục để sửa nhé 👇"
    )


def _contacts_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Sửa tên", callback_data="contact:edit:name")],
        [InlineKeyboardButton("📱 Sửa SĐT", callback_data="contact:edit:phone")],
        [InlineKeyboardButton("💬 Sửa Zalo", callback_data="contact:edit:zalo")],
        [InlineKeyboardButton("📘 Sửa Facebook", callback_data="contact:edit:facebook")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ])


async def cmd_contacts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    broker = db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    await update.message.reply_text(
        _contacts_text(broker),
        parse_mode="HTML",
        reply_markup=_contacts_kb(),
    )


async def cmd_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quick phone change (shortcut; full profile lives in /contacts)."""
    u = update.effective_user
    broker = db.get_or_create_broker(u.id, u.username, u.full_name)
    ctx.user_data["editing_contact"] = "phone"
    await natural_delay(update)
    if broker.get("phone"):
        await update.message.reply_text(
            f"SĐT hiện tại của anh là {broker['phone']}. Anh muốn đổi thành số nào ạ? 📱")
    else:
        await update.message.reply_text("Anh chưa có SĐT nào. Anh cho em xin SĐT nhé? 📱")


async def contact_edit_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.rsplit(":", 1)[-1]
    prompts = {
        "name": "Anh muốn đổi tên thành gì ạ?",
        "phone": "SĐT mới của anh là số nào ạ? 📱",
        "zalo": "Số Zalo mới của anh là gì ạ?\n(Gõ “xóa” để Zalo dùng lại SĐT)",
        "facebook": "Anh gửi link Facebook hoặc tên FB giúp em nhé? 📘",
    }
    ctx.user_data["editing_contact"] = field
    await q.edit_message_text(prompts.get(field, "Anh nhập giá trị mới nhé?"))


async def _handle_contact_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                               field: str, text: str):
    uid = update.effective_user.id
    text = (text or "").strip()

    if field == "phone":
        phones = normalize_phone(text)
        if not phones:
            await update.message.reply_text(
                "SĐT này chưa đúng định dạng, anh kiểm tra lại giúp em nhé? 📱")
            return  # stay in edit mode
        db.set_broker_phone(uid, phones[0])
        done = f"Đã đổi SĐT thành {phones[0]} ✓"
    elif field == "zalo":
        if text.lower() in ("xóa", "xoa", "xoa zalo"):
            db.update_broker(uid, zalo=None)
            done = "Đã đặt Zalo = SĐT ✓"
        else:
            phones = normalize_phone(text)
            if not phones:
                await update.message.reply_text(
                    "Số Zalo này chưa đúng định dạng, anh kiểm tra lại giúp em nhé? 📱")
                return
            db.update_broker(uid, zalo=phones[0])
            done = f"Đã đổi Zalo thành {phones[0]} ✓"
    elif field == "name":
        if not text:
            await update.message.reply_text("Anh nhập tên giúp em nhé? 😊")
            return
        db.update_broker(uid, name=text[:50])
        done = f"Đã đổi tên thành {text[:50]} ✓"
    elif field == "facebook":
        if not text:
            await update.message.reply_text("Anh gửi link hoặc tên Facebook giúp em nhé? 📘")
            return
        db.update_broker(uid, facebook=text[:200])
        done = "Đã cập nhật Facebook ✓"
    else:
        ctx.user_data.pop("editing_contact", None)
        return

    ctx.user_data.pop("editing_contact", None)
    broker = db.get_broker(uid)
    await natural_delay(update)
    await update.message.reply_text(done)
    await update.message.reply_text(
        _contacts_text(broker),
        parse_mode="HTML",
        reply_markup=_contacts_kb(),
    )


# ---------------------------------------------------------------- intake

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await react_heart(update.message)
    uid = update.effective_user.id
    text = update.message.text or ""

    # 0-. anti-spam: muted or banned users are blocked entirely
    blocked, block_msg = db.is_muted_or_banned(uid)
    if blocked:
        await update.message.reply_text(block_msg, reply_markup=MENU_KB)
        return

    # 0. onboarding (phone/name collection) takes priority
    ob = ctx.user_data.get("onboarding")
    if ob:
        await _handle_onboarding(update, ctx, ob, text)
        return

    # 0a. simplified onboarding for new brokers (3 steps)
    ob2 = ctx.user_data.get("onboarding2")
    if ob2:
        await _handle_onboarding2(update, ctx, ob2, text)
        return

    # 0b. editing a contact field via /contacts or /phone
    ec = ctx.user_data.get("editing_contact")
    if ec:
        await _handle_contact_edit(update, ctx, ec, text)
        return

    # 0b2. forwarded text → always a NEW listing import, bypasses all
    # state routing (confirming/awaiting/guided). Each forward = 1 listing.
    # Processed immediately, no 5s wait.
    fwd_here = get_forward_source(update.message)
    if fwd_here:
        await feat_intake.handle_forward_text(
            update, ctx, uid, text, fwd_here)
        return

    # 0b3. editing a saved FB post? typed text = the edited version.
    ep = ctx.user_data.get("editing_post")
    if ep:
        await feat_write.handle_edit_post(update, ctx, ep, text)
        return

    # 0c. confirming a draft summary? typed text = correction (or "đúng rồi")
    confirming = ctx.user_data.get("confirming")
    if confirming:
        await feat_intake._handle_confirm_correction(update, ctx, confirming, text)
        return

    # 1. answering a missing-field question?
    awaiting = ctx.user_data.get("awaiting")
    if awaiting:
        await feat_intake._handle_answer(update, ctx, awaiting, text)
        return

    # 1b. answering an edit-field prompt?
    editing = ctx.user_data.get("editing")
    if editing:
        await feat_listings._handle_edit_answer(update, ctx, editing, text)
        return

    # 1b2. adding a new client step-by-step?
    addc = ctx.user_data.get("adding_client")
    if addc:
        await feat_clients._handle_add_client(update, ctx, addc, text)
        return

    # 1b3. adding a note to a client?
    addn = ctx.user_data.get("adding_note")
    if addn:
        await feat_clients._handle_add_note(update, ctx, addn, text)
        return

    # 1b4. editing a client field?
    ced = ctx.user_data.get("editing_client")
    if ced:
        await feat_clients._handle_edit_client(update, ctx, ced, text)
        return

    # 1b5. entering a deal commission?
    ad = ctx.user_data.get("adding_deal")
    if ad:
        # False = not a commission answer; the step was released and the
        # message continues through normal routing below.
        if await feat_deals._handle_add_deal(update, ctx, ad, text):
            return

    # 1b6. entering a new price for an old-listing refresh?
    rd = ctx.user_data.get("refresh_discount")
    if rd:
        await feat_refresh._handle_refresh_discount(update, ctx, rd, text)
        return

    # 1b7. adding a custom message template?
    at = ctx.user_data.get("adding_template")
    if at:
        await feat_templates._handle_add_template(update, ctx, at, text)
        return

    # 1b8. relaying a message to another broker (cross-broker match)?
    rl = ctx.user_data.get("relaying")
    if rl:
        await feat_match._handle_relay_message(update, ctx, rl, text)
        return

    # 1b8b. typing extra requirements for a client (after paste confirm)?
    er = ctx.user_data.get("client_extra_req")
    if er:
        await feat_clients._handle_extra_req(update, ctx, er, text)
        return

    # 1b9. entering post-viewing feedback?
    vf = ctx.user_data.get("viewing_feedback")
    if vf:
        await feat_viewings._handle_viewing_feedback(update, ctx, vf, text)
        return

    # 1b9b. entering viewing datetime after client chose a listing?
    s2c = ctx.user_data.get("send2client")
    if s2c and s2c.get("awaiting_dt"):
        if await feat_sendclient.handle_s2c_datetime(update, ctx, s2c, text):
            return

    # 1b10. guided listing intake? (False during photo step -> buffer routing)
    gd = ctx.user_data.get("guided")
    if gd:
        if await feat_intake.handle_guided_text(update, ctx, gd, text):
            return

    # 1c. adding photos to a listing? text is not expected here
    if ctx.user_data.get("adding_photos"):
        await update.message.reply_text(
            "Anh gửi ảnh giúp em nhé 📥 (hoặc gõ /huy để hủy)")
        return

    # 1d. choosing photos to delete by number?
    pd = ctx.user_data.get("photo_delete")
    if pd:
        await feat_listings._handle_photo_delete_answer(update, ctx, pd, text)
        return

    # 2. part of an active collection buffer? (manual input only;
    # forwards are handled at 0b2 and never reach the buffer)
    buf = _buffers.get(uid)
    if buf and buf.get("guided"):
        # Guided photo step: its buffer only collects photos ("Đủ rồi"
        # keeps buf["photos"] and nothing else), so text put there would
        # silently vanish. The user has one buffer slot, so the text cannot
        # start a second listing either -- say so instead of eating it.
        await update.message.reply_text(
            "Bước này em chỉ nhận ảnh 📸 Anh gửi ảnh, hoặc bấm "
            "“Không có ảnh, tiếp tục”. Nếu muốn nhập một tin khác thì gõ "
            "/huy rồi gửi lại tin đó giúp em nhé.")
        return
    if buf:
        buf["texts"].append(text)
        buf["deadline"] = time.time() + COLLECT_WINDOW
        feat_intake._wake_flush(uid, ctx, buf)
        return

    # 4. natural-language listing query? (not a new listing) — Pro feature
    if listing_parser.looks_like_query(text):
        if not feat_premium.requires_tier(uid, "natural_query"):
            await natural_delay(update)
            await feat_premium.send_gate(update, "natural_query", uid)
            return
        await feat_listings._handle_query(update, ctx, uid, text)
        return

    # 5. otherwise treat as a fresh listing
    # spam/relevance check first
    is_rel, reason = listing_parser.is_rental_relevant(text)
    if not is_rel:
        # 3rd spam submission in 1h → automatic strike
        action = db.maybe_strike_for_repeated_event(uid, "spam_content")
        await natural_delay(update)
        if action:
            await update.message.reply_text(
                db.spam_violation_message(action, "spam_content", text),
                reply_markup=MENU_KB,
            )
        else:
            await update.message.reply_text(
                f"Tin này em thấy {reason}, không giống tin cho thuê nhà 😅\n"
                f"Anh gửi tin cho thuê giúp em nhé!",
                reply_markup=MENU_KB,
            )
        return
    # duplicate-text check: same raw text submitted repeatedly → spam
    if db.count_recent_identical_texts(uid, text, hours=1) >= 2:
        # 3rd identical submission in 1h → automatic strike
        action = db.maybe_strike_for_repeated_event(uid, "duplicate")
        await natural_delay(update)
        if action:
            await update.message.reply_text(
                db.spam_violation_message(action, "duplicate"),
                reply_markup=MENU_KB,
            )
        else:
            await update.message.reply_text(
                "Tin này anh gửi trùng rồi 😅 Em bỏ qua nhé!",
                reply_markup=MENU_KB,
            )
        return
    # Tier-based rate limit
    tier = db.get_tier(uid)
    hourly_limit = config.RATE_LIMITS_PER_HOUR.get(tier, 10)
    recent_count = db.count_recent_listings(uid, hours=1)
    if recent_count >= hourly_limit:
        # rate-limit breach → immediate strike (fully automatic)
        action = db.record_spam_violation(uid, "rate_limit")
        await natural_delay(update)
        await update.message.reply_text(
            db.spam_violation_message(
                action, "rate_limit",
                f"Gói {tier} tối đa {hourly_limit} tin/giờ,"
                f" anh đã gửi {recent_count} tin"),
            reply_markup=MENU_KB,
        )
        return
    _buffers[uid] = {"texts": [text], "photos": [],
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": update.effective_chat.id,
                     "forward_source": get_forward_source(update.message)}
    fwd = _buffers[uid]["forward_source"]
    if fwd:
        # clean channel promo footers from forwarded text
        _buffers[uid]["texts"] = [strip_forward_noise(text)]
    fwd_note = f" (forward từ {fwd})" if fwd else ""
    await update.message.reply_text(
        f"Em nhận text{fwd_note} rồi! Đang đợi ảnh... 📥\n"
        "(anh gửi ảnh trong 5s nhé, không có ảnh cũng được)")
    asyncio.create_task(feat_intake._flush_after(uid, ctx))


async def _maybe_show_hint(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                         menu_data: str, handler_coro):
    """Show first-time hint for a menu feature, or run handler directly.

    Returns True if hint was shown (handler NOT run yet).
    The hint has [Bắt đầu →] which marks seen and re-dispatches
    to the original menu_data, and [Để sau] which goes back to menu.
    """
    q = update.callback_query
    uid = q.from_user.id
    hint_key = hints.MENU_HINT_MAP.get(menu_data)
    if hint_key and hints.should_show_hint(uid, hint_key):
        text = hints.get_hint_text(hint_key)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bắt đầu →",
                                  callback_data=f"hint:go:{menu_data}")],
            [InlineKeyboardButton("Để sau", callback_data="hint:skip")],
        ])
        # remember which hint is pending so hint:skip can mark it seen
        ctx.user_data["pending_hint_key"] = hint_key
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        return True
    await handler_coro()
    return False


class _Override:
    """Read-only view of a (frozen) PTB object with some attributes
    replaced; everything else, including bound methods such as answer()
    and edit_message_text(), is delegated to the wrapped object."""

    def __init__(self, inner, **overrides):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        ov = object.__getattribute__(self, "_overrides")
        if name in ov:
            return ov[name]
        return getattr(object.__getattribute__(self, "_inner"), name)


def _with_callback_data(update, data):
    """The same update, but its callback_query.data reads `data`."""
    q = _Override(update.callback_query, data=data)
    return _Override(update, callback_query=q)


# Buttons that leave or cancel whatever step the user was in. Tapping one
# releases every pending step (utils.clear_pending_steps, via
# feat_intake.release_pending_steps which also offers unsaved drafts back),
# so a later typed
# message is never swallowed by a step the user already walked away from.
# Opening a client card (the catch-all "client:<id>:..." route, the target
# of most "Hủy"/"Quay lại" buttons in client flows) does the same, below.
_LEAVE_STEP_BUTTONS = frozenset({
    "clients:cancel", "deal:skip_auto", "mresp:cancel", "rf:skip:", "vw:no",
})
_LEAVE_STEP_PREFIXES = (
    "menu:", "cms:", "editcancel:", "mpick:cancel:", "tpl:list:",
    "clients:list:", "vw:fbcancel:", "writeview:",
)


def _leaves_pending_steps(data):
    return data in _LEAVE_STEP_BUTTONS or data.startswith(_LEAVE_STEP_PREFIXES)


async def _release_steps(update, ctx, keep_guided):
    q = update.callback_query
    chat = getattr(update, "effective_chat", None)
    await feat_intake.release_pending_steps(
        ctx, q.from_user.id, chat.id if chat else q.from_user.id,
        keep_guided=keep_guided)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if _leaves_pending_steps(data):
        # plain navigation keeps a guided intake; "new listing" restarts it
        await _release_steps(update, ctx, keep_guided=(data != "menu:new"))
    # hint proceed/skip — handle before normal dispatch
    if data.startswith("hint:go:"):
        original = data[len("hint:go:"):]
        hint_key = hints.MENU_HINT_MAP.get(original)
        if hint_key:
            hints.mark_seen(update.callback_query.from_user.id, hint_key)
        ctx.user_data.pop("pending_hint_key", None)
        # re-dispatch to the original menu action (hint now marked seen,
        # so it goes straight to the handler). PTB objects are frozen, so
        # the query cannot be rewritten in place — wrap it instead.
        await on_callback(_with_callback_data(update, original), ctx)
        return
    if data == "hint:skip":
        # user dismissed the hint — mark seen so we don't nag again
        pending = ctx.user_data.pop("pending_hint_key", None)
        if pending:
            hints.mark_seen(update.callback_query.from_user.id, pending)
        await show_menu(update, ctx)
        return
    if data == "menu:new":
        await feat_intake.on_new_listing_prompt(update, ctx)
    elif data.startswith("menu:list:"):
        await feat_listings.show_my_listings(update, ctx)
    elif data.startswith("flt:"):
        await feat_listings.show_filter_picker(update, ctx)
    elif data == "menu:write":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_write.on_write_post_prompt(update, ctx))
    elif data == "write:new":
        await feat_write.on_write_new(update, ctx)
    elif data.startswith("writeview:"):
        await feat_write.on_write_view(update, ctx)
    elif data.startswith("writecopy:"):
        await feat_write.on_write_copy(update, ctx)
    elif data.startswith("writeedit:"):
        await feat_write.on_write_edit_prompt(update, ctx)
    elif data.startswith("writeaddlang:"):
        await feat_write.on_write_add_lang(update, ctx)
    elif data.startswith("writegenlang:"):
        await feat_write.on_write_gen_lang(update, ctx)
    elif data.startswith("write:"):
        await feat_write.on_write_view(update, ctx)
    elif data.startswith("writelang:"):
        await feat_write.on_write_generate(update, ctx)
    elif data == "menu:help":
        await show_help(update, ctx)
    elif data == "menu:profile":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: show_profile(update, ctx))
    elif data == "menu:back":
        await show_menu(update, ctx)
    elif data == "premium:plans":
        await feat_premium.premium_plans_cb(update, ctx)
    elif data.startswith("premium:want:"):
        await feat_premium.premium_want_cb(update, ctx)
    elif data == "premium:paid" or data.startswith("premium:paid:"):
        await feat_premium.premium_paid_cb(update, ctx)
    elif data == "menu:clients":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_clients.show_clients(update, ctx))
    elif data == "menu:premium":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_premium.cmd_premium(update, ctx))
    elif data == "menu:match":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_match.match_requests_list(update, ctx))
    elif data == "menu:deals":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_deals.cmd_commission(update, ctx))
    elif data == "menu:templates":
        await _maybe_show_hint(
            update, ctx, data,
            lambda: feat_templates.tpl_list_cb(update, ctx))
    elif data == "stray:yes":
        await feat_intake.stray_confirm_yes(update, ctx)
    elif data == "stray:new":
        await feat_intake.stray_confirm_new(update, ctx)
    elif data == "buf:done":
        await feat_intake.buf_confirm_done(update, ctx)
    elif data == "buf:more":
        await feat_intake.buf_confirm_more(update, ctx)
    elif data == "guided:mode:free":
        await feat_intake.guided_mode_free(update, ctx)
    elif data == "guided:mode:guided":
        await feat_intake.guided_mode_guided(update, ctx)
    elif data.startswith("guided:amen:"):
        await feat_intake.guided_amen(update, ctx)
    elif data.startswith("guided:bset:"):
        await feat_intake.guided_bset(update, ctx)
    elif data == "guided:badd":
        await feat_intake.guided_badd(update, ctx)
    elif data == "guided:bback":
        await feat_intake.guided_bback(update, ctx)
    elif data.startswith("guided:sset:"):
        if data == "guided:sset:custom":
            await feat_intake.guided_sset_custom(update, ctx)
        else:
            await feat_intake.guided_sset(update, ctx)
    elif data == "guided:sback":
        await feat_intake.guided_sback(update, ctx)
    elif data.startswith("guided:wset:"):
        await feat_intake.guided_wset(update, ctx)
    elif data == "guided:wback":
        await feat_intake.guided_wback(update, ctx)
    elif data.startswith("guided:set:"):
        await feat_intake.guided_set(update, ctx)
    elif data == "guided:back":
        await feat_intake.guided_back(update, ctx)
    elif data == "guided:skip":
        await feat_intake.guided_skip(update, ctx)
    elif data == "guided:nophoto":
        await feat_intake.guided_no_photos(update, ctx)
    elif data == "menu:viewings":
        async def _viewings_flow():
            if not feat_premium.requires_tier(update.callback_query.from_user.id,
                                              "viewings"):
                await update.callback_query.answer()
                await feat_premium.send_gate(update.callback_query, "viewings",
                                             update.callback_query.from_user.id,
                                             edit=True)
            else:
                await feat_viewings.cmd_viewings_cb(update, ctx)
        await _maybe_show_hint(update, ctx, data, _viewings_flow)
    elif data.startswith("vw:"):
        act, payload = feat_viewings._parse_vw_cb(data)
        if act == "ok":
            await feat_viewings.vw_confirm(update, ctx)
        elif act == "no":
            await feat_viewings.vw_cancel(update, ctx)
        elif act == "del":
            await feat_viewings.vw_delete(update, ctx)
        elif act == "date":
            await feat_viewings.vw_pick_date(update, ctx)
        elif act == "time":
            await feat_viewings.vw_pick_time(update, ctx)
        elif act == "c":
            await feat_viewings.vw_from_client(update, ctx)
        elif act == "lc":
            await feat_viewings.vw_from_listing(update, ctx)
        elif act == "cc":
            await feat_viewings.vw_pick(update, ctx)
        elif act == "lpick":
            sub, _, rest = payload.partition(":")
            if sub == "toggle":
                await feat_viewings.vw_lpick_toggle(update, ctx, rest)
            elif sub == "done":
                await feat_viewings.vw_lpick_done(update, ctx)
            elif sub == "back":
                await feat_viewings.vw_lpick_back(update, ctx)
        elif act == "fb":
            await feat_viewings.vw_feedback_start(update, ctx)
        elif act == "fbcancel":
            await feat_viewings.vw_feedback_cancel(update, ctx)
    elif data.startswith("tpl:"):
        act, _ = feat_templates._parse_tpl_cb(data)
        if act == "list":
            await feat_templates.tpl_list_cb(update, ctx)
        elif act == "use":
            await feat_templates.tpl_use(update, ctx)
        elif act == "new":
            await feat_templates.tpl_new(update, ctx)
        elif act == "del":
            await feat_templates.tpl_delete(update, ctx)
    elif data.startswith("rf:"):
        if not feat_premium.requires_tier(update.callback_query.from_user.id,
                                          "refresh"):
            await update.callback_query.answer()
            await feat_premium.send_gate(update.callback_query, "refresh",
                                         update.callback_query.from_user.id,
                                         edit=True)
        else:
            await feat_refresh.rf_action(update, ctx)
    elif data.startswith("stale:"):
        await feat_stale.stale_action_cb(update, ctx)
    elif data.startswith("dup:"):
        await feat_intake.dup_action_cb(update, ctx)
    elif data.startswith("imgdup:"):
        await feat_intake.imgdup_action_cb(update, ctx)
    elif data.startswith("deal:"):
        rest = data[len("deal:"):]
        if rest == "new":
            await feat_deals.deal_new(update, ctx)
        elif rest.startswith("pick:"):
            await feat_deals.deal_pick(update, ctx)
        elif rest.startswith("mc:"):
            await feat_deals.deal_pick_client(update, ctx)
        elif rest.startswith("ml:"):
            await feat_deals.deal_pick_listing(update, ctx)
        elif rest == "skip_auto":
            await feat_deals.deal_skip_auto(update, ctx)
    elif data.startswith("cms:"):
        await feat_deals.cms_nav(update, ctx)
    elif data == "pay:receipt_yes":
        await feat_payment.receipt_yes_cb(update, ctx)
    elif data == "pay:receipt_no":
        await feat_payment.receipt_no_cb(update, ctx)
    elif data.startswith("pay:confirm:"):
        await feat_payment.pay_confirm_cb(update, ctx)
    elif data.startswith("pay:reject:"):
        await feat_payment.pay_reject_cb(update, ctx)
    elif data.startswith("clients:list:"):
        await feat_clients.show_clients(update, ctx)
    elif data == "clients:new":
        await feat_clients.client_add_start(update, ctx)
    elif data == "clients:cancel":
        await feat_clients.client_add_cancel(update, ctx)
    elif data.startswith("clients:addmode:"):
        await feat_clients.client_add_mode_cb(update, ctx)
    elif data.startswith("clients:extrareq:skip:"):
        await feat_clients.client_extrareq_skip_cb(update, ctx)
    elif data in ("clients:pasteok", "clients:pastefix", "clients:fixback"):
        await feat_clients.client_paste_confirm_cb(update, ctx)
    elif data.startswith("clients:fixval:"):
        await feat_clients.client_paste_fixval_cb(update, ctx)
    elif data.startswith("clients:fix:"):
        await feat_clients.client_paste_fix_cb(update, ctx)
    elif data == "clientadd:skipphone" or data.startswith("clientadd:urg:"):
        await feat_clients.client_add_urgency_cb(update, ctx)
    elif data.startswith("client:delconfirm:"):
        await feat_clients.client_delete_confirm(update, ctx)
    elif data.startswith("client:delete:"):
        await feat_clients.client_delete_prompt(update, ctx)
    elif data.startswith("client:send:"):
        await feat_clients.client_send_listing(update, ctx)
    elif data.startswith("send2client:"):
        if not feat_premium.requires_tier(update.callback_query.from_user.id,
                                          "send2client"):
            await update.callback_query.answer()
            await feat_premium.send_gate(update.callback_query, "send2client",
                                         update.callback_query.from_user.id,
                                         edit=True)
            return
        act, payload = feat_sendclient._parse_s2c_cb(data)
        if act == "start":
            await feat_sendclient.s2c_start(update, ctx)
        elif act == "toggle":
            await feat_sendclient.s2c_toggle(update, ctx)
        elif act == "done":
            await feat_sendclient.s2c_done(update, ctx)
        elif act == "lang":
            await feat_sendclient.s2c_lang(update, ctx)
        elif act == "copy":
            await feat_sendclient.s2c_copy(update, ctx)
        elif act == "sent":
            await feat_sendclient.s2c_sent(update, ctx)
        elif act == "followup":
            await feat_sendclient.s2c_followup(update, ctx)
        elif act == "chose":
            await feat_sendclient.s2c_chose(update, ctx)
        elif act == "nochoice":
            await feat_sendclient.s2c_nochoice(update, ctx)
    elif data.startswith("client:broadcast:"):
        if not feat_premium.requires_tier(update.callback_query.from_user.id,
                                          "broadcast"):
            await update.callback_query.answer()
            await feat_premium.send_gate(update.callback_query, "broadcast",
                                         update.callback_query.from_user.id,
                                         edit=True)
        else:
            await feat_match.match_broadcast_send(update, ctx)
    elif data.startswith("client:reqs:"):
        await feat_match.match_requests_list(update, ctx)
    elif data.startswith("mreq:close:"):
        await feat_match.match_request_close(update, ctx)
    elif data.startswith("mresp:view:"):
        await feat_match.match_responses_view(update, ctx)
    elif data.startswith("eve:"):
        act = data.split(":", 2)[1] if ":" in data else ""
        if act == "now":
            await feat_evening.eve_now(update, ctx)
        elif act == "later":
            await feat_evening.eve_later(update, ctx)
        elif act == "done":
            await feat_evening.eve_done(update, ctx)
        elif act == "go":
            await feat_evening.eve_go(update, ctx)
    elif data.startswith("mresp:msg:") or data.startswith("mresp:back:"):
        await feat_match.match_relay_prompt(update, ctx)
    elif data.startswith("mresp:connect:"):
        await feat_match.match_connect_request(update, ctx)
    elif data.startswith("mresp:accept:"):
        await feat_match.match_connect_accept(update, ctx)
    elif data.startswith("mresp:decline:"):
        await feat_match.match_connect_decline(update, ctx)
    elif data == "mresp:cancel":
        await feat_match.match_relay_cancel(update, ctx)
    elif data.startswith("mpick:toggle:"):
        await feat_match.match_pick_toggle(update, ctx)
    elif data.startswith("mpick:send:"):
        await feat_match.match_pick_send(update, ctx)
    elif data.startswith("mpick:cancel:"):
        await feat_match.match_pick_cancel(update, ctx)
    elif data == "enrich:start":
        await feat_clients.enrich_start_cb(update, ctx)
    elif data == "enrich:later":
        await feat_clients.enrich_later_cb(update, ctx)
    elif data.startswith("enrich:t:"):
        await feat_clients.enrich_toggle_cb(update, ctx)
    elif data == "enrich:next":
        await feat_clients.enrich_next_cb(update, ctx)
    elif data == "enrich:skip":
        await feat_clients.enrich_skip_cb(update, ctx)
    elif data == "enrich:done":
        await feat_clients.enrich_done_cb(update, ctx)
    elif data.startswith("client:match:"):
        await feat_clients.client_match(update, ctx)
    elif data.startswith("client:seturg:"):
        await feat_clients.client_set_urgency(update, ctx)
    elif data.startswith("client:editfield:"):
        await feat_clients.client_edit_field(update, ctx)
    elif data.startswith("client:edit:"):
        await feat_clients.client_edit_picker(update, ctx)
    elif data.startswith("client:setstatus:"):
        await feat_clients.client_set_status(update, ctx)
    elif data.startswith("client:status:"):
        await feat_clients.client_status_picker(update, ctx)
    elif data.startswith("client:note:"):
        await feat_clients.client_note_prompt(update, ctx)
    elif data.startswith("client:"):
        # opening a client card = leaving any step (see _LEAVE_STEP_BUTTONS)
        await _release_steps(update, ctx, keep_guided=True)
        await feat_clients.show_client_detail(update, ctx)
    elif data == "onboard:skip_phone":
        await onboard_skip_phone(update, ctx)
    elif data.startswith("onboard2:pronoun:"):
        await onboard2_pronoun_cb(update, ctx)
    elif data == "onboard2:skip_phone":
        await onboard2_skip_phone(update, ctx)
    elif data.startswith("onboard:pronoun:"):
        await onboard_pronoun_cb(update, ctx)
    elif data.startswith("onboard:dname:"):
        await onboard_dname_cb(update, ctx)
    elif data.startswith("cfm:save:"):
        await feat_intake.confirm_save_cb(update, ctx)
    elif data == "drafts:resume":
        await feat_intake.drafts_resume_cb(update, ctx)
    elif data == "batch:more":
        await feat_intake.batch_more_cb(update, ctx)
    elif data == "batch:done":
        await feat_intake.batch_done_cb(update, ctx)
    elif data.startswith("cfm:hl_done:"):
        await feat_intake.hl_done_cb(update, ctx)
    elif data.startswith("cfm:edit:"):
        await feat_listings.confirm_edit_cb(update, ctx)
    elif data.startswith("contact:edit:"):
        await contact_edit_prompt(update, ctx)
    elif data.startswith("editpick:"):
        await feat_listings.edit_pick_cb(update, ctx)
    elif data.startswith("editfield:"):
        await feat_listings.edit_field_cb(update, ctx)
    elif data.startswith("editval:"):
        await feat_listings.edit_value_cb(update, ctx)
    elif data.startswith("editcancel:"):
        await feat_listings.edit_cancel_cb(update, ctx)
    elif data.startswith("edit:"):
        await feat_listings.edit_from_detail(update, ctx)
    elif data.startswith("detail:"):
        await feat_listings.show_detail(update, ctx)
    elif data.startswith("photos:"):
        await feat_listings.view_photos_cb(update, ctx)
    elif data.startswith("addphoto:"):
        await feat_listings.add_photos_cb(update, ctx)
    elif data.startswith("qdetail:"):
        await feat_listings.show_query_detail(update, ctx)
    elif data.startswith("rented:"):
        await feat_listings.mark_rented(update, ctx)
    elif data.startswith("setstatus:"):
        await feat_listings.set_status_cb(update, ctx)
    elif data.startswith("refresh:"):
        await feat_listings.refresh_listing_cb(update, ctx)
    elif data.startswith("qrented:"):
        await feat_listings.mark_query_rented(update, ctx)
    elif data.startswith("delconfirm:"):
        await feat_listings.delete_confirm_cb(update, ctx)
    elif data.startswith("delcancel:"):
        await feat_listings.delete_cancel_cb(update, ctx)
    elif data.startswith("delete:"):
        await feat_listings.delete_listing(update, ctx)
    elif data.startswith("notify:"):
        await feat_notify.notify_pref_toggle(update, ctx)
    elif data.startswith("referral:"):
        await feat_referral.handle_referral_callback(update, ctx)


ERROR_REPLY = ("Em gặp trục trặc khi xử lý thao tác này 😥 Anh thử lại giúp em,"
               " hoặc gõ /menu để quay về menu nhé.")


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    """Application-wide error handler: full traceback to the log, one short
    line to the user. Without it PTB only logs and the user sees a button
    that does nothing."""
    err = getattr(ctx, "error", None)
    if isinstance(err, BadRequest) and "message is not modified" in str(
            err).lower():
        # re-tapping a button that would redraw the same text: harmless
        log.info("ignored 'message is not modified' for update %r",
                 getattr(update, "update_id", update))
        return
    log.error("unhandled error while handling update %r: %r",
              getattr(update, "update_id", update), err,
              exc_info=(type(err), err, err.__traceback__) if err else None)
    if update is None:
        return
    try:
        q = getattr(update, "callback_query", None)
        if q is not None:
            try:
                await q.answer()
            except Exception:
                pass
        chat = getattr(update, "effective_chat", None)
        # apologise only in a private chat -- never into the broker group
        if chat is not None and getattr(chat, "type", None) == "private":
            await ctx.bot.send_message(chat.id, ERROR_REPLY)
    except Exception as e:  # never let the error handler raise
        log.warning("error reply failed: %r", e)


def _single_instance_lock():
    """Hold an exclusive localhost port for the process lifetime.

    Two copies polling the same token race for updates (in-memory
    conversation state splits between them) and both run the outbox poller,
    so queued DMs/penalties go out once per copy. The OS releases the port
    when the process dies, so a crash never leaves a stale lock.
    """
    import os
    import socket
    port = int(os.environ.get("BOT_LOCK_PORT", "47831"))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(f"Another bot.py is already running (lock port {port}).")
    return s


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var first. See README.md")
    _lock = _single_instance_lock()  # noqa: F841 — keep socket open
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("phone", cmd_phone))
    app.add_handler(CommandHandler("edit", feat_listings.cmd_edit))
    app.add_handler(CommandHandler("clients", feat_clients.cmd_clients))
    app.add_handler(CommandHandler("viewings", feat_viewings.cmd_viewings))
    app.add_handler(CommandHandler("templates", feat_templates.cmd_templates))
    app.add_handler(CommandHandler("commission", feat_deals.cmd_commission))
    app.add_handler(CommandHandler("premium", feat_premium.cmd_premium))
    app.add_handler(CommandHandler("approve", feat_premium.cmd_approve))
    app.add_handler(CommandHandler("matchstats", feat_match.cmd_matchstats))
    app.add_handler(CommandHandler("metrics", feat_metrics.cmd_metrics))
    app.add_handler(CommandHandler("skip", feat_listings.cmd_skip_photo_delete))
    app.add_handler(CommandHandler("huy", feat_listings.cmd_cancel_addphoto))
    app.add_handler(CommandHandler("thongbao", feat_notify.cmd_thongbao))
    app.add_handler(CommandHandler("moi", feat_referral.cmd_moi))
    app.add_handler(CallbackQueryHandler(on_callback))
    # Group replies to broadcast messages (cross-broker matching).
    # Registered before on_text so group replies are caught first.
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.REPLY, feat_match.on_group_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, feat_intake.on_photo))
    app.add_error_handler(on_error)
    # Poller: send queued webapp notifications (e.g. slot reopened alerts).
    # Runs every 30s; cheap no-op when outbox is empty.
    async def _outbox_poller(ctx):
        try:
            await feat_match.process_outbox_notifications(ctx)
        except Exception as e:
            log.warning("outbox poller failed: %s", e)
    app.job_queue.run_repeating(_outbox_poller, interval=30, first=10)
    log.info("Linh is running…")
    app.run_polling()


if __name__ == "__main__":
    main()

