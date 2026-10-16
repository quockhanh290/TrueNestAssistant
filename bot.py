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
    [InlineKeyboardButton("📋 Tin của tôi", callback_data="menu:list:0:s:a")],
    [InlineKeyboardButton("✍️ Viết tin FB", callback_data="menu:write")],
    [InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu:help")],
])

STATUS_EMOJI = {
    "draft": "📝", "pending_info": "⏳", "submitted": "✅",
    "rented": "🔑", "expired": "📦",
}

# listing list filters for "📋 Tin của tôi"
LIST_FILTERS = {
    "all": {"label": "Tất cả", "statuses": None},          # None = all except deleted
    "active": {"label": "Đang trống", "statuses": ("draft", "pending_info", "submitted")},
    "rented": {"label": "Đã cho thuê", "statuses": ("rented",)},
}

# status labels for display
STATUS_LABEL = {
    "draft": "nháp", "pending_info": "thiếu info", "submitted": "đang trống",
    "rented": "đã cho thuê", "expired": "hết hạn", "deleted": "đã xoá",
}

# filter option codes (compact for callback_data)
DISTRICT_CODES = {
    "st": "Sơn Trà", "hc": "Hải Châu", "nhs": "Ngũ Hành Sơn",
    "lc": "Liên Chiểu", "cl": "Cẩm Lệ", "tk": "Thanh Khê",
}
PRICE_RANGES = {
    # code: (label, min_vnd, max_vnd)
    "u8": ("Dưới 8tr", None, 8_000_000),
    "812": ("8-12tr", 8_000_000, 12_000_000),
    "1220": ("12-20tr", 12_000_000, 20_000_000),
    "o20": ("Trên 20tr", 20_000_000, None),
}
BR_OPTIONS = [("0", "Studio"), ("1", "1PN"), ("2", "2PN"), ("3", "3PN"), ("4", "4PN+")]


