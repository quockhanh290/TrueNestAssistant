"""TrueNest Assistant — Telegram bot "Linh" for broker listing management.

MVP: intake free-form listings, AI-parse (regex), ask max 2 missing
critical fields, save to SQLite, manage own listings, availability nudge.

Run:  TELEGRAM_BOT_TOKEN=... python bot.py
"""
import asyncio
import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("linh")

# ---------------------------------------------------------------- helpers

MENU_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📝 Gửi tin mới", callback_data="menu:new")],
    [InlineKeyboardButton("📋 Tin của tôi", callback_data="menu:list:0")],
    [InlineKeyboardButton("✍️ Viết tin FB", callback_data="menu:write")],
    [InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu:help")],
])

STATUS_EMOJI = {
    "draft": "📝", "pending_info": "⏳", "in_review": "🔍",
    "approved": "✅", "rented": "🔑", "expired": "📦", "rejected": "❌",
}

# per-user collection buffer: {user_id: {"texts": [], "photos": [], "deadline": ts}}
_buffers = {}
COLLECT_WINDOW = 30  # seconds to wait for text+photos arriving together


async def natural_delay(update: Update):
    """Typing indicator + human-like delay before replying."""
    try:
        await update.effective_chat.send_action("typing")
    except Exception:
        pass
    await asyncio.sleep(random.uniform(config.REPLY_DELAY_MIN,
                                       config.REPLY_DELAY_MAX))


def fmt_price(v):
    if not v:
        return "?"
    if v >= 1_000_000:
        return f"{v / 1_000_000:g}tr"
    return f"{int(v):,}".replace(",", ".")


def listing_line(l):
    p = l["parsed"]
    br = p.get("bedrooms")
    br_s = "studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = p.get("building_name") or p.get("district") or "?"
    st = STATUS_EMOJI.get(l["status"], "•")
    return (f"{st} {br_s} {loc}, {fmt_price(p.get('price_vnd'))}"
            f" — 👀 {l['view_count']}")


# ---------------------------------------------------------------- /start

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    await update.message.reply_text(
        f"Chào anh! Em là {config.BOT_NAME}, trợ lý quản lý tin cho thuê.\n\n"
        "Anh gửi tin thoải mái như đăng group — text + ảnh kiểu gì cũng được, "
        "em tự sắp xếp lại cho gọn gàng.",
        reply_markup=MENU_KB,
    )


async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Anh cần gì ạ?", reply_markup=MENU_KB)


async def show_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await natural_delay(update)
    await q.edit_message_text(
        "❓ <b>Hướng dẫn</b>\n\n"
        "📝 <b>Gửi tin mới:</b> bấm nút rồi gửi text + ảnh của tin. "
        "Gửi xong em tự đọc và tóm tắt lại, thiếu gì em hỏi thêm.\n\n"
        "📋 <b>Tin của tôi:</b> xem lại các tin đã gửi, đánh dấu đã cho thuê.\n\n"
        "✍️ <b>Viết tin FB:</b> em viết giúp anh tin đăng Facebook "
        "tiếng Việt / tiếng Anh từ tin đã có.\n\n"
        "Mẹo: cứ gửi như anh đăng group là được, không cần theo mẫu gì cả.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")]]),
    )


# ---------------------------------------------------------------- intake

async def on_new_listing_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped 📝 Gửi tin mới — arm the collection buffer."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    # rate limit
    if db.count_recent_listings(uid, hours=1) >= config.RATE_LIMIT_PER_HOUR:
        await q.edit_message_text(
            f"Anh gửi nhiều quá rồi 😅 Em chỉ nhận tối đa "
            f"{config.RATE_LIMIT_PER_HOUR} tin/giờ thôi, anh nghỉ chút rồi gửi tiếp nhé.",
            reply_markup=MENU_KB,
        )
        return
    _buffers[uid] = {"texts": [], "photos": [], "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": q.message.chat_id}
    await natural_delay(update)
    await q.edit_message_text(
        "Ok anh, anh gửi tin đi ạ — text + ảnh, gửi nhiều tin nhắn cũng được, "
        "em chờ 30 giây rồi tổng hợp một thể 📥"
    )
    # schedule flush
    asyncio.create_task(_flush_after(uid, ctx))


async def _flush_after(uid, ctx):
    await asyncio.sleep(COLLECT_WINDOW + 1)
    buf = _buffers.pop(uid, None)
    if not buf or (not buf["texts"] and not buf["photos"]):
        return
    await _process_buffer(uid, buf, ctx)


