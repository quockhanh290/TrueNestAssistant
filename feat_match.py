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


def _h_txt(h):
    """Casual hours display: 'chưa đầy 1' when < 1h."""
    h = int(h)
    return str(h) if h >= 1 else "chưa đầy 1"


def _gate_message(reason, info, pn):
    """User-facing message for a failed anti-spam check."""
    if reason == "not_qualified":
        n = info.get("listing_count", 0)
        return (f"{pn.capitalize()} cần có ít nhất 10 tin đã đăng để dùng"
                f" tính năng này. Hiện tại {pn} có {n} tin.")
    if reason == "low_urgency":
        return "Chỉ đăng được cho khách có nhu cầu gấp hoặc bình thường thôi ạ."
    if reason == "already_open":
        name = info.get("client_name") or "Khách này"
        return f"{name} đã có yêu cầu đang mở rồi ạ."
    if reason == "daily_limit":
        return (f"{pn.capitalize()} đã đăng {info.get('daily_limit', 3)}"
                f" yêu cầu hôm nay rồi. Mai đăng tiếp nhé! 😊")
    if reason == "weekly_limit":
        return (f"{pn.capitalize()} đã đăng {info.get('weekly_limit', 10)}"
                f" yêu cầu tuần này rồi. Tuần sau đăng tiếp nhé!")
    if reason == "cooldown":
        return (f"{pn.capitalize()} vừa đăng cách đây"
                f" {_h_txt(info.get('hours_since', 0))} tiếng."
                f" Đợi thêm {_h_txt(info.get('hours_left', 0))} tiếng nữa nhé.")
    return "Chưa đăng được lúc này, anh thử lại sau nhé."


def _parse_mresp_cb(data):
    """Parse mresp: callbacks. mr_id itself contains a colon."""
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    mr_id = (parts[2] + ":" + parts[3]) if len(parts) > 3 else ""
    target = parts[4] if len(parts) > 4 else ""
    return act, mr_id, target


def _relay_label(uid, r):
    """Best-known public label for a broker in this request's context."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return "môi giới"
    b = db.get_broker(uid) or {}
    if b.get("username"):
        return f"@{b['username']}"
    if uid == r["broker_id"]:
        return b.get("display_name") or b.get("name") or "môi giới"
    for rp in db.list_responses(r["id"]):
        if rp["responder_broker_id"] == uid and rp.get("responder_username"):
            return f"@{rp['responder_username']}"
    return b.get("display_name") or b.get("name") or "môi giới"


def _listing_brief(lst):
    """Short ' — 🏠 2PN Sơn Trà 12tr' suffix for a responder's listing."""
    beds = lst.get("bedrooms")
    bed_txt = f"{int(beds)}PN " if beds else ""
    dist = (lst.get("district") or "").strip()
    price = lst.get("price_vnd")
    return f" — 🏠 {bed_txt}{dist} {fmt_price(price)}".strip()


