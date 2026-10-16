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
from normalize import normalize_phone

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
    "rented": "🔴", "negotiating": "🤝", "deposited": "💰",
    "expired": "📦",
}

# listing list filters for "📋 Tin của tôi"
LIST_FILTERS = {
    "all": {"label": "Tất cả", "statuses": None},          # None = all except deleted
    "active": {"label": "Đang trống", "statuses": ("draft", "pending_info", "submitted")},
    "inactive": {"label": "Không còn trống",
                 "statuses": ("rented", "negotiating", "deposited")},
}

# status labels for display
STATUS_LABEL = {
    "draft": "nháp", "pending_info": "thiếu info", "submitted": "đang trống",
    "rented": "đã cho thuê", "negotiating": "đang đàm phán", "deposited": "đã cọc",
    "expired": "hết hạn", "deleted": "đã xoá",
}

# completeness scoring — weights sum to 100. Only uses the listing's own
# fields + timestamps (no market data needed).
COMPLETENESS_FIELDS = {
    'price_vnd': (20, "Giá thuê"),
    'primary_phone': (15, "SĐT liên hệ"),
    'bedrooms': (10, "Số phòng ngủ"),
    'district': (10, "Khu vực"),
    'area_m2': (10, "Diện tích"),
    'photos': (15, "Ảnh (tối thiểu 3)"),
    'furnishing': (5, "Nội thất"),
    'pet_friendly': (5, "Chính sách pet"),
    'description': (10, "Mô tả chi tiết"),
}


def completeness_score(listing):
    """0-100% based on filled fields. Returns (score, [missing labels])."""
    p = listing.get("parsed") or {}
    score = 0
    missing = []
    checks = {
        'price_vnd': bool(p.get('price_vnd')),
        'primary_phone': bool(p.get('primary_phone')),
        'bedrooms': p.get('bedrooms') is not None,
        'district': bool(p.get('district')),
        'area_m2': bool(p.get('area_m2')),
        'photos': len(listing.get('photo_file_ids') or []) >= 3,
        'furnishing': bool(p.get('furnishing')),
        'pet_friendly': p.get('pet_friendly') is not None,
        'description': len(listing.get('raw_text') or '') > 50,
    }
    for key, (weight, label) in COMPLETENESS_FIELDS.items():
        if checks[key]:
            score += weight
        else:
            missing.append(label)
    return score, missing


def freshness_badge(created_at):
    """(emoji, label) for listing age. No market data needed."""
    age_d = (time.time() - created_at) / 86400
    if age_d < 3:
        label = "mới" if age_d < 1 else f"{int(age_d)} ngày"
        return "🟢", label
    if age_d <= 14:
        return "🟡", f"{int(age_d)} ngày"
    if age_d <= 30:
        return "🟠", f"{int(age_d)} ngày"
    return "🔴", f"{int(age_d)} ngày"

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
        sf["status"] = "inactive"   # rented + negotiating + deposited
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
        bits.append("không còn trống")
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


PROCESSING_HINTS = [
    "Anh đợi em 1 xíu nhé, em đang xử lý... ⏳",
    "Để em xem nào... 🔍",
    "Sắp xong rồi ạ! ✨",
    "Em đang làm đây, anh đợi xíu nhé 💪",
]


async def react_heart(message):
    """React ❤️ to a user message. Never breaks the flow."""
    try:
        await message.set_reaction("❤️")
    except Exception:
        pass


async def maybe_send_hint(message, chance=0.3):
    """Occasionally send a processing hint to feel more human."""
    if random.random() < chance:
        try:
            await message.reply_text(random.choice(PROCESSING_HINTS))
        except Exception:
            pass


async def maybe_send_hint_to_chat(ctx, chat_id, chance=0.3):
    """Same as maybe_send_hint, when we only have chat_id (no message)."""
    if random.random() < chance:
        try:
            await ctx.bot.send_message(chat_id, random.choice(PROCESSING_HINTS))
        except Exception:
            pass


