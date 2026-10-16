"""Cross-broker matching/broadcast."""
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

from feat_clients import parse_client_cb, _client_req_summary

def _broadcast_text(req_summary, urgency, broker_label):
    """Group broadcast message. NEVER includes client name/phone."""
    urg_e = CLIENT_URGENCY_EMOJI.get(urgency or "normal", "🟡")
    urg_l = CLIENT_URGENCY_LABEL.get(urgency or "normal", "Bình thường")
    return (
        "🔍 CẦN TÌM NHÀ\n\n"
        f"💰 {req_summary}\n"
        f"⏰ {urg_e} {urg_l}\n"
        f"👤 Môi giới: {broker_label}\n\n"
        "Ai có căn phù hợp thì reply tin này nhé! 🤝"
    )


def _group_link(group_id, message_id):
    """t.me link to a group message. Works for private supergroups
    (-100...) and public groups with username."""
    gid = str(group_id)
    if gid.startswith("-100"):
        return f"https://t.me/c/{gid[4:]}/{message_id}"
    if gid.lstrip("-").isdigit():
        return ""  # basic groups have no message links
    return f"https://t.me/{gid.lstrip('@')}/{message_id}"


async def match_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Post the client's requirement to the broker group."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, _ = parse_client_cb(q.data, "client:broadcast")
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        return
    if not config.BROKER_GROUP_ID:
        await q.edit_message_text(
            "Tính năng này chưa được bật. Liên hệ admin nhé.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Quay lại",
                    callback_data=f"client:match:{client_id}")]]))
        return
    u = q.from_user
    broker = db.get_broker(uid) or {}
    broker_label = (f"@{u.username}" if u.username
                    else broker.get("display_name") or broker.get("name")
                    or "môi giới")
    req_summary = _client_req_summary(c)
    try:
        sent = await ctx.bot.send_message(
            chat_id=int(config.BROKER_GROUP_ID),
            text=_broadcast_text(req_summary, c.get("urgency"), broker_label))
    except Exception as e:
        log.warning("broadcast failed: %s", e)
        await q.edit_message_text(
            f"Em chưa đăng được lên nhóm ({pn} kiểm tra lại giúp em"
            f" BROKER_GROUP_ID nhé).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Quay lại",
                    callback_data=f"client:match:{client_id}")]]))
        return
    mr_id = db.create_match_request(uid, client_id, req_summary,
                                    urgency=c.get("urgency") or "normal")
    db.update_match_request(mr_id, group_message_id=sent.message_id)
    await q.edit_message_text(
        f"Em đã đăng nhu cầu của <b>{c.get('name')}</b> lên nhóm rồi nhé ✓\n"
        f"Có anh em nào reply là em báo {pn} ngay.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📢 Yêu cầu đã đăng",
                callback_data=f"client:reqs:{client_id}")],
            [InlineKeyboardButton(
                "⬅️ Quay lại",
                callback_data=f"client:{client_id}:0:a:a")]]))


async def match_requests_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """List this client's open broadcast requests."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, _ = parse_client_cb(q.data, "client:reqs")
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        return
    reqs = [r for r in db.list_broker_requests(uid, status="open")
            if r["client_id"] == client_id]
    if not reqs:
        await q.edit_message_text(
            f"Chưa có yêu cầu nào đang mở cho <b>{c.get('name')}</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Quay lại",
                    callback_data=f"client:{client_id}:0:a:a")]]))
        return
    lines = [f"📢 Yêu cầu đang mở của <b>{c.get('name')}</b>:"]
    kb = []
    for i, r in enumerate(reqs, start=1):
        lines.append(f"{i}. 💰 {r['requirements_summary']}")
        kb.append([InlineKeyboardButton(
            f"{i}. Đóng yêu cầu",
            callback_data=f"mreq:close:{r['id']}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def match_request_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Close a broadcast request; mark the group message as closed."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    parts = q.data.split(":")
    mr_id = parts[2] + ":" + parts[3] if len(parts) >= 4 else ""
    r = db.get_match_request(mr_id) if mr_id else None
    if not r or r["broker_id"] != uid:
        return
    db.close_match_request(mr_id)
    # Best-effort: mark the group message closed so others stop replying.
    if config.BROKER_GROUP_ID and r.get("group_message_id"):
        try:
            orig = _broadcast_text(r["requirements_summary"],
                                   r["urgency"], "môi giới")
            await ctx.bot.edit_message_text(
                chat_id=int(config.BROKER_GROUP_ID),
                message_id=r["group_message_id"],
                text="✅ ĐÃ ĐÓNG — " + orig)
        except Exception as e:
            log.warning("close broadcast edit failed: %s", e)
    c = db.get_client(r["client_id"])
    client_id = r["client_id"] if c else None
    back = (f"client:reqs:{client_id}" if client_id
            else "menu:clients")
    await q.edit_message_text(
        "Em đã đóng yêu cầu rồi nhé ✓",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Quay lại", callback_data=back)]]))


async def on_group_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Detect replies to broadcast messages in the broker group and
    notify the requesting broker."""
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return
    r = db.get_match_request_by_group_message(
        msg.reply_to_message.message_id)
    if not r:
        return
    replier = update.effective_user
    if replier.id == r["broker_id"]:
        return  # don't notify on own replies
    # Don't notify twice for the same request.
    if r["status"] != "open":
        return
    db.update_match_request(r["id"], status="matched")
    replier_label = (f"@{replier.username}" if replier.username
                     else replier.full_name)
    c = db.get_client(r["client_id"])
    client_name = c.get("name") if c else "khách"
    link = _group_link(config.BROKER_GROUP_ID,
                       msg.reply_to_message.message_id)
    kb = []
    if link:
        kb.append([InlineKeyboardButton("Mở nhóm", url=link)])
    try:
        await ctx.bot.send_message(
            chat_id=r["broker_id"],
            text=(f"🎉 <b>{replier_label}</b> có căn phù hợp với khách"
                  f" <b>{client_name}</b>!\n\n"
                  f"💰 {r['requirements_summary']}\n\n"
                  f"Mở group để xem chi tiết nhé. Hai anh em inbox"
                  f" nhau trao đổi, đừng lộ SĐT khách trên nhóm nhé 😉"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        log.warning("notify broker failed: %s", e)


# ---- delete client ----

