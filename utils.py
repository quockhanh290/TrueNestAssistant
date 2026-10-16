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
    [InlineKeyboardButton("📋 Tin của tôi", callback_data="menu:list:0:s:a"),
     InlineKeyboardButton("👥 Khách hàng", callback_data="menu:clients")],
    [InlineKeyboardButton("✍️ Viết tin", callback_data="menu:write"),
     InlineKeyboardButton("📅 Lịch xem", callback_data="menu:viewings")],
    [InlineKeyboardButton("🤝 Liên kết broker", callback_data="menu:match"),
     InlineKeyboardButton("💰 Hoa hồng", callback_data="menu:deals")],
    [InlineKeyboardButton("💬 Mẫu tin nhắn", callback_data="menu:templates"),
     InlineKeyboardButton("💎 Premium", callback_data="menu:premium")],
    [InlineKeyboardButton("📊 Hồ sơ", callback_data="menu:profile"),
     InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu:help")],
])

# client (khách hàng) statuses

CLIENT_STATUS_EMOJI = {
    "new": "🆕", "sent": "📤", "pending_viewing": "⏳",
    "scheduled": "📅", "viewed": "👀", "negotiating": "🤝",
    "deposited": "💰", "contracted": "📝", "rented": "✅",
    "cancelled": "❌",
    # legacy (kept for old rows)
    "viewing": "👀",
}

CLIENT_STATUS_LABEL = {
    "new": "Mới", "sent": "Đã gửi tin", "pending_viewing": "Chờ chốt xem",
    "scheduled": "Đã chốt xem", "viewed": "Đã xem", "negotiating": "Đàm phán",
    "deposited": "Đã cọc", "contracted": "Đã kí HĐ", "rented": "Hoàn thành",
    "cancelled": "Hủy",
    # legacy
    "viewing": "đang xem",
}

# Ordered pipeline for the visual progress bar in client detail
CLIENT_PIPELINE = [
    "new", "sent", "pending_viewing", "scheduled", "viewed",
    "negotiating", "deposited", "contracted", "rented",
]


def client_pipeline_bar(status, full=True):
    """Visual pipeline with current status highlighted.

    full=True (Pro): 10-step pipeline.
    full=False (Free): simplified Mới → Đang xem → Hoàn thành.
    Returns None when the status is Pro-only and full=False (caller then
    shows just the status label).
    """
    if status == "cancelled":
        return "❌ Đã hủy"
    if not full:
        basic = ["new", "viewing", "viewed", "rented"]
        if status not in basic:
            return None
        steps = ["new", "viewing", "rented"]
        labels = {"new": "Mới", "viewing": "Đang xem", "rented": "Hoàn thành"}
        disp = "viewing" if status == "viewed" else status
        cur_idx = steps.index(disp)
        bits = []
        for i, st in enumerate(steps):
            if i < cur_idx:
                bits.append(f"✅ {labels[st]}")
            elif i == cur_idx:
                bits.append(f"👉 <b>{labels[st]}</b>")
            else:
                bits.append(labels[st])
        return " → ".join(bits)
    # map legacy "viewing" to the new "viewed" step for display
    disp = "viewed" if status == "viewing" else status
    bits = []
    cur_idx = CLIENT_PIPELINE.index(disp) if disp in CLIENT_PIPELINE else 0
    for i, st in enumerate(CLIENT_PIPELINE):
        label = CLIENT_STATUS_LABEL[st]
        if i < cur_idx:
            bits.append(f"✅ {label}")
        elif i == cur_idx:
            bits.append(f"👉 <b>{label}</b>")
        else:
            bits.append(label)
    return " → ".join(bits)


# statuses visible to Free tier (basic); the rest are Pro-only
FREE_CLIENT_STATUSES = ("new", "viewing", "rented", "cancelled")

STATUS_EMOJI = {
    "draft": "📝", "pending_info": "⏳", "submitted": "✅",
    "rented": "🔴", "negotiating": "🤝", "deposited": "💰",
    "expired": "📦", "uncertain": "❓",
}

# listing list filters for "📋 Tin của tôi"

LIST_FILTERS = {
    "all": {"label": "Tất cả", "statuses": None},          # None = all except deleted
    "active": {"label": "Đang trống", "statuses": ("draft", "pending_info", "submitted", "uncertain")},
    "inactive": {"label": "Không còn trống",
                 "statuses": ("rented", "negotiating", "deposited")},
}

# status labels for display