def fmt_price(v):
    if not v:
        return "?"
    if v >= 1_000_000:
        return f"{v / 1_000_000:g}tr"
    return f"{int(v):,}".replace(",", ".")


def listing_line(l):
    """Two-line compact display with essential info + freshness:
    🏠 2PN An Thượng, 12tr/tháng 🟢 2 ngày
    📐 52m² | 🛋️ Full NT | 🐾 Pet OK | 👀 23 | ✅ đang trống
    """
    p = l["parsed"]
    br = p.get("bedrooms")
    br_s = "studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = p.get("building_name") or p.get("district") or "?"
    price = fmt_price(p.get("price_vnd"))
    fresh_emoji, fresh_label = freshness_badge(l["created_at"])

    line1 = f"🏠 {br_s} {loc}, {price}/tháng {fresh_emoji} {fresh_label}"

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
    "/edit — sửa thông tin tin đã đăng\n"
    "/help — xem hướng dẫn này\n"
    "/contacts — xem / sửa thông tin liên hệ\n"
    "/phone — đổi SĐT nhanh"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    broker = db.get_or_create_broker(u.id, u.username, u.full_name)
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
    # onboarding: collect phone (then name) once, reuse for all listings
    if not broker.get("phone"):
        ctx.user_data["onboarding"] = {"step": "phone"}
        await asyncio.sleep(0.8)
        await update.message.reply_text(
            "Cho em xin SĐT của anh để có khách em liên hệ cho dễ nhé? 📱",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Bỏ qua", callback_data="onboard:skip_phone")]]),
        )
    elif not broker.get("name"):
        ctx.user_data["onboarding"] = {"step": "name"}
        await asyncio.sleep(0.8)
        await update.message.reply_text("Anh tên gì để em tiện xưng hô ạ? 😊")


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


# ---------------------------------------------------------------- onboarding & contacts

async def _handle_onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             ob: dict, text: str):
    """Collect broker phone (then name) once at onboarding."""
    uid = update.effective_user.id
    step = ob.get("step")

    if step == "phone":
        if text.strip().lower() in ("bỏ qua", "bo qua", "skip"):
            await _onboard_ask_name(update, ctx)
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
        await _onboard_ask_name(update, ctx)

    elif step == "name":
        name = text.strip()[:50]
        if name:
            db.update_broker(uid, name=name)
        ctx.user_data.pop("onboarding", None)
        await natural_delay(update)
        greet = f"Ok anh {name} nhé! 😊" if name else "Dạ ok anh! 😊"
        await update.message.reply_text(
            f"{greet} Anh cần gì cứ bảo em.",
            reply_markup=MENU_KB,
        )


async def _onboard_ask_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["onboarding"] = {"step": "name"}
    await asyncio.sleep(0.8)
    await update.message.reply_text("Anh tên gì để em tiện xưng hô ạ? 😊")


