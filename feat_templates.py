"""Message templates."""
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

TPL_BUILTINS = {
    "chao": ("👋 Chào khách mới",
             "Chào {client_name}! Em là {broker_name}, môi giới cho thuê ở Đà Nẵng. "
             "{client_name} đang tìm nhà như thế nào ạ? "
             "(mấy phòng ngủ, ngân sách khoảng bao nhiêu ạ?)"),
    "baogia": ("💰 Báo giá",
               "Dạ căn này {bedrooms} ở {district}, giá {price}/tháng ạ. "
               "{client_name} muốn xem nhà lúc nào để em sắp xếp ạ?"),
    "hen": ("📅 Hẹn xem nhà",
            "Dạ em có thể dẫn {client_name} xem nhà vào {time} ngày {date} "
            "được không ạ?"),
    "thuongluong": ("🤝 Thương lượng",
                    "Dạ giá chủ đưa ra là {price}/tháng, nhưng em sẽ thương lượng "
                    "giúp {client_name} hết sức ạ."),
}


def _fill_tpl(content, broker, client=None, listing=None):
    subs = {
        "{broker_name}": (broker.get("display_name")
                          or broker.get("username") or "em"),
        "{client_name}": (client or {}).get("name") or "anh/chị",
        "{time}": "[giờ]",
        "{date}": "[ngày]",
    }
    p = (listing or {}).get("parsed", {}) if listing else {}
    br = p.get("bedrooms")
    subs["{bedrooms}"] = ("studio" if br == 0.0
                          else (f"{int(br)}PN" if br else "[số phòng]"))
    subs["{district}"] = p.get("district") or "[khu vực]"
    subs["{price}"] = (fmt_price(p.get("price_vnd"))
                       if p.get("price_vnd") else "[giá]")
    for k, v in subs.items():
        content = content.replace(k, str(v))
    return content


async def cmd_templates(update, ctx):
    await _tpl_list_send(update.message, update.effective_user.id,
                         "-", edit=False)


async def _tpl_list_send(msg_or_q, uid, client_id, edit):
    customs = db.list_templates(uid)
    kb = []
    for key, (label, _) in TPL_BUILTINS.items():
        kb.append([InlineKeyboardButton(
            label, callback_data=f"tpl:use:{key}@{client_id}")])
    for t in customs:
        kb.append([InlineKeyboardButton(
            f"📝 {t['name']}", callback_data=f"tpl:use:{t['id']}@{client_id}")])
    kb.append([InlineKeyboardButton("➕ Thêm mẫu mới",
                                    callback_data="tpl:new")])
    if client_id != "-":
        kb.append([InlineKeyboardButton(
            "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    else:
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    markup = InlineKeyboardMarkup(kb)
    text = "💬 <b>Mẫu tin nhắn:</b>\nChọn mẫu để điền thông tin và copy nhé."
    if edit:
        await msg_or_q.edit_message_text(text, parse_mode="HTML",
                                         reply_markup=markup)
    else:
        await msg_or_q.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def tpl_list_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, client_id = _parse_tpl_cb(q.data)
    await _tpl_list_send(q, uid, client_id or "-", edit=True)


def _parse_tpl_cb(data):
    rest = data[len("tpl:"):]
    act, _, payload = rest.partition(":")
    return act, payload


async def tpl_use(update, ctx):
    """Fill a template with broker/client/listing context and show it."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, payload = _parse_tpl_cb(q.data)
    key, _, client_id = payload.partition("@")
    client_id = client_id or "-"
    broker = db.get_broker(uid) or {}
    client = None
    listing = None
    if client_id != "-" :
        client = db.get_client(client_id)
        if client and client["broker_id"] != uid:
            client = None
    if client:
        viewed = client.get("viewed_listings") or []
        if viewed:
            listing = db.get_listing(viewed[-1])
    if key in TPL_BUILTINS:
        label, content = TPL_BUILTINS[key]
        can_delete = False
    else:
        t = db.get_template(key)
        if not t or t["broker_id"] != uid:
            await q.edit_message_text("Mẫu này không còn nữa.",
                                      reply_markup=MENU_KB)
            return
        label, content = t["name"], t["content"]
        can_delete = True
    filled = _fill_tpl(content, broker, client, listing)
    kb = []
    if can_delete:
        kb.append([InlineKeyboardButton(
            "🗑 Xóa mẫu này", callback_data=f"tpl:del:{key}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Danh sách mẫu",
        callback_data=f"tpl:list:{client_id}")])
    await q.edit_message_text(
        f"{label}:\n\n{filled}\n\n<i>👆 Copy đoạn trên gửi cho khách nhé</i>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def tpl_new(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data["adding_template"] = {"step": "name"}
    await q.edit_message_text(
        "Tên mẫu mới là gì? (vd: Follow-up sau khi xem nhà)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy", callback_data="tpl:list:-")]]))


async def _handle_add_template(update, ctx, at, text):
    uid = update.effective_user.id
    t = text.strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("adding_template", None)
        await update.message.reply_text("Đã hủy ạ.", reply_markup=MENU_KB)
        return
    if at["step"] == "name":
        at["name"] = t
        at["step"] = "content"
        await update.message.reply_text(
            "Nội dung mẫu là gì?\n"
            "Dùng {client_name}, {broker_name}, {bedrooms}, {district}, "
            "{price}, {time}, {date} để em tự điền nhé.")
        return
    db.create_template(uid, at["name"], t)
    ctx.user_data.pop("adding_template", None)
    await update.message.reply_text(f"Đã lưu mẫu “{at['name']}” ✓",
                                    reply_markup=MENU_KB)


async def tpl_delete(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, tpl_id = _parse_tpl_cb(q.data)
    t = db.get_template(tpl_id)
    if t and t["broker_id"] == uid:
        db.delete_template(tpl_id)
    await _tpl_list_send(q, uid, "-", edit=True)


# ================================================================ refresh