STATUS_LABEL = {
    "draft": "nháp", "pending_info": "thiếu info", "submitted": "đang trống",
    "rented": "đã cho thuê", "negotiating": "đang đàm phán", "deposited": "đã cọc",
    "expired": "hết hạn", "deleted": "đã xoá", "uncertain": "ko chắc",
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


# Active listing statuses counted toward profile score
PROFILE_ACTIVE_STATUSES = ("draft", "pending_info", "submitted", "uncertain")

FRESHNESS_WINDOW_DAYS = 7


def broker_profile_score(broker_id):
    """Calculate broker profile score (0-100) from listing quality + freshness.

    Score = 60% × avg_completeness + 40% × freshness_pct
    Only active listings count. No listings → score is None ("—").

    Returns dict: score, completeness, freshness, total_listings,
                  complete_listings, fresh_listings.
    """
    listings = db.list_broker_listings(
        broker_id, limit=10000, offset=0,
        statuses=PROFILE_ACTIVE_STATUSES)
    total = len(listings)
    if not total:
        return {
            "score": None,
            "completeness": None,
            "freshness": None,
            "total_listings": 0,
            "complete_listings": 0,
            "fresh_listings": 0,
        }

    now = time.time()
    fresh_cutoff = now - FRESHNESS_WINDOW_DAYS * 86400
    comp_sum = 0
    complete_count = 0
    fresh_count = 0
    for l in listings:
        comp, _ = completeness_score(l)
        comp_sum += comp
        if comp >= 80:
            complete_count += 1
        if (l.get("updated_at") or 0) >= fresh_cutoff:
            fresh_count += 1

    avg_comp = comp_sum / total
    fresh_pct = fresh_count / total * 100
    score = round(avg_comp * 0.6 + fresh_pct * 0.4)
    return {
        "score": score,
        "completeness": round(avg_comp),
        "freshness": round(fresh_pct),
        "total_listings": total,
        "complete_listings": complete_count,
        "fresh_listings": fresh_count,
    }


def profile_score_text(broker_id, pronoun="anh"):
    """Vietnamese profile card text for the broker's own score."""
    s = broker_profile_score(broker_id)
    pn = pronoun.capitalize()
    if s["total_listings"] == 0:
        return (
            f"📊 <b>Hồ sơ của {pn.lower()}:</b>\n\n"
            f"Điểm uy tín: — (chưa có tin nào)\n\n"
            f"{pn} gửi tin đầu tiên để bắt đầu tích điểm nhé! 📝"
        )
    return (
        f"📊 <b>Hồ sơ của {pn.lower()}:</b>\n"
        f"Điểm uy tín: <b>{s['score']}/100</b>\n\n"
        f"📝 Chất lượng tin: {s['completeness']}/100 "
        f"({s['complete_listings']}/{s['total_listings']} tin đầy đủ)\n"
        f"🔄 Độ tươi: {s['freshness']}/100 "
        f"({s['fresh_listings']}/{s['total_listings']} tin cập nhật trong 7 ngày)\n\n"
        f"💡 Tin đầy đủ + cập nhật thường xuyên → điểm cao\n"
        f"   → được ưu tiên match với khách hàng thật"
    )


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

# per-user collection buffer: {user_id: {"texts": [], "photos": [], "deadline": ts,
#   "forward_source": str|None}}
# "forward_source" records where the content was forwarded from (channel name,
# user name, etc.) so the confirmation can show "(forward từ ...)".
# Buffer dicts may also carry "guided": True and "chat_id".

_buffers = {}

COLLECT_WINDOW = 5  # seconds of silence before asking "đủ chưa?"


import re as _re

_FORWARD_NOISE_PATTERNS = [
    # bare channel mention / t.me link lines (typical channel footers)
    _re.compile(r"^@[\w]{5,}$"),
    _re.compile(r"^(https?://)?t\.me/[\w/]+$"),
    _re.compile(r"^[👉📌➡️📢]\s*@?[\w]+$"),
    _re.compile(r"^[👉📌➡️📢]\s*(https?://)?t\.me/[\w/]+$"),
]


def strip_forward_noise(text):
    """Remove obvious channel-attribution footers from forwarded text.

    Only strips trailing lines (footers) matching channel-promo patterns:
    bare "@channel", "t.me/..." links, "👉 @channel". Never touches the
    body — the field-specific parser already ignores most noise, this just
    keeps raw_text clean.
    """
    if not text:
        return text
    lines = text.strip().split("\n")
    while lines:
        stripped = lines[-1].strip()
        if any(p.match(stripped) for p in _FORWARD_NOISE_PATTERNS):
            lines.pop()
        else:
            break
    return "\n".join(lines).strip()


def get_forward_source(msg):
    """Return a short human-readable label for a forwarded message's origin,
    or None if the message was not forwarded.

    Handles all Telegram forward mechanics (python-telegram-bot 21.x):
    - forward_from_chat: forwarded from a channel/supergroup -> channel title
    - forward_from: forwarded from a user (no privacy) -> name / @username
    - forward_sender_name: sender has forward-privacy enabled -> name string
    - forward_origin: Bot API 7+ MessageOrigin object (fallback)

    Note on albums: when a user forwards an album, Telegram delivers the
    photos as separate messages that (in practice) share a fresh
    media_group_id, so the normal album reassembly still works. If
    media_group_id is ever absent on a forward, the 5s collection buffer
    groups the photos anyway — but see on_photo: forwarded photos bypass
    the "stray photo?" question and go straight into a new buffer.
    """
    if msg is None:
        return None
    # 1. forwarded from a channel / supergroup
    ffc = getattr(msg, "forward_from_chat", None)
    if ffc is not None:
        title = getattr(ffc, "title", None)
        username = getattr(ffc, "username", None)
        if title:
            return title
        if username:
            return "@" + username
        return "kênh/chat"
    # 2. forwarded from a user (no privacy restriction)
    ff = getattr(msg, "forward_from", None)
    if ff is not None:
        name = (getattr(ff, "full_name", "") or "").strip()
        username = getattr(ff, "username", None)
        if name:
            return name
        if username:
            return "@" + username
        return "người dùng"
    # 3. privacy-enabled sender: only a name string is available
    fsn = getattr(msg, "forward_sender_name", None)
    if fsn:
        return fsn
    # 4. Bot API 7+ forward_origin object
    fo = getattr(msg, "forward_origin", None)
    if fo is not None:
        try:
            ftype = getattr(fo, "type", "")
            if ftype == "channel":
                chat = getattr(fo, "chat", None)
                title = getattr(chat, "title", None) if chat else None
                return title or "kênh"
            if ftype == "user":
                user = getattr(fo, "sender_user", None)
                name = (getattr(user, "full_name", "") or "").strip() if user else ""
                return name or "người dùng"
            if ftype == "hidden_user":
                return getattr(fo, "sender_user_name", None) or "người dùng ẩn danh"
            if ftype == "chat":
                chat = getattr(fo, "sender_chat", None)
                title = getattr(chat, "title", None) if chat else None
                return title or "nhóm/chat"
        except Exception:
            pass
        return "tin forward"
    return None

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
    if l.get("status") == "uncertain":
        bits.append("⚠️ cần xác nhận")

    return f"{line1}\n{' | '.join(bits)}"


# ---------------------------------------------------------------- /start

_PTYPE_SHORT = {"apartment": "Căn hộ", "house": "Nhà", "villa": "Villa",
                "room": "Phòng", "studio": "Studio"}

_FURN_SHORT = {"full": "Full", "basic": "Cơ bản", "empty": "Trống"}


def _confirm_summary(l, pn="anh", phone_note="", forward_source="",
                   hl_stage=False):
    """Full pre-save summary of every parsed field.

    Returns (text, keyboard_or_None). Unknown/empty fields are skipped.
    keyboard is None when nothing was parsed (fallback prompt instead).
    forward_source: label from get_forward_source() — shown as
    "(forward từ ...)" so the broker knows the origin was detected.
    hl_stage: when True, show the selling-points prompt with a
    [Bỏ qua, tiếp tục] button instead of the [Đúng rồi]/[Sửa] buttons.
    """
    p = l.get("parsed") or {}
    photos = l.get("photo_file_ids") or []
    lines = ["Em tóm tắt lại tin này nhé:", ""]
    if forward_source:
        lines.append(f"↗️ (forward từ {forward_source})")
        lines.append("")
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

    hl = p.get("highlights") or []
    if hl:
        lines.append("✨ Điểm nổi bật:")
        for h in hl:
            lines.append(f"• {h}")
        has = True

    if not has:
        return ("Em chưa bóc được thông tin gì từ tin này 😅 "
                f"{pn} gửi thêm giúp em nhé? (giá, số phòng ngủ, địa chỉ...)",
                None)
    if hl_stage:
        lines += ["",
                  "✨ Anh có muốn thêm điểm nào để thu hút khách không?",
                  '(vd: "view siêu đẹp", "chủ dễ tính", "khu yên tĩnh")',
                  "Gõ thêm hoặc bấm nút bên dưới nhé 👇"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Bỏ qua, tiếp tục",
                                  callback_data=f"cfm:hl_done:{l['id']}")],
        ])
    else:
        lines += ["", f"Đúng hết chưa {pn}?"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đúng rồi, lưu tin",
                                  callback_data=f"cfm:save:{l['id']}")],
            [InlineKeyboardButton("✏️ Sửa",
                                  callback_data=f"cfm:edit:{l['id']}")],
        ])
    return "\n".join(lines), kb