def _parse_filter_str(fs):
    """'s:a,br:2,pr:812,di:st' -> {'s': 'a', 'br': '2', ...}"""
    d = {}
    for part in (fs or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if v and v != "-":
                d[k] = v
    return d


def _build_filter_str(d):
    return ",".join(f"{k}:{v}" for k, v in sorted(d.items()) if v and v != "-")


def _filters_to_search(f):
    """Convert UI filter dict to db.search_listings() filters."""
    sf = {}
    s = f.get("s", "a")
    if s == "t":
        sf["status"] = "active"
    elif s == "r":
        sf["status"] = "rented"
    # s == "a" -> default (hide deleted)

    br = f.get("br")
    if br == "0":
        sf["bedrooms"] = 0.0
    elif br in ("1", "2", "3"):
        sf["bedrooms"] = float(br)
    elif br == "4":
        sf["min_bedrooms"] = 4.0

    pr = f.get("pr")
    if pr in PRICE_RANGES:
        _, mn, mx = PRICE_RANGES[pr]
        if mn:
            sf["min_price"] = float(mn)
        if mx:
            sf["max_price"] = float(mx)

    di = f.get("di")
    if di in DISTRICT_CODES:
        sf["district"] = DISTRICT_CODES[di]

    return sf


def _describe_ui_filters(f):
    """Short Vietnamese description of active UI filters."""
    bits = []
    s = f.get("s", "a")
    if s == "t":
        bits.append("đang trống")
    elif s == "r":
        bits.append("đã cho thuê")
    br = f.get("br")
    if br == "0":
        bits.append("Studio")
    elif br in ("1", "2", "3"):
        bits.append(f"{br}PN")
    elif br == "4":
        bits.append("4PN+")
    pr = f.get("pr")
    if pr in PRICE_RANGES:
        bits.append(PRICE_RANGES[pr][0])
    di = f.get("di")
    if di in DISTRICT_CODES:
        bits.append(DISTRICT_CODES[di])
    return ", ".join(bits)


def rel_time(ts):
    """'3 ngày trước', '2 giờ trước', 'vừa xong'."""
    import time as _t
    d = _t.time() - ts
    if d < 3600:
        m = int(d // 60)
        return "vừa xong" if m < 1 else f"{m} phút trước"
    if d < 86400:
        return f"{int(d // 3600)} giờ trước"
    return f"{int(d // 86400)} ngày trước"


def parse_listing_cb(data, action):
    """Parse 'action:tg:<hex>:page[:filter_str]' — listing ids contain a colon.
    Returns (listing_id, page, filter_str). filter_str like 's:a,br:2'."""
    rest = data[len(action) + 1:]          # strip "action:"
    # rest = "tg:<hex>:page[:filter_str]"
    m = __import__("re").match(r"^(tg:[0-9a-f]+):(\d+)(?::(.+))?$", rest)
    if not m:
        return None, "0", "s:a"
    return m.group(1), m.group(2), m.group(3) or "s:a"

# per-user collection buffer: {user_id: {"texts": [], "photos": [], "deadline": ts}}
_buffers = {}
COLLECT_WINDOW = 30  # seconds to wait for text+photos arriving together

# album (media group) reassembly: {f"{uid}:{media_group_id}": {...}}
# Telegram splits an album into separate messages sharing one media_group_id;
# the caption lives only on the first message. We debounce per group, then
# merge photos + caption into the user's collection buffer as one listing.
_media_groups = {}
MEDIA_GROUP_WINDOW = 2  # seconds of quiet before flushing an album


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
    """Two-line compact display with essential info:
    🏠 2PN An Thượng, 12tr/tháng
    📐 52m² | 🛋️ Full NT | 🐾 Pet OK | 👀 23 | ✅ đang trống
    """
    p = l["parsed"]
    br = p.get("bedrooms")
    br_s = "studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = p.get("building_name") or p.get("district") or "?"
    price = fmt_price(p.get("price_vnd"))

    line1 = f"🏠 {br_s} {loc}, {price}/tháng"

    bits = []
    area = p.get("area_m2")
    if area:
        bits.append(f"📐 {area:g}m²")
    furn = p.get("furnishing")
    if furn:
        furn_s = {"full": "Full NT", "basic": "NT cơ bản",
                  "empty": "Trống"}.get(furn, furn)
        bits.append(f"🛋️ {furn_s}")
    pet = p.get("pet_friendly")
    if pet is True:
        bits.append("🐾 Pet OK")
    elif pet is False:
        bits.append("🐾 No pet")
    bits.append(f"👀 {l['view_count']}")
    st_emoji = STATUS_EMOJI.get(l["status"], "•")
    st_label = STATUS_LABEL.get(l["status"], l["status"])
    bits.append(f"{st_emoji} {st_label}")

    return f"{line1}\n{' | '.join(bits)}"


# ---------------------------------------------------------------- /start

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
    "- Hoặc gõ trực tiếp kiểu “cho xem tin 2PN dưới 15tr” để em tìm giúp\n\n"
    "✍️ <b>Viết tin FB:</b>\n"
    "- Em viết bài đăng FB từ tin của anh\n"
    "- 5 ngôn ngữ: Việt, Anh, Hàn, Trung, Nga\n\n"
    "⌨️ <b>Lệnh nhanh:</b>\n"
    "/menu — mở menu chính\n"
    "/help — xem hướng dẫn này"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    await update.message.reply_text(
        f"Chào anh! Em là {config.BOT_NAME} 🏠\n\n"
        "Em là trợ lý quản lý tin cho thuê MIỄN PHÍ dành cho môi giới Đà Nẵng.\n\n"
        "Em giúp anh:\n"
        "📝 Lưu tin cho thuê — chỉ cần gửi text + ảnh như đăng group FB, em tự bóc thông tin\n"
        "📋 Quản lý tin — xem, lọc theo phòng/giá/khu vực, đánh dấu đã cho thuê hay còn trống\n"
        "✍️ Viết tin FB — tự động viết bài đăng đẹp, 5 ngôn ngữ (Việt/Anh/Hàn/Trung/Nga)\n"
        "🔔 Nhắc thông minh — em nhắc khi tin thiếu thông tin hoặc lâu chưa cập nhật\n\n"
        "👉 Để bắt đầu, anh cứ gửi tin đầu tiên cho em nhé! (text kèm ảnh)\n\n"
        "Gõ /menu để mở menu bất cứ lúc nào, /help để xem hướng dẫn chi tiết.",
        reply_markup=MENU_KB,
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    await update.message.reply_text("Anh cần gì ạ?", reply_markup=MENU_KB)


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
    await q.edit_message_text("Anh cần gì ạ?", reply_markup=MENU_KB)


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
    await asyncio.sleep(random.uniform(1.0, 1.5))

    listing_id = db.create_listing(
        uid, raw_text=raw, photo_file_ids=photos,
        parsed=result["fields"], missing_fields=result["missing"],
        status="submitted" if not result["missing"] else "pending_info",
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
        db.update_listing(listing_id, status="submitted")
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(1)
        await ctx.bot.send_message(
            chat_id,
            "Xong! Em đã lưu tin rồi nhé ✓",
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

    # 3. natural-language listing query? (not a new listing)
    if listing_parser.looks_like_query(text):
        await _handle_query(update, ctx, uid, text)
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
                     "chat_id": update.effective_chat.id}
    await update.message.reply_text(
        "Nhận được! Nếu còn ảnh thì anh gửi thêm nhé, em chờ 30 giây 📥")
    asyncio.create_task(_flush_after(uid, ctx))


async def _flush_media_group(key, ctx):
    """Debounced flush of one album: merge its photos + caption into the
    user's collection buffer (creating one if needed)."""
    try:
        await asyncio.sleep(MEDIA_GROUP_WINDOW)
    except asyncio.CancelledError:
        return  # superseded by a newer message in the same album
    entry = _media_groups.pop(key, None)
    if not entry or not entry["photos"]:
        return
    uid = entry["uid"]
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].extend(entry["photos"])
        if entry["caption"]:
            buf["texts"].append(entry["caption"])
        buf["deadline"] = time.time() + COLLECT_WINDOW
    else:
        _buffers[uid] = {
            "texts": [entry["caption"]] if entry["caption"] else [],
            "photos": list(entry["photos"]),
            "deadline": time.time() + COLLECT_WINDOW,
            "chat_id": entry["chat_id"],
        }
        try:
            await ctx.bot.send_message(
                entry["chat_id"],
                "Nhận ảnh! Anh gửi thêm text mô tả giúp em nhé 📥")
        except Exception:
            pass
        asyncio.create_task(_flush_after(uid, ctx))


async def _handle_photo_answer(update, ctx, awaiting, file_id, caption):
    """User sent a photo while the bot was asking for missing photos:
    attach it to the pending listing instead of starting a new one."""
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    listing_id = awaiting["listing_id"]
    listing = db.get_listing(listing_id)
    if not listing:
        ctx.user_data.pop("awaiting", None)
        return
    photos = listing["photo_file_ids"] + [file_id]
    raw = listing["raw_text"]
    if caption:
        raw = (raw + "\n" + caption).strip()
    db.update_listing(listing_id, photo_file_ids=photos, raw_text=raw)

    remaining = [m for m in awaiting.get("remaining", [])]
    parsed = listing["parsed"]
    still = []
    if "price_vnd" not in parsed:
        still.append("price_vnd")
    if "primary_phone" not in parsed:
        still.append("primary_phone")
    if len(photos) < 1:
        still.append("photos")
    still = [s for s in still if s in remaining][:config.MAX_MISSING_QUESTIONS]

    db.update_listing(listing_id, missing_fields=still)
    await natural_delay(update)
    if still:
        await _ask_missing(chat_id, uid, listing_id, still[0], ctx,
                           remaining=still[1:])
    else:
        ctx.user_data.pop("awaiting", None)
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        await update.message.reply_text(
            f"Đã nhận ảnh ✓ (tổng {len(photos)} ảnh)")
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(0.5)
        await update.message.reply_text(
            "Xong! Em đã lưu tin rồi nhé ✓",
            reply_markup=MENU_KB,
        )


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    file_id = msg.photo[-1].file_id  # largest size
    caption = (msg.caption or "").strip()

    # 1. answering a missing-field question that wants photos?
    awaiting = ctx.user_data.get("awaiting")
    if awaiting and awaiting.get("field") == "photos":
        await _handle_photo_answer(update, ctx, awaiting, file_id, caption)
        return

    # 2. part of an album? buffer by media_group_id, debounce, then merge
    mg_id = msg.media_group_id
    if mg_id:
        key = f"{uid}:{mg_id}"
        entry = _media_groups.get(key)
        if entry and entry.get("task"):
            entry["task"].cancel()
        if entry is None:
            entry = {"photos": [], "caption": "", "uid": uid,
                     "chat_id": msg.chat.id, "task": None}
            _media_groups[key] = entry
        entry["photos"].append(file_id)
        if caption and not entry["caption"]:
            entry["caption"] = caption
        entry["task"] = asyncio.create_task(_flush_media_group(key, ctx))
        return

    # 3. single photo — caption goes through the same pipeline as text
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].append(file_id)
        if caption:
            buf["texts"].append(caption)
        buf["deadline"] = time.time() + COLLECT_WINDOW
    else:
        _buffers[uid] = {"texts": [caption] if caption else [],
                         "photos": [file_id],
                         "deadline": time.time() + COLLECT_WINDOW,
                         "chat_id": msg.chat.id}
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
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(1)
        await update.message.reply_text(
            "Xong! Em đã lưu tin rồi nhé ✓",
            reply_markup=MENU_KB,
        )


# ---------------------------------------------------------------- advanced query

def _describe_filters(f):
    """Human-readable Vietnamese description of active filters."""
    bits = []
    br = f.get("bedrooms")
    if br == 0.0:
        bits.append("studio")
    elif br:
        bits.append(f"{int(br)}PN")
    if "min_price" in f and "max_price" in f:
        bits.append(f"giá {fmt_price(f['min_price'])}–{fmt_price(f['max_price'])}")
    elif "max_price" in f:
        bits.append(f"dưới {fmt_price(f['max_price'])}")
    elif "min_price" in f:
        bits.append(f"trên {fmt_price(f['min_price'])}")
    if f.get("district"):
        bits.append(f"ở {f['district']}")
    if f.get("building_name"):
        bits.append(f"tòa {f['building_name']}")
    if f.get("pet_friendly") is True:
        bits.append("cho pet")
    if f.get("property_type"):
        bits.append(f.get("property_type"))
    if f.get("status") == "rented":
        bits.append("đã cho thuê")
    elif f.get("status") == "active":
        bits.append("còn trống")
    return ", ".join(bits) if bits else "tất cả tin"


async def _handle_query(update, ctx, uid, text):
    """Natural-language listing search, e.g. 'cho xem tin 2PN dưới 15tr'."""
    filters = listing_parser.parse_query(text)
    await natural_delay(update)
    if not filters:
        await update.message.reply_text(
            "Em chưa hiểu anh muốn lọc kiểu gì 😅 Anh thử kiểu "
            "'cho xem tin 2PN dưới 15tr' hoặc bấm 📋 Tin của tôi nhé.",
            reply_markup=MENU_KB,
        )
        return
    # store for pagination
    ctx.user_data["last_query"] = filters
    items = db.search_listings(uid, filters, limit=5, offset=0)
    desc = _describe_filters(filters)
    if not items:
        await update.message.reply_text(
            f"Em không tìm thấy tin nào ({desc}) anh ơi. "
            "Thử nới điều kiện ra nhé?",
            reply_markup=MENU_KB,
        )
        return
    lines = [f"<b>🔍 Kết quả ({desc}):</b>"]
    kb = []
    for i, l in enumerate(items, start=1):
        lines.append(f"{i}. {listing_line(l)}")
        kb.append([InlineKeyboardButton(
            f"{i}. Chi tiết", callback_data=f"qdetail:{l['id']}:0")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await update.message.reply_text("\n".join(lines), parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(kb))


async def show_query_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Detail view from a query result — back goes to menu (query not persisted)."""
    q = update.callback_query
    await q.answer()
    listing_id = q.data.split(":", 1)[1].rsplit(":", 1)[0]  # qdetail:tg:<hex>:0
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    p = l["parsed"]
    lines = [
        f"<b>{listing_line(l)}</b>",
        f"📸 {len(l['photo_file_ids'])} ảnh | 👀 {l['view_count']} lượt xem",
        f"📅 Đăng {rel_time(l['created_at'])}",
        f"Trạng thái: {STATUS_EMOJI.get(l['status'], '')} {l['status']}",
    ]
    if p.get("area_m2"):
        lines.append(f"Diện tích: {p['area_m2']:g}m²")
    if p.get("furnishing"):
        lines.append(f"Nội thất: {p['furnishing']}")
    kb = []
    if l["status"] not in ("rented", "deleted"):
        kb.append([InlineKeyboardButton("🔑 Đánh dấu đã cho thuê",
                                       callback_data=f"qrented:{listing_id}")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def mark_query_rented(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    listing_id = q.data.split(":", 1)[1]  # qrented:tg:<hex>
    db.set_listing_status(listing_id, "rented", changed_by="broker")
    await natural_delay(update)
    await q.edit_message_text("Đã đánh dấu cho thuê 🔑 Chúc mừng anh!",
                              reply_markup=MENU_KB)


# ---------------------------------------------------------------- my listings

async def show_my_listings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    # callback: menu:list:{page}:{filter_str}  e.g. menu:list:0:s:a,br:2
    rest = q.data[len("menu:list:"):]
    parts = rest.split(":", 1)
    page = int(parts[0]) if parts[0].isdigit() else 0
    fstr = parts[1] if len(parts) > 1 else "s:a"
    f = _parse_filter_str(fstr)
    if "s" not in f:
        f["s"] = "a"
    fstr = _build_filter_str(f) or "s:a"

    per = 5
    sf = _filters_to_search(f)
    total = db.count_search(uid, sf)
    items = db.search_listings(uid, sf, limit=per, offset=page * per)

    # header with active filter description
    desc = _describe_ui_filters(f)
    has_extra = any(k in f for k in ("br", "pr", "di"))
    if not items:
        msg = ("Anh chưa có tin nào. Bấm 📝 Gửi tin mới để bắt đầu nhé!"
               if total == 0 and not has_extra else
               f"Không có tin nào khớp bộ lọc ({desc}) anh ơi. "
               "Thử nới điều kiện ra nhé?")
        kb = [[InlineKeyboardButton("❌ Xóa hết lọc",
                                    callback_data="menu:list:0:s:a")]] \
            if has_extra else None
        await q.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup(kb) if kb else MENU_KB)
        return

    lines = [f"<b>📋 Tin của anh ({total}):</b>"]
    if has_extra or f.get("s", "a") != "a":
        lines.append(f"🔍 Đang lọc: {desc}")
    kb = []

    # row 1: status quick filters
    srow = []
    for key, code in (("all", "a"), ("active", "t"), ("rented", "r")):
        label = LIST_FILTERS[key]["label"]
        mark = "● " if f.get("s", "a") == code else ""
        nf = dict(f)
        nf["s"] = code
        srow.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"menu:list:0:{_build_filter_str(nf)}"))
    kb.append(srow)

    # row 2: attribute filters
    arow = []
    for label, kind in (("🛏️ PN", "br"), ("💰 Giá", "pr"), ("📍 Khu vực", "di")):
        mark = "● " if f.get(kind) else ""
        arow.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"flt:{kind}:{page}:{fstr}"))
    kb.append(arow)

    # listings (2-line display, ━━━ separator)
    for i, l in enumerate(items, start=page * per + 1):
        if i > page * per + 1:
            lines.append("━━━━━━━━━━━━")
        lines.append(f"{i}. {listing_line(l)}")
        kb.append([InlineKeyboardButton(
            f"{i}. Chi tiết", callback_data=f"detail:{l['id']}:{page}:{fstr}")])

    # clear-all row (only when extra filters active)
    if has_extra:
        kb.append([InlineKeyboardButton("❌ Xóa hết lọc",
                                        callback_data="menu:list:0:s:a")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️", callback_data=f"menu:list:{page-1}:{fstr}"))
    if (page + 1) * per < total:
        nav.append(InlineKeyboardButton(
            "➡️", callback_data=f"menu:list:{page+1}:{fstr}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await natural_delay(update)
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


# ---------------------------------------------------------------- filter pickers

async def show_filter_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show bedroom / price / district picker. callback: flt:{kind}:{page}:{fstr}"""
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":", 3)  # flt, kind, page, fstr
    kind = parts[1]
    page = parts[2]
    fstr = parts[3] if len(parts) > 3 else "s:a"
    f = _parse_filter_str(fstr)

    kb = []
    if kind == "br":
        title = "Chọn số phòng ngủ:"
        for code, label in BR_OPTIONS:
            mark = "● " if f.get("br") == code else ""
            nf = dict(f)
            nf["br"] = code
            kb.append([InlineKeyboardButton(
                f"{mark}{label}",
                callback_data=f"menu:list:0:{_build_filter_str(nf)}")])
    elif kind == "pr":
        title = "Chọn khoảng giá:"
        for code, (label, _, _) in PRICE_RANGES.items():
            mark = "● " if f.get("pr") == code else ""
            nf = dict(f)
            nf["pr"] = code
            kb.append([InlineKeyboardButton(
                f"{mark}{label}",
                callback_data=f"menu:list:0:{_build_filter_str(nf)}")])
    elif kind == "di":
        title = "Chọn khu vực:"
        for code, label in DISTRICT_CODES.items():
            mark = "● " if f.get("di") == code else ""
            nf = dict(f)
            nf["di"] = code
            kb.append([InlineKeyboardButton(
                f"{mark}{label}",
                callback_data=f"menu:list:0:{_build_filter_str(nf)}")])
    else:
        return

    # "clear this filter" option
    if f.get(kind):
        nf = dict(f)
        nf.pop(kind, None)
        kb.append([InlineKeyboardButton(
            "❌ Bỏ lọc này",
            callback_data=f"menu:list:0:{_build_filter_str(nf) or 's:a'}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"menu:list:{page}:{fstr}")])
    await q.edit_message_text(title, reply_markup=InlineKeyboardMarkup(kb))


async def show_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "detail")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    p = l["parsed"]
    lines = [
        f"<b>{listing_line(l)}</b>",
        f"📸 {len(l['photo_file_ids'])} ảnh | 👀 {l['view_count']} lượt xem",
        f"📅 Đăng {rel_time(l['created_at'])}",
        f"Trạng thái: {STATUS_EMOJI.get(l['status'], '')} {l['status']}",
    ]
    if p.get("area_m2"):
        lines.append(f"Diện tích: {p['area_m2']:g}m²")
    if p.get("furnishing"):
        lines.append(f"Nội thất: {p['furnishing']}")
    kb = []
    if l["status"] not in ("rented", "deleted"):
        kb.append([InlineKeyboardButton("🔑 Đánh dấu đã cho thuê",
                                       callback_data=f"rented:{listing_id}:{page}:{filt}")])
    kb.append([InlineKeyboardButton("🗑 Xoá tin",
                                    callback_data=f"delete:{listing_id}:{page}:{filt}")])
    kb.append([InlineKeyboardButton("⬅️ Danh sách",
                                    callback_data=f"menu:list:{page}:{filt}")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def mark_rented(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "rented")
    if listing_id:
        db.set_listing_status(listing_id, "rented", changed_by="broker")
    await natural_delay(update)
    await q.edit_message_text("Đã đánh dấu cho thuê 🔑 Chúc mừng anh!",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data=f"menu:list:{page}:{filt}")]]))


async def delete_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "delete")
    if listing_id:
        db.set_listing_status(listing_id, "deleted", changed_by="broker")
    await q.edit_message_text("Đã xoá tin 🗑",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data=f"menu:list:{page}:{filt}")]]))


