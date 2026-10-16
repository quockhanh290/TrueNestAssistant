"""Listing management: list, detail, filters, edit, delete, photos, query."""
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

async def confirm_edit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lid = q.data.split(":", 2)[2]  # "cfm:edit:<listing_id>"
    # keep ctx.user_data["confirming"] so the edit flow returns here
    await _show_edit_picker(q, lid, "0", "s:a")


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
        "📅 Đặt lịch xem",
        callback_data=f"vw:lc:{l['id']}")])
    kb.append([
        InlineKeyboardButton(
            "📸 Xem ảnh",
            callback_data=f"photos:{l['id']}:{page}:{filt}"),
        InlineKeyboardButton(
            "➕ Thêm ảnh",
            callback_data=f"addphoto:{l['id']}:{page}:{filt}"),
    ])
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
    """Step 1: ask for confirmation before deleting."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "delete")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    text = (
        "Anh chắc chắn muốn xoá tin này không? "
        "Hành động này không thể hoàn tác.\n\n"
        f"🏠 {listing_line(l)}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Xoá luôn",
            callback_data=f"delconfirm:{l['id']}:{page}:{filt}"),
        InlineKeyboardButton(
            "❌ Giữ lại",
            callback_data=f"delcancel:{l['id']}:{page}:{filt}"),
    ]])
    await q.edit_message_text(text, reply_markup=kb)


async def delete_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 2a: broker confirmed — actually delete."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "delconfirm")
    if listing_id:
        db.set_listing_status(listing_id, "deleted", changed_by="broker")
    await q.edit_message_text("Em đã xoá tin rồi ạ 🗑",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data=f"menu:list:{page}:{filt}")]]))


async def delete_cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 2b: broker cancelled — back to listing detail."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "delcancel")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    text, kb = _detail_content(l, page, filt)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------------- listing photos

def _photo_caption(l):
    """Short plain-text caption for the photo album."""
    p = l["parsed"]
    br = p.get("bedrooms")
    br_s = "studio" if br == 0.0 else (f"{int(br)}PN" if br else "")
    loc = p.get("building_name") or p.get("district") or ""
    price = fmt_price(p.get("price_vnd"))
    bits = " ".join(x for x in (br_s, loc) if x)
    return (f"📸 {len(l['photo_file_ids'])} ảnh — "
            f"🏠 {bits}, {price}/tháng")


async def view_photos_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """[📸 Xem ảnh] — send all listing photos back as Telegram album(s),
    then offer to delete individual photos by number."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "photos")
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    photos = l["photo_file_ids"] or []
    if not photos:
        await q.message.reply_text(
            "Tin này chưa có ảnh. Anh gửi ảnh cho em nhé? 😊")
        return
    chat_id = update.effective_chat.id
    caption = _photo_caption(l)
    # Telegram allows max 10 media per group — chunk if more.
    for gi, start in enumerate(range(0, len(photos), 10)):
        chunk = photos[start:start + 10]
        media = [InputMediaPhoto(
            media=fid,
            caption=caption if gi == 0 and i == 0 else None)
            for i, fid in enumerate(chunk)]
        try:
            await ctx.bot.send_media_group(chat_id, media)
        except Exception:
            log.warning("send_media_group failed for %s", listing_id)
            await q.message.reply_text(
                "Em gửi ảnh bị lỗi, anh thử lại giúp em nhé 😅")
            return
    ctx.user_data["photo_delete"] = {
        "listing_id": listing_id, "page": page, "filt": filt,
    }
    await ctx.bot.send_message(
        chat_id,
        "Anh muốn xóa ảnh nào không? Gửi số thứ tự ảnh muốn xóa "
        f"(vd: 1, 3 — tổng {len(photos)} ảnh), hoặc gõ “bỏ qua” nhé.")


async def _handle_photo_delete_answer(update, ctx, pd, text):
    """Broker typed photo numbers to delete (or 'bỏ qua' to skip)."""
    uid = update.effective_user.id
    if text.strip().lower() in ("bỏ qua", "bo qua", "skip"):
        ctx.user_data.pop("photo_delete", None)
        await update.message.reply_text("Ok, giữ nguyên ảnh nhé ✓",
                                        reply_markup=MENU_KB)
        return
    listing = db.get_listing(pd["listing_id"])
    if not listing:
        ctx.user_data.pop("photo_delete", None)
        await update.message.reply_text("Tin này không còn nữa.",
                                        reply_markup=MENU_KB)
        return
    n = len(listing["photo_file_ids"])
    nums = set()
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            i = int(part)
            if 1 <= i <= n:
                nums.add(i)
    if not nums:
        await update.message.reply_text(
            f"Anh gửi số từ 1 đến {n} giúp em nhé (vd: 1, 3), "
            "hoặc gõ “bỏ qua”.")
        return
    keep = [fid for idx, fid in enumerate(listing["photo_file_ids"], 1)
            if idx not in nums]
    db.update_listing(pd["listing_id"], photo_file_ids=keep)
    ctx.user_data.pop("photo_delete", None)
    await update.message.reply_text(
        f"Em đã xóa {len(nums)} ảnh rồi nhé ✓ (còn {len(keep)} ảnh)",
        reply_markup=MENU_KB)