async def _process_buffer(uid, buf, ctx):
    chat_id = buf["chat_id"]
    raw = "\n".join(buf["texts"])
    photos = buf["photos"]
    result = listing_parser.parse_listing(raw, photo_count=len(photos))

    await ctx.bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(random.uniform(2, 3))

    listing_id = db.create_listing(
        uid, raw_text=raw, photo_file_ids=photos,
        parsed=result["fields"], missing_fields=result["missing"],
        status="in_review" if not result["missing"] else "pending_info",
    )

    # reflective summary
    summary = listing_parser.reflective_summary(result)
    photo_note = f"\n📸 {len(photos)} ảnh" if photos else ""
    await ctx.bot.send_message(chat_id, summary + photo_note)

    # ask max 2 missing critical fields
    missing = [m for m in result["missing"] if m in config.CRITICAL_FIELDS]
    missing = missing[:config.MAX_MISSING_QUESTIONS]
    if missing:
        db.update_listing(listing_id, missing_fields=missing)
        await _ask_missing(chat_id, uid, listing_id, missing[0], ctx,
                           remaining=missing[1:])
    else:
        db.update_listing(listing_id, status="in_review")
        db.set_listing_status(listing_id, "in_review", changed_by="bot")
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(1)
        await ctx.bot.send_message(
            chat_id,
            "Xong! Tin đang chờ duyệt ✓ Em báo khi xong nhé.",
            reply_markup=MENU_KB,
        )


QUESTION_TEXT = {
    "price_vnd": "Giá thuê bao nhiêu một tháng ạ?",
    "primary_phone": "Còn thiếu SĐT để khách liên hệ, anh cho em nhé?",
    "photos": "Anh gửi thêm ảnh của căn này giúp em nhé? (càng nhiều càng tốt)",
}


async def _ask_missing(chat_id, uid, listing_id, field, ctx, remaining):
    ctx.user_data["awaiting"] = {"listing_id": listing_id, "field": field,
                                 "remaining": remaining}
    await asyncio.sleep(1)
    await ctx.bot.send_message(chat_id, QUESTION_TEXT[field])


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""

    # 1. answering a missing-field question?
    awaiting = ctx.user_data.get("awaiting")
    if awaiting:
        await _handle_answer(update, ctx, awaiting, text)
        return

    # 2. part of an active collection buffer?
    buf = _buffers.get(uid)
    if buf:
        buf["texts"].append(text)
        buf["deadline"] = time.time() + COLLECT_WINDOW
        return

    # 3. otherwise treat as a fresh listing
    if db.count_recent_listings(uid, hours=1) >= config.RATE_LIMIT_PER_HOUR:
        await natural_delay(update)
        await update.message.reply_text(
            f"Anh gửi nhiều quá rồi 😅 Tối đa {config.RATE_LIMIT_PER_HOUR} tin/giờ thôi ạ.",
            reply_markup=MENU_KB,
        )
        return
    _buffers[uid] = {"texts": [text], "photos": [],
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": update.effective_chat.id}
    await update.message.reply_text(
        "Nhận được! Nếu còn ảnh thì anh gửi thêm nhé, em chờ 30 giây 📥")
    asyncio.create_task(_flush_after(uid, ctx))


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    file_id = update.message.photo[-1].file_id  # largest size
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].append(file_id)
        buf["deadline"] = time.time() + COLLECT_WINDOW
    else:
        # photo without text — start a buffer anyway
        _buffers[uid] = {"texts": [], "photos": [file_id],
                         "deadline": time.time() + COLLECT_WINDOW,
                         "chat_id": update.effective_chat.id}
        await update.message.reply_text(
            "Nhận ảnh! Anh gửi thêm text mô tả giúp em nhé 📥")
        asyncio.create_task(_flush_after(uid, ctx))