# ---------------------------------------------------------------- write FB post

# user_ids currently in "write post" mode: after intake completes,
# go to language selection instead of the normal "done" message.
_write_post_pending = set()

PTYPE_VI = {"apartment": "căn hộ", "house": "nhà", "villa": "villa",
            "room": "phòng", "studio": "studio"}
PTYPE_EN = {"apartment": "apartment", "house": "house", "villa": "villa",
            "room": "room", "studio": "studio"}
PTYPE_KO = {"apartment": "아파트", "house": "주택", "villa": "빌라",
            "room": "방", "studio": "스튜디오"}
PTYPE_ZH = {"apartment": "公寓", "house": "别墅", "villa": "别墅",
            "room": "房间", "studio": "单间"}
PTYPE_RU = {"apartment": "квартира", "house": "дом", "villa": "вилла",
            "room": "комната", "studio": "студия"}
FURN_VI = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}
FURN_EN = {"full": "Fully furnished", "basic": "Basic furnishing",
           "empty": "Unfurnished"}
FURN_KO = {"full": "풀옵션", "basic": "기본옵션", "empty": "옵션없음"}
FURN_ZH = {"full": "全配", "basic": "简配", "empty": "空房"}
FURN_RU = {"full": "с мебелью", "basic": "частично", "empty": "без мебели"}


