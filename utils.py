"""Shared helpers, constants, and state for TrueNest bot modules."""
import asyncio
import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import ContextTypes

import config
import db
import parser as listing_parser
from normalize import normalize_phone

log = logging.getLogger("linh")

log = logging.getLogger("linh")

# ---------------------------------------------------------------- helpers

MENU_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📝 Gửi tin mới", callback_data="menu:new")],
    [InlineKeyboardButton("📋 Tin của tôi", callback_data="menu:list:0:s:a")],
    [InlineKeyboardButton("✍️ Viết tin FB", callback_data="menu:write")],
    [InlineKeyboardButton("👥 Khách hàng", callback_data="menu:clients")],
    [InlineKeyboardButton("📅 Lịch xem", callback_data="menu:viewings")],
    [InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu:help")],
])

# client (khách hàng) statuses

CLIENT_STATUS_EMOJI = {
    "new": "🆕", "viewing": "👀", "negotiating": "🤝",
    "deposited": "💰", "rented": "✅", "cancelled": "❌",
}

CLIENT_STATUS_LABEL = {
    "new": "mới", "viewing": "đang xem", "negotiating": "đàm phán",
    "deposited": "đã cọc", "rented": "đã thuê", "cancelled": "hủy",
}

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


def get_pronoun(uid, broker=None):
    """'anh' or 'chị' for this broker. Defaults to 'anh'."""
    b = broker if broker is not None else db.get_broker(uid)
    return (b or {}).get("pronoun") or "anh"

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

# "add photos to existing listing" buffer:
# {user_id: {"listing_id": ..., "photos": [], "captions": [], "task": ...}}
# Photos are buffered in memory and committed to the DB once after a quiet
# window, so rapid multi-photo sends never race on read-modify-write.

_addphoto_pending = {}

ADD_PHOTO_WINDOW = 3  # seconds of quiet before committing added photos


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

_PTYPE_SHORT = {"apartment": "Căn hộ", "house": "Nhà", "villa": "Villa",
                "room": "Phòng", "studio": "Studio"}

_FURN_SHORT = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}


def _confirm_summary(l, pn="anh", phone_note=""):
    """Full pre-save summary of every parsed field.

    Returns (text, keyboard_or_None). Unknown/empty fields are skipped.
    keyboard is None when nothing was parsed (fallback prompt instead).
    """
    p = l.get("parsed") or {}
    photos = l.get("photo_file_ids") or []
    lines = ["Em tóm tắt lại tin này nhé:", ""]
    has = False

    br = p.get("bedrooms")
    ptype = p.get("property_type")
    if br == 0.0 or ptype == "studio":
        lines.append("🏠 Loại: Studio")
        has = True
    elif br:
        lines.append(f"🏠 Loại: {_PTYPE_SHORT.get(ptype, 'Căn')} {int(br)}PN")
        has = True
    elif ptype:
        lines.append(f"🏠 Loại: {_PTYPE_SHORT.get(ptype, ptype)}")
        has = True

    addr_bits = [x for x in (p.get("building_name"), p.get("street"),
                             p.get("district")) if x]
    try:
        if p.get("floor_number"):
            addr_bits.append(f"tầng {int(p['floor_number'])}")
    except (TypeError, ValueError):
        pass
    if p.get("unit_number"):
        addr_bits.append(f"căn {p['unit_number']}")
    if addr_bits:
        lines.append(f"📍 Địa chỉ: {', '.join(addr_bits)}")
        has = True

    if p.get("price_vnd"):
        lines.append(f"💰 Giá: {fmt_price(p['price_vnd'])}/tháng")
        has = True

    if p.get("area_m2"):
        lines.append(f"📐 Diện tích: {p['area_m2']:g}m²")
        has = True

    bb = []
    if br is not None and br != 0.0:
        bb.append(f"🛏️ Phòng ngủ: {int(br)}")
    if p.get("bathrooms"):
        bb.append(f"🛁 Phòng tắm: {int(p['bathrooms'])}")
    if bb:
        lines.append(" | ".join(bb))
        has = True

    if p.get("furnishing"):
        lines.append(f"🛋️ Nội thất: "
                     f"{_FURN_SHORT.get(p['furnishing'], p['furnishing'])}")
        has = True

    if p.get("pet_friendly") is True:
        lines.append("🐾 Pet: Cho phép")
        has = True
    elif p.get("pet_friendly") is False:
        lines.append("🐾 Pet: Không cho phép")
        has = True

    if p.get("primary_phone"):
        lines.append(f"📱 SĐT: {p['primary_phone']}{phone_note}")
        has = True

    if p.get("telegram_username"):
        lines.append(f"✈️ Telegram: @{p['telegram_username']}")
        has = True

    av = p.get("availability_note")
    if av:
        lines.append(f"📅 Tình trạng: {'Còn trống' if av == 'available' else av}")
        has = True

    if photos:
        lines.append(f"📸 Ảnh: {len(photos)} ảnh")
        has = True

    if not has:
        return ("Em chưa bóc được thông tin gì từ tin này 😅 "
                f"{pn} gửi thêm giúp em nhé? (giá, số phòng ngủ, địa chỉ...)",
                None)
    lines += ["", f"Đúng hết chưa {pn}?"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Đúng rồi, lưu tin",
                              callback_data=f"cfm:save:{l['id']}")],
        [InlineKeyboardButton("✏️ Sửa",
                              callback_data=f"cfm:edit:{l['id']}")],
    ])
    return "\n".join(lines), kb