async def onboard_skip_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["onboarding"] = {"step": "name"}
    await q.edit_message_text(
        "Dạ ok anh, để sau cũng được ạ 😊\n\nAnh tên gì để em tiện xưng hô ạ?")


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
    return (
        "📇 <b>THÔNG TIN CỦA ANH</b>\n\n"
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

    # auto-fill broker's saved phone when the text has none (per-listing
    # override: if the text itself contains a phone, it wins for this listing)
    broker_phone = db.get_broker_phone(uid)
    phone_autofilled = False
    if broker_phone and not result["fields"].get("primary_phone"):
        result["fields"]["primary_phone"] = broker_phone
        result["missing"] = [m for m in result["missing"]
                             if m != "primary_phone"]
        phone_autofilled = True

    await maybe_send_hint_to_chat(ctx, chat_id)
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
    phone_note = f"\n📱 SĐT: {broker_phone} (SĐT của anh)" if phone_autofilled else ""
    await ctx.bot.send_message(chat_id, summary + photo_note + phone_note)

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

    # 1. answering a missing-field question?
    awaiting = ctx.user_data.get("awaiting")
    if awaiting:
        await _handle_answer(update, ctx, awaiting, text)
        return

    # 1b. answering an edit-field prompt?
    editing = ctx.user_data.get("editing")
    if editing:
        await _handle_edit_answer(update, ctx, editing, text)
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
    await react_heart(update.message)
    if ctx.user_data.get("onboarding") or ctx.user_data.get("editing_contact"):
        await update.message.reply_text(
            "Anh trả lời tin nhắn trên giúp em trước nhé? 😊")
        return
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
            # save to broker profile too (for future auto-fill)
            db.update_broker(uid, phone=phone)
            if not (db.get_broker(uid) or {}).get("zalo"):
                db.update_broker(uid, zalo=phone)
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
    await maybe_send_hint(update.message)
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
    if l["status"] not in ("rented", "negotiating", "deposited", "deleted"):
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
    for key, code in (("all", "a"), ("active", "t"), ("inactive", "r")):
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


def parse_status_cb(data):
    """Parse 'setstatus:tg:<hex>:<new_status>:<page>:<filter_str>'.
    Returns (listing_id, new_status, page, filter_str)."""
    import re as _re
    rest = data[len("setstatus:"):]
    m = _re.match(r"^(tg:[0-9a-f]+):([a-z_]+):(\d+)(?::(.+))?$", rest)
    if not m:
        return None, None, "0", "s:a"
    return m.group(1), m.group(2), m.group(3), m.group(4) or "s:a"


def _detail_content(l, page, filt):
    """Build (text, InlineKeyboardMarkup) for a listing detail view."""
    p = l["parsed"]
    lines = [
        f"<b>{listing_line(l)}</b>",
        f"📸 {len(l['photo_file_ids'])} ảnh | 👀 {l['view_count']} lượt xem",
        f"📅 Đăng {rel_time(l['created_at'])}",
        f"Trạng thái: {STATUS_EMOJI.get(l['status'], '')} "
        f"{STATUS_LABEL.get(l['status'], l['status'])}",
    ]
    if p.get("area_m2"):
        lines.append(f"Diện tích: {p['area_m2']:g}m²")
    if p.get("furnishing"):
        lines.append(f"Nội thất: {p['furnishing']}")

    # completeness score + suggestions (listing's own data only)
    score, missing = completeness_score(l)
    lines.append(f"📊 Độ đầy đủ: {score}%")
    if missing:
        lines.append("💡 Để tin nổi bật hơn, anh bổ sung giúp em:")
        for m in missing:
            lines.append(f"   • {m}")

    kb = []

    # refresh prompt for old listings (>30 days)
    age_days = (time.time() - l["created_at"]) / 86400
    if age_days > 30:
        lines.append(
            f"\n💡 Tin này đã {int(age_days)} ngày rồi, "
            "anh có muốn làm mới không?")
        kb.append([InlineKeyboardButton(
            "🔄 Làm mới tin",
            callback_data=f"refresh:{l['id']}:{page}:{filt}")])

    # status toggle buttons
    if l["status"] in ("draft", "pending_info", "submitted"):
        kb.append([
            InlineKeyboardButton(
                "🔑 Đã cho thuê",
                callback_data=f"setstatus:{l['id']}:rented:{page}:{filt}"),
            InlineKeyboardButton(
                "🤝 Đàm phán",
                callback_data=f"setstatus:{l['id']}:negotiating:{page}:{filt}"),
        ])
        kb.append([
            InlineKeyboardButton(
                "💰 Đã cọc",
                callback_data=f"setstatus:{l['id']}:deposited:{page}:{filt}"),
        ])
    elif l["status"] in ("rented", "negotiating", "deposited"):
        kb.append([InlineKeyboardButton(
            "✅ Đánh dấu còn trống",
            callback_data=f"setstatus:{l['id']}:submitted:{page}:{filt}")])

    kb.append([InlineKeyboardButton(
        "✏️ Sửa tin",
        callback_data=f"edit:{l['id']}:{page}:{filt}")])
    kb.append([InlineKeyboardButton(
        "🗑 Xoá tin",
        callback_data=f"delete:{l['id']}:{page}:{filt}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Danh sách",
        callback_data=f"menu:list:{page}:{filt}")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def show_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "detail")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    text, kb = _detail_content(l, page, filt)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def set_status_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle extended status buttons: rented / negotiating / deposited /
    submitted. Re-renders the detail view."""
    q = update.callback_query
    await q.answer()
    listing_id, new_status, page, filt = parse_status_cb(q.data)
    if listing_id and new_status in ("submitted", "rented",
                                     "negotiating", "deposited"):
        db.set_listing_status(listing_id, new_status, changed_by="broker")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    text, kb = _detail_content(l, page, filt)
    await natural_delay(update)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def refresh_listing_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """'Làm mới tin' — bump created_at/updated_at so the listing reads as new."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "refresh")
    if listing_id:
        db.touch_listing(listing_id)
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.", reply_markup=MENU_KB)
        return
    text, kb = _detail_content(l, page, filt)
    await natural_delay(update)
    await q.edit_message_text(
        "Đã làm mới tin ✓ Giờ tin của anh lại hiện như mới!\n\n" + text,
        parse_mode="HTML", reply_markup=kb)


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


# ---------------------------------------------------------------- edit listing

EDIT_FIELDS = [
    ("price_vnd", "💰 Giá thuê"),
    ("primary_phone", "📱 SĐT"),
    ("description", "📝 Mô tả"),
    ("bedrooms", "🛏️ Số phòng ngủ"),
    ("area_m2", "📐 Diện tích"),
    ("location", "📍 Địa chỉ/Khu vực"),
    ("furnishing", "🛋️ Nội thất"),
    ("pet_friendly", "🐾 Thú cưng"),
]


def parse_edit_cb(data, action):
    """Parse edit callbacks. Listing ids contain a colon (tg:<hex>).

    - 'edit:<lid>:<page>[:<filt>]'
    - 'editpick:<lid>'
    - 'editfield:<lid>:<field>:<page>[:<filt>]'
    - 'editval:<lid>:<field>:<val>:<page>[:<filt>]'
    - 'editcancel:<lid>:<page>[:<filt>]'
    Returns dict with keys lid/field/val/page/filt (None when absent).
    """
    import re as _re
    rest = data[len(action) + 1:]
    out = {"lid": None, "field": None, "val": None, "page": "0", "filt": "s:a"}
    if action == "editpick":
        m = _re.match(r"^(tg:[0-9a-f]+)$", rest)
        if m:
            out["lid"] = m.group(1)
        return out
    if action == "editval":
        m = _re.match(
            r"^(tg:[0-9a-f]+):([a-z_]+):([a-z]+):(\d+)(?::(.+))?$", rest)
        if m:
            out.update({"lid": m.group(1), "field": m.group(2),
                        "val": m.group(3), "page": m.group(4),
                        "filt": m.group(5) or "s:a"})
        return out
    if action == "editfield":
        m = _re.match(
            r"^(tg:[0-9a-f]+):([a-z_]+):(\d+)(?::(.+))?$", rest)
        if m:
            out.update({"lid": m.group(1), "field": m.group(2),
                        "page": m.group(3), "filt": m.group(4) or "s:a"})
        return out
    # edit / editcancel
    m = _re.match(r"^(tg:[0-9a-f]+):(\d+)(?::(.+))?$", rest)
    if m:
        out.update({"lid": m.group(1), "page": m.group(2),
                    "filt": m.group(3) or "s:a"})
    return out


async def _show_edit_picker(q, listing_id, page, filt):
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    kb = []
    for field, label in EDIT_FIELDS:
        kb.append([InlineKeyboardButton(
            label,
            callback_data=f"editfield:{listing_id}:{field}:{page}:{filt}")])
    kb.append([InlineKeyboardButton(
        "❌ Hủy",
        callback_data=f"editcancel:{listing_id}:{page}:{filt}")])
    await q.edit_message_text("Anh muốn sửa gì?",
                              reply_markup=InlineKeyboardMarkup(kb))


def _edit_current_text(l, field):
    """'Giá hiện tại là …' line for the edit prompt."""
    p = l["parsed"]
    if field == "price_vnd":
        v = p.get("price_vnd")
        return f"Giá hiện tại là {fmt_price(v)}/tháng." if v else "Hiện chưa có giá."
    if field == "primary_phone":
        v = p.get("primary_phone")
        return f"SĐT hiện tại là {v}." if v else "Hiện chưa có SĐT."
    if field == "bedrooms":
        br = p.get("bedrooms")
        if br == 0.0:
            return "Hiện tại là studio."
        return f"Hiện tại là {int(br)}PN." if br else "Hiện chưa có số PN."
    if field == "area_m2":
        v = p.get("area_m2")
        return f"Diện tích hiện tại là {v:g}m²." if v else "Hiện chưa có diện tích."
    if field == "location":
        addr = ", ".join(x for x in (p.get("building_name"), p.get("street"),
                                     p.get("district")) if x)
        return f"Địa chỉ hiện tại: {addr}." if addr else "Hiện chưa có địa chỉ."
    if field == "furnishing":
        v = p.get("furnishing")
        label = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}.get(v, v)
        return f"Nội thất hiện tại: {label}." if v else "Hiện chưa ghi nội thất."
    if field == "pet_friendly":
        v = p.get("pet_friendly")
        if v is True:
            return "Hiện tại: cho nuôi pet."
        if v is False:
            return "Hiện tại: không nuôi pet."
        return "Hiện chưa ghi chính sách pet."
    if field == "description":
        raw = (l.get("raw_text") or "").strip()
        short = raw[:120] + ("…" if len(raw) > 120 else "")
        return f"Mô tả hiện tại: {short}" if raw else "Hiện chưa có mô tả."
    return ""


_EDIT_QUESTION = {
    "price_vnd": "Anh muốn đổi thành bao nhiêu?",
    "primary_phone": "Anh muốn đổi thành số nào?",
    "description": "Anh gửi mô tả mới cho em nhé?",
    "bedrooms": "Anh muốn đổi thành mấy PN? (ghi 0 nếu là studio)",
    "area_m2": "Anh muốn đổi thành bao nhiêu m²?",
    "location": "Anh muốn đổi địa chỉ thành gì? (VD: The Monarchy, Sơn Trà)",
    "furnishing": "Anh muốn đổi nội thất? (Full / Cơ bản / Trống)",
    "pet_friendly": "Anh muốn đổi chính sách pet?",
}


async def _prompt_edit_field(q, listing_id, field, page, filt, ctx):
    l = db.get_listing(listing_id)
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    ctx.user_data["editing"] = {"listing_id": listing_id, "field": field,
                                "page": page, "filt": filt}
    kb = []
    if field == "pet_friendly":
        kb.append([
            InlineKeyboardButton(
                "🐾 Cho pet",
                callback_data=f"editval:{listing_id}:pet_friendly:yes:{page}:{filt}"),
            InlineKeyboardButton(
                "🚫 Không pet",
                callback_data=f"editval:{listing_id}:pet_friendly:no:{page}:{filt}"),
        ])
    elif field == "furnishing":
        kb.append([
            InlineKeyboardButton(
                "Full",
                callback_data=f"editval:{listing_id}:furnishing:full:{page}:{filt}"),
            InlineKeyboardButton(
                "Cơ bản",
                callback_data=f"editval:{listing_id}:furnishing:basic:{page}:{filt}"),
            InlineKeyboardButton(
                "Trống",
                callback_data=f"editval:{listing_id}:furnishing:empty:{page}:{filt}"),
        ])
    kb.append([InlineKeyboardButton(
        "❌ Giữ nguyên",
        callback_data=f"editcancel:{listing_id}:{page}:{filt}")])
    text = _edit_current_text(l, field) + "\n" + _EDIT_QUESTION[field]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


def _validate_edit(field, text):
    """Returns (value, error_msg). error_msg None when valid."""
    import re as _re
    t = (text or "").strip()
    if field == "price_vnd":
        v, _ = listing_parser.parse_price(t)
        if not v or v <= 0:
            return None, "Giá này em chưa hiểu, anh ghi lại giúp em VD: 13tr ạ?"
        return v, None
    if field == "primary_phone":
        v, _ = listing_parser.parse_phone(t)
        if not v:
            return None, "Số này em chưa nhận ra, anh ghi lại 10 số giúp em nhé?"
        return v, None
    if field == "bedrooms":
        v, _ = listing_parser.parse_bedrooms(t)
        if v is None and _re.fullmatch(r"\d{1,2}", t):
            v = float(t)
        if v is None or not (0 <= v <= 10):
            return None, "Anh ghi số phòng ngủ giúp em VD: 2 (ghi 0 nếu là studio) ạ?"
        return v, None
    if field == "area_m2":
        v, _ = listing_parser.parse_area(t)
        if v is None:
            try:
                v = float(t.replace(",", "."))
            except ValueError:
                v = None
        if v is None or v <= 0:
            return None, "Diện tích này em chưa hiểu, anh ghi lại VD: 52m2 ạ?"
        return v, None
    if field == "location":
        loc = {}
        d, _ = listing_parser.parse_district(t)
        s, _ = listing_parser.parse_street(t)
        b, _ = listing_parser.parse_building(t)
        if d:
            loc["district"] = d
        if s:
            loc["street"] = s
        if b:
            loc["building_name"] = b
        if not loc:
            return None, ("Em chưa nhận ra địa chỉ này, anh ghi rõ hơn giúp em "
                          "VD: The Monarchy, Sơn Trà ạ?")
        return loc, None
    if field == "furnishing":
        v, _ = listing_parser.parse_furnishing(t)
        if not v:
            return None, "Anh chọn giúp em: Full / Cơ bản / Trống ạ?"
        return v, None
    if field == "pet_friendly":
        v, _ = listing_parser.parse_pet(t)
        if v is None:
            return None, "Anh ghi “cho pet” hoặc “không pet” giúp em ạ?"
        return v, None
    if field == "description":
        if not t:
            return None, "Anh gửi mô tả mới cho em nhé?"
        return t, None
    return None, "Em chưa hỗ trợ sửa mục này ạ."


def _edit_confirm_text(field, value):
    if field == "price_vnd":
        return f"Em cập nhật giá thành {fmt_price(value)}/tháng rồi nhé ✓"
    if field == "primary_phone":
        return f"Em cập nhật SĐT thành {value} rồi nhé ✓"
    if field == "description":
        return "Em cập nhật mô tả rồi nhé ✓"
    if field == "bedrooms":
        return ("Em cập nhật thành studio rồi nhé ✓"
                if value == 0.0 else f"Em cập nhật thành {int(value)}PN rồi nhé ✓")
    if field == "area_m2":
        return f"Em cập nhật diện tích thành {value:g}m² rồi nhé ✓"
    if field == "location":
        return "Em cập nhật địa chỉ rồi nhé ✓"
    if field == "furnishing":
        label = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}.get(value, value)
        return f"Em cập nhật nội thất: {label} rồi nhé ✓"
    if field == "pet_friendly":
        return ("Em cập nhật: cho nuôi pet rồi nhé ✓"
                if value else "Em cập nhật: không nuôi pet rồi nhé ✓")
    return "Em cập nhật rồi nhé ✓"