async def _handle_answer(update, ctx, awaiting, text):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    listing_id = awaiting["listing_id"]
    field = awaiting["field"]
    listing = db.get_listing(listing_id)
    if not listing:
        ctx.user_data.pop("awaiting", None)
        return

    parsed = listing["parsed"]
    if field == "price_vnd":
        price, _ = listing_parser.parse_price(text)
        if price:
            parsed["price_vnd"] = price
            await natural_delay(update)
            await update.message.reply_text(f"Ok, đã nhận giá {fmt_price(price)}/tháng ✓")
        else:
            await update.message.reply_text(
                "Em chưa hiểu giá này lắm, anh ghi lại giúp em VD: 12tr ạ?")
            return  # stay on same question
    elif field == "primary_phone":
        phone, _ = listing_parser.parse_phone(text)
        if phone:
            parsed["primary_phone"] = phone
            # save to broker profile too
            db.update_broker(uid, phone=phone)
            await natural_delay(update)
            await update.message.reply_text("Đã lưu SĐT ✓")
        else:
            await update.message.reply_text(
                "Số này em chưa nhận ra, anh ghi lại 10 số giúp em nhé?")
            return

    remaining = [m for m in awaiting["remaining"]]
    # recompute what's still missing
    still = []
    if "price_vnd" not in parsed:
        still.append("price_vnd")
    if "primary_phone" not in parsed:
        still.append("primary_phone")
    if len(listing["photo_file_ids"]) < 1:
        still.append("photos")
    still = [s for s in still if s in remaining][:config.MAX_MISSING_QUESTIONS]

    db.update_listing(listing_id, parsed=parsed, missing_fields=still)
    if still:
        await _ask_missing(chat_id, uid, listing_id, still[0], ctx,
                           remaining=still[1:])
    else:
        ctx.user_data.pop("awaiting", None)
        db.set_listing_status(listing_id, "in_review", changed_by="bot")
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(1)
        await update.message.reply_text(
            "Xong! Tin đang chờ duyệt ✓ Em báo khi xong nhé.",
            reply_markup=MENU_KB,
        )


# ---------------------------------------------------------------- my listings

async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    page = int(q.data.split(":")[2])
    per = 5
    total = db.count_broker_listings(uid)
    items = db.list_broker_listings(uid, limit=per, offset=page * per)
    if not items:
        await q.edit_message_text("Anh chưa có tin nào. Bấm 📝 Gửi tin mới để bắt đầu nhé!",
                                  reply_markup=MENU_KB)
        return
    lines = [f"<b>📋 Tin của anh ({total}):</b>"]
    kb = []
    for i, l in enumerate(items, start=page * per + 1):
        lines.append(f"{i}. {listing_line(l)}")
        kb.append([InlineKeyboardButton(
            f"{i}. Chi tiết", callback_data=f"detail:{l['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"menu:list:{page-1}"))
    if (page + 1) * per < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"menu:list:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await natural_delay(update)
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def show_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, listing_id, page = q.data.split(":")
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    p = l["parsed"]
    lines = [
        f"<b>{listing_line(l)}</b>",
        f"📸 {len(l['photo_file_ids'])} ảnh | 👀 {l['view_count']} lượt xem",
        f"Trạng thái: {STATUS_EMOJI.get(l['status'], '')} {l['status']}",
    ]
    if p.get("area_m2"):
        lines.append(f"Diện tích: {p['area_m2']:g}m²")
    if p.get("furnishing"):
        lines.append(f"Nội thất: {p['furnishing']}")
    kb = []
    if l["status"] not in ("rented", "deleted"):
        kb.append([InlineKeyboardButton("🔑 Đánh dấu đã cho thuê",
                                       callback_data=f"rented:{listing_id}:{page}")])
    kb.append([InlineKeyboardButton("🗑 Xoá tin",
                                    callback_data=f"delete:{listing_id}:{page}")])
    kb.append([InlineKeyboardButton("⬅️ Danh sách",
                                    callback_data=f"menu:list:{page}")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def mark_rented(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, listing_id, page = q.data.split(":")
    db.set_listing_status(listing_id, "rented", changed_by="broker")
    await natural_delay(update)
    await q.edit_message_text("Đã đánh dấu cho thuê 🔑 Chúc mừng anh!",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data=f"menu:list:{page}")]]))


async def delete_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, listing_id, page = q.data.split(":")
    db.set_listing_status(listing_id, "deleted", changed_by="broker")
    await q.edit_message_text("Đã xoá tin 🗑",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data=f"menu:list:{page}")]]))


# ---------------------------------------------------------------- write FB post

# user_ids currently in "write post" mode: after intake completes,
# go to language selection instead of the normal "done" message.
_write_post_pending = set()

PTYPE_VI = {"apartment": "căn hộ", "house": "nhà", "villa": "villa",
            "room": "phòng", "studio": "studio"}
PTYPE_EN = {"apartment": "apartment", "house": "house", "villa": "villa",
            "room": "room", "studio": "studio"}
FURN_VI = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}
FURN_EN = {"full": "Fully furnished", "basic": "Basic furnishing",
           "empty": "Unfurnished"}