def generate_post(listing, lang="vi"):
    """Build a Facebook-ready post from a listing dict.

    lang: 'vi' | 'en' | 'ko' | 'zh' | 'ru' | 'both' (vi+en) | 'all'.
    Only includes fields that have values.
    """
    p = listing["parsed"]

    br = p.get("bedrooms")
    if br == 0.0:
        br_vi, br_en, br_ko, br_zh, br_ru = ("studio", "studio",
                                            "스튜디오", "单间", "студия")
    elif br:
        n = int(br)
        br_vi, br_en = f"{n}PN", f"{n}BR"
        br_ko, br_zh, br_ru = f"{n}BR", f"{n}房", f"{n}-комн."
    else:
        br_vi = br_en = br_ko = br_zh = br_ru = ""

    ptype = p.get("property_type") or ""
    ptype_vi = PTYPE_VI.get(ptype, "căn hộ")
    ptype_en = PTYPE_EN.get(ptype, "apartment")
    ptype_ko = PTYPE_KO.get(ptype, "아파트")
    ptype_zh = PTYPE_ZH.get(ptype, "公寓")
    ptype_ru = PTYPE_RU.get(ptype, "квартира")

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
    price_ko = f"{fmt_price(price)} VND/월" if price else ""
    price_zh = f"{fmt_price(price)} VND/月" if price else ""
    price_ru = f"{fmt_price(price)} VND/мес" if price else ""

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

    def build_ko():
        title_br = f" {br_ko}" if br_ko else ""
        lines = [f"🏠 임대{title_br} {ptype_ko}"
                 + (f" - {loc}" if loc else "")]
        lines.append("")
        if address:
            lines.append(f"📍 위치: {address}")
        if price_ko:
            lines.append(f"💰 가격: {price_ko}")
        specs = []
        if br_ko:
            specs.append(f"🛏️ {br_ko}")
        if ba:
            specs.append(f"🛁 {int(ba)} BA")
        if area:
            specs.append(f"📐 {area:g}sqm")
        if specs:
            lines.append(" | ".join(specs))
        if furn and furn in FURN_KO:
            lines.append(f"🛋️ 가구: {FURN_KO[furn]}")
        if pet is True:
            lines.append("🐾 반려동물 가능")
        elif pet is False:
            lines.append("🐾 반려동물 불가")
        lines.append("")
        if phone:
            lines.append(f"📞 연락처: {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_zh():
        title_br = f" {br_zh}" if br_zh else ""
        lines = [f"🏠 出租{title_br}{ptype_zh}"
                 + (f" - {loc}" if loc else "")]
        lines.append("")
        if address:
            lines.append(f"📍 地址: {address}")
        if price_zh:
            lines.append(f"💰 价格: {price_zh}")
        specs = []
        if br_zh:
            specs.append(f"🛏️ {br_zh}")
        if ba:
            specs.append(f"🛁 {int(ba)} 卫")
        if area:
            specs.append(f"📐 {area:g}平米")
        if specs:
            lines.append(" | ".join(specs))
        if furn and furn in FURN_ZH:
            lines.append(f"🛋️ 家具: {FURN_ZH[furn]}")
        if pet is True:
            lines.append("🐾 可养宠物")
        elif pet is False:
            lines.append("🐾 不可养宠物")
        lines.append("")
        if phone:
            lines.append(f"📞 联系: {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_ru():
        title_br = f" {br_ru}" if br_ru else ""
        lines = [f"🏠 АРЕНДА{title_br} {ptype_ru}"
                 + (f" - {loc}" if loc else "")]
        lines.append("")
        if address:
            lines.append(f"📍 Адрес: {address}")
        if price_ru:
            lines.append(f"💰 Цена: {price_ru}")
        specs = []
        if br_ru:
            specs.append(f"🛏️ {br_ru}")
        if ba:
            specs.append(f"🛁 {int(ba)} ван.")
        if area:
            specs.append(f"📐 {area:g}м²")
        if specs:
            lines.append(" | ".join(specs))
        if furn and furn in FURN_RU:
            lines.append(f"🛋️ Мебель: {FURN_RU[furn]}")
        if pet is True:
            lines.append("🐾 Можно с животными")
        elif pet is False:
            lines.append("🐾 Без животных")
        lines.append("")
        if phone:
            lines.append(f"📞 Контакт: {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    if lang == "en":
        return build_en()
    if lang == "ko":
        return build_ko()
    if lang == "zh":
        return build_zh()
    if lang == "ru":
        return build_ru()
    if lang == "both":
        return build_vi() + "\n\n---\n\n" + build_en()
    if lang == "all":
        sep = "\n\n---\n\n"
        return (build_vi() + sep + build_en() + sep + build_ko() + sep
                + build_zh() + sep + build_ru())
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
    listing_id = q.data.split(":", 1)[1]  # "write:tg:<hex>"
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇻🇳 Việt", callback_data=f"writelang:{listing_id}:vi"),
         InlineKeyboardButton("🇬🇧 Anh", callback_data=f"writelang:{listing_id}:en")],
        [InlineKeyboardButton("🇰🇷 Hàn", callback_data=f"writelang:{listing_id}:ko"),
         InlineKeyboardButton("🇨🇳 Trung", callback_data=f"writelang:{listing_id}:zh")],
        [InlineKeyboardButton("🇷🇺 Nga", callback_data=f"writelang:{listing_id}:ru"),
         InlineKeyboardButton("🌐 Tất cả", callback_data=f"writelang:{listing_id}:all")],
        [InlineKeyboardButton("⬅️ Chọn căn khác",
                              callback_data="menu:write")],
    ])
    await natural_delay(update)
    await q.edit_message_text(
        f"Căn {listing_line(l)} này viết tiếng nào anh? 😊",
        parse_mode="HTML", reply_markup=kb)