async def cmd_skip_photo_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/skip — cancel the photo-delete prompt."""
    if ctx.user_data.pop("photo_delete", None) is not None:
        await update.message.reply_text("Ok, giữ nguyên ảnh nhé ✓",
                                        reply_markup=MENU_KB)


async def add_photos_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """[➕ Thêm ảnh] — enter 'adding photos' mode for this listing."""
    q = update.callback_query
    await q.answer()
    listing_id, page, filt = parse_listing_cb(q.data, "addphoto")
    uid = update.effective_user.id
    # flush any pending buffer for another listing first
    if uid in _addphoto_pending:
        await _commit_addphotos(uid, update.effective_chat.id, ctx)
    l = db.get_listing(listing_id) if listing_id else None
    if not l:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    ctx.user_data["adding_photos"] = {
        "listing_id": listing_id, "page": page, "filt": filt,
    }
    await q.message.reply_text(
        "Anh gửi ảnh muốn thêm vào tin này nhé "
        "(gửi nhiều ảnh cùng lúc được ạ) 📥\n"
        "Gõ /huy để hủy bỏ.")


async def _handle_add_photo(update, ctx, addp, file_id, caption):
    """Buffer one photo for 'adding photos' mode; commit after quiet."""
    uid = update.effective_user.id
    pend = _addphoto_pending.get(uid)
    if pend and pend.get("task"):
        pend["task"].cancel()
    if pend is None or pend.get("listing_id") != addp["listing_id"]:
        pend = {"listing_id": addp["listing_id"], "photos": [],
                "captions": [], "task": None}
        _addphoto_pending[uid] = pend
    pend["photos"].append(file_id)
    if caption:
        pend["captions"].append(caption)
    pend["task"] = asyncio.create_task(
        _flush_addphoto(uid, update.effective_chat.id, ctx))


async def _flush_addphoto(uid, chat_id, ctx):
    """Debounced commit for 'adding photos' mode."""
    try:
        await asyncio.sleep(ADD_PHOTO_WINDOW)
    except asyncio.CancelledError:
        return  # superseded by a newer photo
    await _commit_addphotos(uid, chat_id, ctx)


async def _commit_addphotos(uid, chat_id, ctx):
    """Write buffered photos to the listing and confirm to the broker."""
    pend = _addphoto_pending.pop(uid, None)
    if not pend or not pend["photos"]:
        return
    if pend.get("task"):
        pend["task"].cancel()
    listing = db.get_listing(pend["listing_id"])
    if not listing:
        return
    photos = listing["photo_file_ids"] + pend["photos"]
    raw = listing["raw_text"]
    if pend["captions"]:
        raw = (raw + "\n" + "\n".join(pend["captions"])).strip()
    db.update_listing(pend["listing_id"], photo_file_ids=photos,
                      raw_text=raw)
    ctx.user_data.pop("adding_photos", None)
    try:
        await ctx.bot.send_message(
            chat_id,
            f"Em đã thêm {len(pend['photos'])} ảnh vào tin rồi nhé ✓ "
            f"(tổng {len(photos)} ảnh)",
            reply_markup=MENU_KB)
    except Exception:
        pass


async def cmd_cancel_addphoto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/huy — cancel 'adding photos' mode, discarding buffered photos."""
    uid = update.effective_user.id
    pend = _addphoto_pending.pop(uid, None)
    if pend and pend.get("task"):
        pend["task"].cancel()
    if ctx.user_data.pop("adding_photos", None) is not None or pend:
        await update.message.reply_text(
            "Đã hủy, không thêm ảnh nào nhé.", reply_markup=MENU_KB)
        return
    # guided intake in progress?
    if ctx.user_data.pop("guided", None) is not None:
        _buffers.pop(uid, None)
        await update.message.reply_text(
            "Đã hủy, không lưu tin nào nhé.", reply_markup=MENU_KB)


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
    """Persist edit, clear state, re-render detail with confirmation.

    When the listing is being pre-save confirmed (ctx.user_data["confirming"]),
    re-render the full confirmation summary instead of the detail view.
    """
    db.update_listing_field(listing_id, field, value, changed_by="broker")
    ctx.user_data.pop("editing", None)
    l = db.get_listing(listing_id)
    if not l:
        return
    uid = update_or_q.from_user.id if via_callback else update_or_q.effective_user.id
    confirming = (ctx.user_data.get("confirming") or {}).get("listing_id") == listing_id
    if confirming:
        pn = get_pronoun(uid)
        phone_note = (ctx.user_data.get("confirming") or {}).get("phone_note", "")
        text, kb = _confirm_summary(l, pn, phone_note)
        confirm = _edit_confirm_text(field, value)
        if via_callback:
            q = update_or_q
            await natural_delay(q)
            await q.edit_message_text(confirm + "\n\n" + text,
                                      reply_markup=kb)
        else:
            update = update_or_q
            await natural_delay(update)
            await update.message.reply_text(confirm + "\n\n" + text,
                                            reply_markup=kb)
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
    # in pre-save confirm mode, go back to the full summary
    if (ctx.user_data.get("confirming") or {}).get("listing_id") == c["lid"]:
        pn = get_pronoun(q.from_user.id)
        phone_note = (ctx.user_data.get("confirming") or {}).get("phone_note", "")
        text, kb = _confirm_summary(l, pn, phone_note)
        await q.edit_message_text(text, reply_markup=kb)
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

