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
import feat_viewings
import feat_templates
import feat_refresh
import feat_deals
import feat_evening
import feat_premium
from utils import (
    MENU_KB, STATUS_EMOJI, STATUS_LABEL, LIST_FILTERS,
    CLIENT_STATUS_EMOJI, CLIENT_STATUS_LABEL,
    completeness_score, freshness_badge, get_pronoun,
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
    "📝 <b>Gửi tin mới:</b>\n"
    "- Gửi text mô tả + ảnh trực tiếp cho em (như đăng group FB)\n"
    "- Có thể gửi ảnh kèm caption, hoặc text riêng + ảnh riêng\n"
    "- Em sẽ tóm tắt lại để anh xác nhận, thiếu gì em hỏi thêm (tối đa 2 câu)\n\n"
    "📋 <b>Tin của tôi:</b>\n"
    "- Xem tất cả tin của anh\n"
    "- Lọc theo phòng ngủ, giá tiền, khu vực, trạng thái\n"
    "- Đánh dấu “đã cho thuê” / “còn trống” để em cập nhật\n"
    "- Xem / thêm / xóa ảnh ngay trong chi tiết từng tin\n"
    "- 💎 Gói Pro: gõ “cho xem tin 2PN dưới 15tr” để em tìm giúp\n\n"
    "👥 <b>Khách hàng:</b>\n"
    "- Lưu thông tin khách + nhu cầu tìm nhà\n"
    "- Theo dõi trạng thái: mới → đang xem → đã cọc → đã thuê\n"
    "- ⏰ Em tự nhắc khi 3+ ngày chưa liên lạc với khách\n"
    "- 💎 Gói Pro: em tự gợi ý tin phù hợp cho từng khách\n\n"
    "✍️ <b>Viết tin FB:</b>\n"
    "- Em viết bài đăng FB từ tin của anh\n"
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
    broker = db.get_or_create_broker(u.id, u.username, u.full_name)
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


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
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

    # 0. onboarding (phone/name collection) takes priority
    ob = ctx.user_data.get("onboarding")
    if ob:
        await _handle_onboarding(update, ctx, ob, text)
        return

    # 0b. editing a contact field via /contacts or /phone
    ec = ctx.user_data.get("editing_contact")
    if ec:
        await _handle_contact_edit(update, ctx, ec, text)
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
        await feat_deals._handle_add_deal(update, ctx, ad, text)
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

    # 1b9. entering post-viewing feedback?
    vf = ctx.user_data.get("viewing_feedback")
    if vf:
        await feat_viewings._handle_viewing_feedback(update, ctx, vf, text)
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

    # 2. part of an active collection buffer?
    buf = _buffers.get(uid)
    if buf:
        fwd_here = get_forward_source(update.message)
        buf["texts"].append(strip_forward_noise(text) if fwd_here else text)
        buf["deadline"] = time.time() + COLLECT_WINDOW
        # remember forward origin for the confirmation summary
        if not buf.get("forward_source") and fwd_here:
            buf["forward_source"] = fwd_here
        return

    # 3. natural-language listing query? (not a new listing) — Pro feature
    if listing_parser.looks_like_query(text):
        if not feat_premium.requires_tier(uid, "natural_query"):
            await natural_delay(update)
            await feat_premium.send_gate(update, "natural_query", uid)
            return
        await feat_listings._handle_query(update, ctx, uid, text)
        return

    # 4. otherwise treat as a fresh listing
    if db.count_recent_listings(uid, hours=1) >= config.RATE_LIMIT_PER_HOUR:
        await natural_delay(update)
        await update.message.reply_text(
            f"Anh gửi nhiều quá rồi 😅 Tối đa {config.RATE_LIMIT_PER_HOUR} tin/giờ thôi ạ.",
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


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "menu:new":
        await feat_intake.on_new_listing_prompt(update, ctx)
    elif data.startswith("menu:list:"):
        await feat_listings.show_my_listings(update, ctx)
    elif data.startswith("flt:"):
        await feat_listings.show_filter_picker(update, ctx)
    elif data == "menu:write":
        await feat_write.on_write_post_prompt(update, ctx)
    elif data == "write:new":
        await feat_write.on_write_new(update, ctx)
    elif data.startswith("write:"):
        await feat_write.on_write_lang(update, ctx)
    elif data.startswith("writelang:"):
        await feat_write.on_write_generate(update, ctx)
    elif data == "menu:help":
        await show_help(update, ctx)
    elif data == "menu:back":
        await show_menu(update, ctx)
    elif data == "premium:plans":
        await feat_premium.premium_plans_cb(update, ctx)
    elif data.startswith("premium:want:"):
        await feat_premium.premium_want_cb(update, ctx)
    elif data == "premium:paid":
        await feat_premium.premium_paid_cb(update, ctx)
    elif data == "menu:clients":
        await feat_clients.show_clients(update, ctx)
    elif data == "menu:premium":
        await feat_premium.cmd_premium(update, ctx)
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
    elif data.startswith("guided:set:"):
        await feat_intake.guided_set(update, ctx)
    elif data == "guided:back":
        await feat_intake.guided_back(update, ctx)
    elif data == "guided:skip":
        await feat_intake.guided_skip(update, ctx)
    elif data == "menu:viewings":
        if not feat_premium.requires_tier(update.callback_query.from_user.id,
                                          "viewings"):
            await update.callback_query.answer()
            await feat_premium.send_gate(update.callback_query, "viewings",
                                         update.callback_query.from_user.id,
                                         edit=True)
        else:
            await feat_viewings.cmd_viewings_cb(update, ctx)
    elif data.startswith("vw:"):
        act, payload = _parse_vw_cb(data)
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
    elif data.startswith("tpl:"):
        act, _ = _parse_tpl_cb(data)
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
    elif data.startswith("cms:"):
        await feat_deals.cms_nav(update, ctx)
    elif data.startswith("clients:list:"):
        await feat_clients.show_clients(update, ctx)
    elif data == "clients:new":
        await feat_clients.client_add_start(update, ctx)
    elif data == "clients:cancel":
        await feat_clients.client_add_cancel(update, ctx)
    elif data == "clientadd:skipphone" or data.startswith("clientadd:urg:"):
        await feat_clients.client_add_urgency_cb(update, ctx)
    elif data.startswith("client:delconfirm:"):
        await feat_clients.client_delete_confirm(update, ctx)
    elif data.startswith("client:delete:"):
        await feat_clients.client_delete_prompt(update, ctx)
    elif data.startswith("client:send:"):
        await feat_clients.client_send_listing(update, ctx)
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
    elif data == "mresp:cancel":
        await feat_match.match_relay_cancel(update, ctx)
    elif data.startswith("mpick:toggle:"):
        await feat_match.match_pick_toggle(update, ctx)
    elif data.startswith("mpick:send:"):
        await feat_match.match_pick_send(update, ctx)
    elif data.startswith("mpick:cancel:"):
        await feat_match.match_pick_cancel(update, ctx)
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
        await feat_clients.show_client_detail(update, ctx)
    elif data == "onboard:skip_phone":
        await onboard_skip_phone(update, ctx)
    elif data.startswith("onboard:pronoun:"):
        await onboard_pronoun_cb(update, ctx)
    elif data.startswith("onboard:dname:"):
        await onboard_dname_cb(update, ctx)
    elif data.startswith("cfm:save:"):
        await feat_intake.confirm_save_cb(update, ctx)
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


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var first. See README.md")
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
    app.add_handler(CommandHandler("skip", feat_listings.cmd_skip_photo_delete))
    app.add_handler(CommandHandler("huy", feat_listings.cmd_cancel_addphoto))
    app.add_handler(CallbackQueryHandler(on_callback))
    # Group replies to broadcast messages (cross-broker matching).
    # Registered before on_text so group replies are caught first.
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.REPLY, feat_match.on_group_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, feat_intake.on_photo))
    log.info("Linh is running…")
    app.run_polling()


if __name__ == "__main__":
    main()