def generate_post(listing, lang="vi"):
    """Build a Facebook-ready post from a listing dict.

    lang: 'vi' | 'en' | 'both'. Only includes fields that have values.
    """
    p = listing["parsed"]

    br = p.get("bedrooms")
    if br == 0.0:
        br_vi, br_en = "studio", "studio"
    elif br:
        br_vi, br_en = f"{int(br)}PN", f"{int(br)}BR"
    else:
        br_vi, br_en = "", ""

    ptype = p.get("property_type") or ""
    ptype_vi = PTYPE_VI.get(ptype, "căn hộ")
    ptype_en = PTYPE_EN.get(ptype, "apartment")

    loc = p.get("building_name") or p.get("district") or ""
    street = p.get("street") or ""
    district = p.get("district") or ""
    if street:
        address = street + (f", {district}" if district else "")
    else:
        address = loc

    price = p.get("price_vnd")
    price_vi = f"{fmt_price(price)}/tháng" if price else ""
    price_en = f"{fmt_price(price)} VND/month" if price else ""

    ba = p.get("bathrooms")
    area = p.get("area_m2")
    furn = p.get("furnishing")
    pet = p.get("pet_friendly")
    phone = p.get("primary_phone") or ""

    def build_vi():
        title_br = f" {br_vi}" if br_vi else ""
        lines = [f"🏠 CHO THUÊ {ptype_vi.upper()}{title_br}"
                 + (f" - {loc}" if loc else "")]
        lines.append("")
        if address:
            lines.append(f"📍 Địa chỉ: {address}")
        if price_vi:
            lines.append(f"💰 Giá: {price_vi}")
        specs = []
        if br_vi:
            specs.append(f"🛏️ {br_vi}")
        if ba:
            specs.append(f"🛁 {int(ba)} WC")
        if area:
            specs.append(f"📐 {area:g}m²")
        if specs:
            lines.append(" | ".join(specs))
        if furn and furn in FURN_VI:
            lines.append(f"🛋️ Nội thất: {FURN_VI[furn]}")
        if pet is True:
            lines.append("🐾 Cho nuôi pet")
        elif pet is False:
            lines.append("🐾 Không nuôi pet")
        lines.append("")
        if phone:
            lines.append(f"📞 Liên hệ: {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_en():
        title_br = f" {br_en}" if br_en else ""
        lines = [f"🏠 FOR RENT{title_br} {ptype_en.upper()}"
                 + (f" - {loc}" if loc else "")]
        lines.append("")
        if address:
            lines.append(f"📍 Location: {address}")
        if price_en:
            lines.append(f"💰 Price: {price_en}")
        specs = []
        if br_en:
            specs.append(f"🛏️ {br_en}")
        if ba:
            specs.append(f"🛁 {int(ba)} BA")
        if area:
            specs.append(f"📐 {area:g}sqm")
        if specs:
            lines.append(" | ".join(specs))
        if furn and furn in FURN_EN:
            lines.append(f"🛋️ Furnishing: {FURN_EN[furn]}")
        if pet is True:
            lines.append("🐾 Pet-friendly")
        elif pet is False:
            lines.append("🐾 No pets")
        lines.append("")
        if phone:
            lines.append(f"📞 Contact: {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    if lang == "en":
        return build_en()
    if lang == "both":
        return build_vi() + "\n\n---\n\n" + build_en()
    return build_vi()


async def on_write_post_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped ✍️ Viết tin FB — pick a listing or enter a new one."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    items = db.list_broker_listings(uid, limit=5, offset=0)
    kb = []
    for i, l in enumerate(items, start=1):
        kb.append([InlineKeyboardButton(
            f"{i}. {listing_line(l)}", callback_data=f"write:{l['id']}")])
    kb.append([InlineKeyboardButton("➕ Tin mới (nhập tay)",
                                    callback_data="write:new")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await natural_delay(update)
    if items:
        total = db.count_broker_listings(uid)
        text = (f"Anh muốn viết tin cho căn nào? "
                f"Em thấy anh có {total} tin gần đây nè:")
    else:
        text = ("Anh chưa có tin nào trong hệ thống. "
                "Anh gửi thông tin căn hộ cho em nhé — "
                "giá, địa chỉ, số PN... gửi thoải mái như đăng group là được!")
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def on_write_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User chose ➕ Tin mới — intake, then jump to language selection."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if db.count_recent_listings(uid, hours=1) >= config.RATE_LIMIT_PER_HOUR:
        await q.edit_message_text(
            f"Anh gửi nhiều quá rồi 😅 Tối đa {config.RATE_LIMIT_PER_HOUR} tin/giờ thôi ạ.",
            reply_markup=MENU_KB,
        )
        return
    _write_post_pending.add(uid)
    _buffers[uid] = {"texts": [], "photos": [],
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": q.message.chat_id}
    await natural_delay(update)
    await q.edit_message_text(
        "Ok anh, anh gửi thông tin căn hộ cho em — text + ảnh, "
        "em chờ 30 giây rồi viết tin luôn 📥"
    )
    asyncio.create_task(_flush_after(uid, ctx))


async def on_write_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show language selection for the chosen listing."""
    q = update.callback_query
    await q.answer()
    _, listing_id = q.data.split(":")
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇻🇳 Tiếng Việt",
                              callback_data=f"writelang:{listing_id}:vi")],
        [InlineKeyboardButton("🇬🇧 Tiếng Anh",
                              callback_data=f"writelang:{listing_id}:en")],
        [InlineKeyboardButton("🇻🇳+🇬🇧 Cả hai",
                              callback_data=f"writelang:{listing_id}:both")],
        [InlineKeyboardButton("⬅️ Chọn căn khác",
                              callback_data="menu:write")],
    ])
    await natural_delay(update)
    await q.edit_message_text(
        f"Căn {listing_line(l)} này viết tiếng Việt hay tiếng Anh anh? "
        "Hay cả hai cho chắc? 😊",
        parse_mode="HTML", reply_markup=kb)


async def on_write_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Generate the FB post and send it as a copyable message."""
    q = update.callback_query
    await q.answer()
    _, listing_id, lang = q.data.split(":")
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    post = generate_post(l, lang)
    # feel like Linh is actually sitting down and writing it
    await q.message.reply_text("Để em viết nhé... ✍️")
    for _ in range(2):
        try:
            await q.message.chat.send_action("typing")
        except Exception:
            pass
        await asyncio.sleep(random.uniform(1.5, 2.5))
    # send the post itself as a plain message (easy to copy)
    await q.message.reply_text(post)
    await asyncio.sleep(1)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Viết lại",
                              callback_data=f"writelang:{listing_id}:{lang}")],
        [InlineKeyboardButton("📝 Gửi tin khác", callback_data="menu:write")],
    ])
    await q.message.reply_text(
        "Xong rồi anh! Copy đoạn trên để đăng FB nhé. "
        "Thấy chỗ nào chưa ưng thì bảo em sửa.",
        reply_markup=kb)


async def _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
    """After intake: if user is in write-post mode, go to language
    selection instead of the normal 'done' message. Returns True if
    handled."""
    if uid not in _write_post_pending:
        return False
    _write_post_pending.discard(uid)
    l = db.get_listing(listing_id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇻🇳 Tiếng Việt",
                              callback_data=f"writelang:{listing_id}:vi")],
        [InlineKeyboardButton("🇬🇧 Tiếng Anh",
                              callback_data=f"writelang:{listing_id}:en")],
        [InlineKeyboardButton("🇻🇳+🇬🇧 Cả hai",
                              callback_data=f"writelang:{listing_id}:both")],
    ])
    await asyncio.sleep(1)
    if l:
        await ctx.bot.send_message(
            chat_id,
            f"Nhận tin xong! Căn {listing_line(l)} này viết tiếng Việt "
            "hay tiếng Anh anh? Hay cả hai cho chắc? 😊",
            reply_markup=kb)
    else:
        await ctx.bot.send_message(chat_id, "Có lỗi rồi, anh thử lại nhé.",
                                   reply_markup=MENU_KB)
    return True


# ---------------------------------------------------------------- router

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "menu:new":
        await on_new_listing_prompt(update, ctx)
    elif data.startswith("menu:list:"):
        await show_my_listings(update, ctx)
    elif data == "menu:write":
        await on_write_post_prompt(update, ctx)
    elif data == "write:new":
        await on_write_new(update, ctx)
    elif data.startswith("write:"):
        await on_write_lang(update, ctx)
    elif data.startswith("writelang:"):
        await on_write_generate(update, ctx)
    elif data == "menu:help":
        await show_help(update, ctx)
    elif data == "menu:back":
        await show_menu(update, ctx)
    elif data.startswith("detail:"):
        await show_detail(update, ctx)
    elif data.startswith("rented:"):
        await mark_rented(update, ctx)
    elif data.startswith("delete:"):
        await delete_listing(update, ctx)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var first. See README.md")
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    log.info("Linh is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
