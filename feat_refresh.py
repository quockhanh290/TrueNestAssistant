"""Old-listing refresh suggestions."""
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

async def rf_action(update, ctx):
    """Old-listing refresh buttons (sent by refresh.py cron)."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    rest = q.data[len("rf:"):]
    act, _, listing_id = rest.partition(":")
    if act == "skip" or not listing_id:
        ctx.user_data.pop("refresh_discount", None)
        await q.edit_message_text("Ok ạ, em sẽ nhắc lại sau 👋",
                                  reply_markup=MENU_KB)
        return
    l = db.get_listing(listing_id)
    if not l or l["broker_id"] != uid:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    if act == "renew":
        db.touch_listing(listing_id)
        await q.edit_message_text(
            "Em đã làm mới tin rồi ✓ Tin sẽ hiện như mới đăng ạ!",
            reply_markup=MENU_KB)
    elif act == "rented":
        db.set_listing_status(listing_id, "rented")
        await q.edit_message_text(
            f"Đã đánh dấu đã cho thuê ✓ Chúc mừng {pn}!",
            reply_markup=MENU_KB)
    elif act == "discount":
        ctx.user_data["refresh_discount"] = {"listing_id": listing_id}
        p = l["parsed"]
        cur = (fmt_price(p.get("price_vnd")) + "/tháng"
               if p.get("price_vnd") else "chưa có")
        await q.edit_message_text(
            f"Giá hiện tại: {cur}. Giá mới bao nhiêu ạ? (vd: 11tr)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Hủy", callback_data="rf:skip:")]]))


async def _handle_refresh_discount(update, ctx, rd, text):
    uid = update.effective_user.id
    t = text.strip().lower()
    if t in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("refresh_discount", None)
        await update.message.reply_text("Ok, giữ nguyên giá ạ.",
                                        reply_markup=MENU_KB)
        return
    val, _ = listing_parser.parse_price(text)
    if not val or val <= 0:
        await update.message.reply_text(
            "Em chưa hiểu giá, anh nhập lại giúp em nhé? (vd: 11tr)")
        return
    db.update_listing_field(rd["listing_id"], "price_vnd", val)
    ctx.user_data.pop("refresh_discount", None)
    await update.message.reply_text(
        f"Em cập nhật giá mới {fmt_price(val)}/tháng rồi nhé ✓",
        reply_markup=MENU_KB)


# ================================================================ deals