def _responses_text_kb(r, resps):
    """Summary text + relay buttons for the requesting broker."""
    c = db.get_client(r["client_id"])
    client_name = (c.get("name") if c else None) or "khách"
    lines = [f"🎉 Có {len(resps)} môi giới phản hồi cho khách"
             f" <b>{client_name}</b>:"]
    kb = []
    for i, rp in enumerate(resps, start=1):
        uname = (f"@{rp['responder_username']}"
                 if rp.get("responder_username")
                 else f"môi giới {rp['responder_broker_id']}")
        line = f"{i}. {uname}"
        if rp.get("listing_id"):
            lst = db.get_listing(rp["listing_id"])
            if lst:
                line += _listing_brief(lst)
        lines.append(line)
        kb.append([InlineKeyboardButton(
            f"💬 Nhắn tin ({i})",
            callback_data=f"mresp:msg:{r['id']}:{rp['responder_broker_id']}")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def _send_full_summary(ctx, r):
    """DM the requesting broker the full responder list with relay buttons."""
    resps = db.list_responses(r["id"])
    if not resps:
        return
    text, kb = _responses_text_kb(r, resps)
    try:
        await ctx.bot.send_message(chat_id=r["broker_id"], text=text,
                                   parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        log.warning("full summary failed: %s", e)


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
    # ---- anti-spam gates: ALL checks run BEFORE posting to the group ----
    ok, reason, info = db.can_broadcast(uid, c)
    if not ok:
        await q.edit_message_text(
            _gate_message(reason, info, pn),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Quay lại",
                    callback_data=f"client:{client_id}:0:a:a")]]))
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
    db.record_broadcast(uid)  # anti-spam stats hook
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
    reqs = [r for r in db.list_broker_requests(uid)
            if r["client_id"] == client_id and r["status"] in ("open", "matched")]
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
        mark = " ✅ đủ 3 phản hồi" if r["status"] == "matched" else ""
        lines.append(f"{i}. 💰 {r['requirements_summary']}{mark}")
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
    notify the requesting broker. Max 3 responders per request."""
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
    # Same broker replying again -> ignore silently (no double count).
    if db.has_responded(r["id"], replier.id):
        return
    # 4th+ responder -> tell them it's full, don't record or notify.
    if db.count_responses(r["id"]) >= db.MAX_RESPONDERS:
        try:
            await msg.reply_text(
                "Yêu cầu này đã đủ 3 môi giới phản hồi rồi ạ.")
        except Exception as e:
            log.warning("full reply failed: %s", e)
        return
    ok, n = db.add_match_response(r["id"], replier.id, replier.username)
    if not ok:
        return
    if n >= db.MAX_RESPONDERS:
        # Full: close to new responders, DM the complete list.
        db.update_match_request(r["id"], status="matched")
        await _send_full_summary(ctx, r)
        return
    # 1-2 responders: short heads-up with a [Xem phản hồi] button.
    c = db.get_client(r["client_id"])
    client_name = c.get("name") if c else "khách"
    replier_label = (f"@{replier.username}" if replier.username
                     else replier.full_name)
    try:
        await ctx.bot.send_message(
            chat_id=r["broker_id"],
            text=(f"📨 <b>{replier_label}</b> vừa phản hồi yêu cầu cho"
                  f" khách <b>{client_name}</b> ({n}/{db.MAX_RESPONDERS})."),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👀 Xem phản hồi",
                    callback_data=f"mresp:view:{r['id']}")]]))
    except Exception as e:
        log.warning("notify broker failed: %s", e)


async def match_responses_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show the current responder list with relay buttons."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    if not r or r["broker_id"] != uid:
        return
    resps = db.list_responses(r["id"])
    c = db.get_client(r["client_id"])
    client_name = (c.get("name") if c else None) or "khách"
    if not resps:
        await q.edit_message_text(
            f"Chưa có ai phản hồi cho khách <b>{client_name}</b>."
            f" Em báo {get_pronoun(uid)} ngay khi có nhé.",
            parse_mode="HTML")
        return
    text, kb = _responses_text_kb(r, resps)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def match_relay_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start a bot-relayed message: prompt for text, forward via bot.

    Handles both mresp:msg: (requester -> responder) and
    mresp:back: (↩️ reply from either side).
    """
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, mr_id, target = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    if not r or not target.isdigit():
        return
    target_id = int(target)
    if uid == r["broker_id"]:
        # Requester side: can only message brokers that responded.
        if not db.has_responded(r["id"], target_id):
            return
        responder_id = target_id
    else:
        # Responder side: can only reply within their own thread.
        if not db.has_responded(r["id"], uid):
            return
        responder_id = uid
    ctx.user_data["relaying"] = {
        "request_id": r["id"],
        "to_id": target_id,
        "responder_id": responder_id,
        "sender_label": _relay_label(uid, r),
        "other_label": _relay_label(target_id, r),
    }
    pn = get_pronoun(uid)
    other_label = _relay_label(target_id, r)
    await q.edit_message_text(
        f"{pn.capitalize()} muốn nhắn gì tới <b>{other_label}</b>?\n"
        f"(Viết tự nhiên, em chuyển giúp. Đừng ghi SĐT nếu không muốn lộ nhé.)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy", callback_data="mresp:cancel")]]))


async def match_relay_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("relaying", None)
    await q.edit_message_text("Dạ ok, em hủy rồi nhé.")


async def _handle_relay_message(update, ctx, rl, text):
    """Forward one relayed message via the bot; log it to the thread."""
    uid = update.effective_user.id
    t = (text or "").strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("relaying", None)
        await update.message.reply_text("Dạ ok, em hủy rồi nhé.")
        return
    if not t:
        return
    r = db.get_match_request(rl["request_id"])
    if not r:
        ctx.user_data.pop("relaying", None)
        return
    sender_label = rl.get("sender_label") or _relay_label(uid, r)
    fwd = (f"💬 {sender_label} (qua TrueNest) muốn trao đổi về yêu cầu"
           f" [{r['requirements_summary']}]:\n"
           f"“{t}”")
    try:
        await ctx.bot.send_message(
            chat_id=rl["to_id"],
            text=fwd,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "↩️ Trả lời",
                    callback_data=f"mresp:back:{r['id']}:{uid}")]]))
    except Exception as e:
        log.warning("relay forward failed: %s", e)
        await update.message.reply_text(
            "Em chưa chuyển được tin này, anh thử lại sau nhé.")
        return
    db.log_relay_message(r["id"], rl["responder_id"], uid, t)
    ctx.user_data.pop("relaying", None)
    other_label = rl.get("other_label") or "bên kia"
    await update.message.reply_text(
        f"Em đã chuyển tin nhắn tới {other_label} rồi nhé ✓")


# ---- delete client ----

