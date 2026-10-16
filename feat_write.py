"""FB post writer (5 languages)."""
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

from utils import (
    MENU_KB, STATUS_EMOJI, STATUS_LABEL, LIST_FILTERS,
    CLIENT_STATUS_EMOJI, CLIENT_STATUS_LABEL,
    COMPLETENESS_FIELDS, completeness_score, freshness_badge, get_pronoun,
    DISTRICT_CODES, PRICE_RANGES, BR_OPTIONS,
    _parse_filter_str, _build_filter_str, _filters_to_search,
    _describe_ui_filters, rel_time, parse_listing_cb,
    _buffers, COLLECT_WINDOW, _media_groups, MEDIA_GROUP_WINDOW,
    _addphoto_pending, ADD_PHOTO_WINDOW,
    natural_delay, PROCESSING_HINTS, react_heart,
    maybe_send_hint, maybe_send_hint_to_chat,
    fmt_price, listing_line, _confirm_summary,
)

log = logging.getLogger("linh")

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
    desc = (p.get("description") or "").strip()
    amenities = p.get("amenities") or []
    if isinstance(amenities, str):
        try:
            import json as _json
            amenities = _json.loads(amenities)
        except Exception:
            amenities = [amenities]
    deposit = p.get("deposit_months")
    n_photos = len(p.get("photos") or [])

    # ---- shared title location: building + district ----
    _bld = p.get("building_name") or ""
    _dist = p.get("district") or ""
    if _bld and _dist:
        title_loc = f"{_bld}, {_dist}"
    else:
        title_loc = _bld or _dist

    # studio: bedrooms and property_type both say "studio" — avoid duplication
    _is_studio = (br == 0.0) or (ptype == "studio")

    def _deposit_text(lang):
        if not deposit:
            return ""
        n = deposit
        if lang == "vi":
            return f"(cọc {n} tháng)"
        if lang == "en":
            return f"({n}-month deposit)" if n != 1 else "(1-month deposit)"
        if lang == "ko":
            return f"(보증금 {n}개월)"
        if lang == "zh":
            return f"(押金{n}个月)"
        if lang == "ru":
            return f"(залог {n} мес.)"
        return ""

    def build_vi():
        br_part = "" if _is_studio else (f" {br_vi}" if br_vi else "")
        title = f"🏠 Cho thuê {ptype_vi}{br_part}"
        if title_loc:
            title += f" — {title_loc}"
        lines = [title, ""]
        if desc:
            lines.append(desc)
            lines.append("")
        if address:
            lines.append(f"📍 {address}")
        if price_vi:
            dep = _deposit_text("vi")
            lines.append(f"💰 {price_vi}" + (f" {dep}" if dep else ""))
        specs = []
        if br_vi:
            specs.append(f"🛏️ {br_vi}")
        if ba:
            specs.append(f"🛁 {int(ba)} WC")
        if area:
            specs.append(f"📐 {area:g}m²")
        if furn and furn in FURN_VI:
            specs.append(FURN_VI[furn])
        if specs:
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(f"✨ {', '.join(amenities)}")
        if pet is True:
            lines.append("🐾 Cho nuôi pet")
        elif pet is False:
            lines.append("🐾 Không nuôi pet")
        if n_photos:
            lines.append(f"📸 {n_photos} ảnh chi tiết")
        lines.append("")
        if phone:
            lines.append(f"📞 {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_en():
        br_part = "" if _is_studio else (f" {br_en}" if br_en else "")
        ptype_cap = ptype_en[:1].upper() + ptype_en[1:] if ptype_en else ""
        title = f"🏠{br_part} {ptype_cap} for Rent"
        if title_loc:
            title += f" — {title_loc}"
        lines = [title, ""]
        if desc:
            lines.append(desc)
            lines.append("")
        if address:
            lines.append(f"📍 {address}")
        if price_en:
            dep = _deposit_text("en")
            lines.append(f"💰 {price_en}" + (f" {dep}" if dep else ""))
        specs = []
        if br_en:
            specs.append(f"🛏️ {br_en}")
        if ba:
            specs.append(f"🛁 {int(ba)} BA")
        if area:
            specs.append(f"📐 {area:g}sqm")
        if furn and furn in FURN_EN:
            specs.append(FURN_EN[furn])
        if specs:
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(f"✨ {', '.join(amenities)}")
        if pet is True:
            lines.append("🐾 Pet-friendly")
        elif pet is False:
            lines.append("🐾 No pets")
        if n_photos:
            lines.append(f"📸 {n_photos} detailed photo"
                         + ("s" if n_photos != 1 else ""))
        lines.append("")
        if phone:
            lines.append(f"📞 {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_ko():
        br_part = "" if _is_studio else (f" {br_ko}" if br_ko else "")
        # "Monarchy 2BR 아파트 임대 — Son Tra"
        if _bld:
            title = f"🏠 {_bld}{br_part} {ptype_ko} 임대"
            if _dist:
                title += f" — {_dist}"
        elif _dist:
            title = f"🏠 {_dist}{br_part} {ptype_ko} 임대"
        else:
            title = f"🏠{br_part} {ptype_ko} 임대"
        lines = [title, ""]
        if desc:
            lines.append(desc)
            lines.append("")
        if address:
            lines.append(f"📍 {address}")
        if price_ko:
            dep = _deposit_text("ko")
            lines.append(f"💰 {price_ko}" + (f" {dep}" if dep else ""))
        specs = []
        if br_ko:
            specs.append(f"🛏️ {br_ko}")
        if ba:
            specs.append(f"🛁 {int(ba)} BA")
        if area:
            specs.append(f"📐 {area:g}sqm")
        if furn and furn in FURN_KO:
            specs.append(FURN_KO[furn])
        if specs:
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(f"✨ {', '.join(amenities)}")
        if pet is True:
            lines.append("🐾 반려동물 가능")
        elif pet is False:
            lines.append("🐾 반려동물 불가")
        if n_photos:
            lines.append(f"📸 상세 사진 {n_photos}장")
        lines.append("")
        if phone:
            lines.append(f"📞 {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_zh():
        br_part = "" if _is_studio else br_zh  # e.g. "2房", no leading space
        title = f"🏠 出租{br_part}{ptype_zh}"
        if title_loc:
            title += f" — {title_loc}"
        lines = [title, ""]
        if desc:
            lines.append(desc)
            lines.append("")
        if address:
            lines.append(f"📍 {address}")
        if price_zh:
            dep = _deposit_text("zh")
            lines.append(f"💰 {price_zh}" + (f" {dep}" if dep else ""))
        specs = []
        if br_zh:
            specs.append(f"🛏️ {br_zh}")
        if ba:
            specs.append(f"🛁 {int(ba)}卫")
        if area:
            specs.append(f"📐 {area:g}平米")
        if furn and furn in FURN_ZH:
            specs.append(FURN_ZH[furn])
        if specs:
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(f"✨ {', '.join(amenities)}")
        if pet is True:
            lines.append("🐾 可养宠物")
        elif pet is False:
            lines.append("🐾 不可养宠物")
        if n_photos:
            lines.append(f"📸 {n_photos}张详细照片")
        lines.append("")
        if phone:
            lines.append(f"📞 {phone} (Zalo/Call)")
        return "\n".join(lines).rstrip()

    def build_ru():
        br_part = "" if _is_studio else (f" {br_ru}" if br_ru else "")
        title = f"🏠 Сдаётся{br_part} {ptype_ru}"
        if title_loc:
            title += f" — {title_loc}"
        lines = [title, ""]
        if desc:
            lines.append(desc)
            lines.append("")
        if address:
            lines.append(f"📍 {address}")
        if price_ru:
            dep = _deposit_text("ru")
            lines.append(f"💰 {price_ru}" + (f" {dep}" if dep else ""))
        specs = []
        if br_ru:
            specs.append(f"🛏️ {br_ru}")
        if ba:
            specs.append(f"🛁 {int(ba)} ван.")
        if area:
            specs.append(f"📐 {area:g}м²")
        if furn and furn in FURN_RU:
            specs.append(FURN_RU[furn])
        if specs:
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(f"✨ {', '.join(amenities)}")
        if pet is True:
            lines.append("🐾 Можно с животными")
        elif pet is False:
            lines.append("🐾 Без животных")
        if n_photos:
            lines.append(f"📸 {n_photos} детальных фото")
        lines.append("")
        if phone:
            lines.append(f"📞 {phone} (Zalo/Call)")
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
    """User tapped ✍️ Viết bài đăng — pick a listing from inventory."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    items = db.list_broker_listings(
        uid, limit=5, offset=0,
        statuses=("draft", "pending_info", "submitted", "uncertain"))
    kb = []
    for i, l in enumerate(items, start=1):
        kb.append([InlineKeyboardButton(
            f"{i}. {listing_line(l)}", callback_data=f"write:{l['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    await natural_delay(update)
    if items:
        total = db.count_broker_listings(uid)
        text = (f"Anh muốn viết bài đăng cho căn nào trong kho? "
                f"Em thấy anh có {total} căn nè:")
    else:
        text = ("Anh chưa có căn nào trong kho. "
                "Bấm 📝 Nhập căn cho thuê mới để thêm căn trước nhé!")
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
    from feat_intake import _flush_after  # lazy: avoid cycle
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
    # ko/zh/ru/all are Pro features; vi/en are free
    if lang in ("ko", "zh", "ru", "all"):
        import feat_premium
        if not feat_premium.requires_tier(q.from_user.id, "fb_multilang"):
            await feat_premium.send_gate(q, "fb_multilang",
                                         q.from_user.id, edit=True)
            return
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


# ---------------------------------------------------------------- clients (👥 Khách hàng)