async def on_write_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Generate the FB post and send it as a copyable message."""
    q = update.callback_query
    await q.answer()
    # "writelang:tg:<hex>:<lang>"
    rest = q.data.split(":", 1)[1]
    listing_id, lang = rest.rsplit(":", 1)
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
        [InlineKeyboardButton("🇻🇳 Việt", callback_data=f"writelang:{listing_id}:vi"),
         InlineKeyboardButton("🇬🇧 Anh", callback_data=f"writelang:{listing_id}:en")],
        [InlineKeyboardButton("🇰🇷 Hàn", callback_data=f"writelang:{listing_id}:ko"),
         InlineKeyboardButton("🇨🇳 Trung", callback_data=f"writelang:{listing_id}:zh")],
        [InlineKeyboardButton("🇷🇺 Nga", callback_data=f"writelang:{listing_id}:ru"),
         InlineKeyboardButton("🌐 Tất cả", callback_data=f"writelang:{listing_id}:all")],
    ])
    await asyncio.sleep(1)
    if l:
        await ctx.bot.send_message(
            chat_id,
            f"Nhận tin xong! Căn {listing_line(l)} này viết tiếng nào anh? 😊",
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
    elif data.startswith("flt:"):
        await show_filter_picker(update, ctx)
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
    elif data.startswith("qdetail:"):
        await show_query_detail(update, ctx)
    elif data.startswith("rented:"):
        await mark_rented(update, ctx)
    elif data.startswith("qrented:"):
        await mark_query_rented(update, ctx)
    elif data.startswith("delete:"):
        await delete_listing(update, ctx)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var first. See README.md")
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    log.info("Linh is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