async def _finish_edit(update_or_q, ctx, listing_id, field, value, page, filt,
                       via_callback):
    """Persist edit, clear state, re-render detail with confirmation."""
    db.update_listing_field(listing_id, field, value, changed_by="broker")
    ctx.user_data.pop("editing", None)
    l = db.get_listing(listing_id)
    if not l:
        return
    text, kb = _detail_content(l, page, filt)
    confirm = _edit_confirm_text(field, value)
    if via_callback:
        q = update_or_q
        await natural_delay(q)
        await q.edit_message_text(confirm + "\n\n" + text,
                                  parse_mode="HTML", reply_markup=kb)
    else:
        update = update_or_q
        await natural_delay(update)
        await update.message.reply_text(confirm + "\n\n" + text,
                                        parse_mode="HTML", reply_markup=kb)


async def _handle_edit_answer(update, ctx, editing, text):
    listing_id = editing["listing_id"]
    field = editing["field"]
    value, err = _validate_edit(field, text)
    if err:
        await update.message.reply_text(err)
        return  # stay in editing state
    await _finish_edit(update, ctx, listing_id, field, value,
                       editing["page"], editing["filt"], via_callback=False)


# callbacks from the detail view
async def edit_from_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = parse_edit_cb(q.data, "edit")
    if not c["lid"]:
        return
    await _show_edit_picker(q, c["lid"], c["page"], c["filt"])


async def edit_field_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = parse_edit_cb(q.data, "editfield")
    if not c["lid"] or not c["field"]:
        return
    await _prompt_edit_field(q, c["lid"], c["field"], c["page"], c["filt"], ctx)


async def edit_value_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quick-set buttons: pet yes/no, furnishing full/basic/empty."""
    q = update.callback_query
    await q.answer()
    c = parse_edit_cb(q.data, "editval")
    if not c["lid"] or not c["field"]:
        return
    value = {"yes": True, "no": False}.get(c["val"], c["val"])
    await _finish_edit(q, ctx, c["lid"], c["field"], value,
                       c["page"], c["filt"], via_callback=True)


async def edit_cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = parse_edit_cb(q.data, "editcancel")
    ctx.user_data.pop("editing", None)
    if not c["lid"]:
        return
    l = db.get_listing(c["lid"])
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    text, kb = _detail_content(l, c["page"], c["filt"])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------------- /edit command

async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    items = db.list_broker_listings(u.id, limit=5, offset=0)
    if not items:
        await update.message.reply_text(
            "Anh chưa có tin nào để sửa. Bấm 📝 Gửi tin mới nhé!",
            reply_markup=MENU_KB)
        return
    kb = []
    for i, l in enumerate(items, start=1):
        kb.append([InlineKeyboardButton(
            f"{i}. {listing_line(l)}",
            callback_data=f"editpick:{l['id']}")])
    await update.message.reply_text(
        "Anh muốn sửa tin nào?",
        reply_markup=InlineKeyboardMarkup(kb))


async def edit_pick_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = parse_edit_cb(q.data, "editpick")
    if not c["lid"]:
        return
    await _show_edit_picker(q, c["lid"], "0", "s:a")


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
    await maybe_send_hint(q.message)
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
    elif data == "onboard:skip_phone":
        await onboard_skip_phone(update, ctx)
    elif data.startswith("contact:edit:"):
        await contact_edit_prompt(update, ctx)
    elif data.startswith("editpick:"):
        await edit_pick_cb(update, ctx)
    elif data.startswith("editfield:"):
        await edit_field_cb(update, ctx)
    elif data.startswith("editval:"):
        await edit_value_cb(update, ctx)
    elif data.startswith("editcancel:"):
        await edit_cancel_cb(update, ctx)
    elif data.startswith("edit:"):
        await edit_from_detail(update, ctx)
    elif data.startswith("detail:"):
        await show_detail(update, ctx)
    elif data.startswith("qdetail:"):
        await show_query_detail(update, ctx)
    elif data.startswith("rented:"):
        await mark_rented(update, ctx)
    elif data.startswith("setstatus:"):
        await set_status_cb(update, ctx)
    elif data.startswith("refresh:"):
        await refresh_listing_cb(update, ctx)
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
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("phone", cmd_phone))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    log.info("Linh is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
