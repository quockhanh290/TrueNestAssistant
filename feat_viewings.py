"""Viewing schedule + reminders."""
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

VIEWING_TIMES = ["08:00", "09:00", "10:00", "11:00",
                 "14:00", "15:00", "16:00", "17:00"]

VN_WD_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

VN_WD_FULL = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5",
              "Thứ 6", "Thứ 7", "Chủ nhật"]


def _next_days(n=7):
    """[(yyyymmdd, label)] for the date picker."""
    days = []
    today = datetime.date.today()
    for i in range(n):
        d = today + datetime.timedelta(days=i)
        ymd = d.strftime("%Y%m%d")
        if i == 0:
            label = f"Hôm nay {d.day}/{d.month}"
        elif i == 1:
            label = f"Ngày mai {d.day}/{d.month}"
        else:
            label = f"{VN_WD_SHORT[d.weekday()]} {d.day}/{d.month}"
        days.append((ymd, label))
    return days


def _fmt_sched(ts):
    d = datetime.datetime.fromtimestamp(ts)
    return (f"{VN_WD_FULL[d.weekday()]}, {d.day}/{d.month} "
            f"lúc {d.strftime('%H:%M')}")


def _parse_vw_cb(data):
    """'vw:c:cli:xxx' -> ('c', 'cli:xxx'). Ids contain colons."""
    rest = data[len("vw:"):]
    act, _, payload = rest.partition(":")
    return act, payload


async def vw_from_client(update, ctx):
    """Start scheduling from a client: pick one of broker's listings."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    _, client_id = _parse_vw_cb(q.data)
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    ctx.user_data["scheduling"] = {"client_id": client_id,
                                   "client_name": c.get("name") or ""}
    listings = db.search_listings(uid, {"status": "active"}, limit=10)
    if not listings:
        await q.edit_message_text(
            f"{pn.capitalize()} chưa có tin đang trống nào để dẫn khách xem.",
            reply_markup=MENU_KB)
        return
    kb = [[InlineKeyboardButton(
        f"{i}. {listing_line(l).splitlines()[0]}",
        callback_data=f"vw:l:{l['id']}")] for i, l in enumerate(listings, 1)]
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="vw:no")])
    await q.edit_message_text(
        f"Đặt lịch cho <b>{c.get('name')}</b> — chọn tin:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def vw_from_listing(update, ctx):
    """Start scheduling from a listing: pick one of broker's clients."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    _, listing_id = _parse_vw_cb(q.data)
    l = db.get_listing(listing_id)
    if not l or l["broker_id"] != uid:
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    ctx.user_data["scheduling"] = {"listing_id": listing_id}
    clients = db.list_clients(uid, limit=10)
    if not clients:
        await q.edit_message_text(
            f"{pn.capitalize()} chưa có khách nào. Thêm khách trước nhé!",
            reply_markup=MENU_KB)
        return
    kb = [[InlineKeyboardButton(
        f"👤 {c.get('name') or '(chưa có tên)'}",
        callback_data=f"vw:cc:{c['id']}")] for c in clients]
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="vw:no")])
    await q.edit_message_text(
        f"Dẫn khách xem tin <b>{listing_line(l).splitlines()[0]}</b> — chọn khách:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def vw_pick(update, ctx):
    """One side chosen (listing or client) — show the date picker."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, payload = _parse_vw_cb(q.data)
    sched = ctx.user_data.get("scheduling") or {}
    if act == "l":
        sched["listing_id"] = payload
    elif act == "cc":
        c = db.get_client(payload)
        if not c or c["broker_id"] != uid:
            await q.edit_message_text("Khách này không còn nữa.",
                                      reply_markup=MENU_KB)
            return
        sched["client_id"] = payload
        sched["client_name"] = c.get("name") or ""
    ctx.user_data["scheduling"] = sched
    kb, row = [], []
    for ymd, label in _next_days(7):
        row.append(InlineKeyboardButton(label,
                                        callback_data=f"vw:date:{ymd}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="vw:no")])
    await q.edit_message_text("Chọn ngày xem:",
                              reply_markup=InlineKeyboardMarkup(kb))


async def vw_pick_date(update, ctx):
    q = update.callback_query
    await q.answer()
    _, ymd = _parse_vw_cb(q.data)
    sched = ctx.user_data.get("scheduling")
    if not sched:
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    sched["date"] = ymd
    ctx.user_data["scheduling"] = sched
    kb, row = [], []
    for t in VIEWING_TIMES:
        row.append(InlineKeyboardButton(t,
                                        callback_data=f"vw:time:{t.replace(':', '')}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="vw:no")])
    await q.edit_message_text(f"Ngày {_date_label(ymd)} — chọn giờ:",
                              reply_markup=InlineKeyboardMarkup(kb))


def _date_label(ymd):
    d = datetime.datetime.strptime(ymd, "%Y%m%d").date()
    today = datetime.date.today()
    delta = (d - today).days
    if delta == 0:
        return f"Hôm nay {d.day}/{d.month}"
    if delta == 1:
        return f"Ngày mai {d.day}/{d.month}"
    return f"{VN_WD_SHORT[d.weekday()]} {d.day}/{d.month}"


async def vw_pick_time(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, hhmm = _parse_vw_cb(q.data)
    sched = ctx.user_data.get("scheduling")
    if not sched or not sched.get("date"):
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    sched["time"] = hhmm
    ctx.user_data["scheduling"] = sched
    cname = sched.get("client_name")
    if not cname and sched.get("client_id"):
        c = db.get_client(sched["client_id"])
        cname = (c or {}).get("name") or "?"
    l = db.get_listing(sched.get("listing_id")) if sched.get("listing_id") else None
    dt = datetime.datetime.strptime(sched["date"] + hhmm, "%Y%m%d%H%M")
    when = (f"{VN_WD_FULL[dt.weekday()]}, {dt.day}/{dt.month} "
            f"lúc {dt.strftime('%H:%M')}")
    ltxt = listing_line(l).splitlines()[0] if l else "?"
    await q.edit_message_text(
        f"📅 <b>Xác nhận lịch xem:</b>\n\n"
        f"👤 Khách: {cname}\n"
        f"🏠 Tin: {ltxt}\n"
        f"🕙 Thời gian: {when}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Xác nhận", callback_data="vw:ok")],
            [InlineKeyboardButton("❌ Hủy", callback_data="vw:no")],
        ]))


async def vw_confirm(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    sched = ctx.user_data.pop("scheduling", None)
    if (not sched or not sched.get("date") or not sched.get("time")
            or not sched.get("listing_id")):
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    dt = datetime.datetime.strptime(sched["date"] + sched["time"],
                                    "%Y%m%d%H%M")
    db.create_viewing(uid, client_id=sched.get("client_id"),
                      client_name=sched.get("client_name") or "",
                      listing_id=sched["listing_id"],
                      scheduled_at=dt.timestamp())
    await q.edit_message_text(
        f"Đã đặt lịch ✓ Em sẽ nhắc {pn} trước 1 tiếng nhé!",
        reply_markup=MENU_KB)


async def vw_cancel(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("scheduling", None)
    await q.edit_message_text("Đã hủy đặt lịch ạ.", reply_markup=MENU_KB)


async def cmd_viewings(update, ctx):
    uid = update.effective_user.id
    text, kb = _viewings_list(uid)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cmd_viewings_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    text, kb = _viewings_list(q.from_user.id)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


def _viewings_list(uid):
    """(text, InlineKeyboardMarkup) for upcoming viewings."""
    pn = get_pronoun(uid)
    items = db.list_viewings(uid)
    if not items:
        return (f"{pn.capitalize()} chưa có lịch xem nào sắp tới.",
                MENU_KB)
    lines = ["<b>📅 Lịch xem sắp tới:</b>"]
    kb = []
    for v in items:
        l = db.get_listing(v["listing_id"]) if v.get("listing_id") else None
        ltxt = listing_line(l).splitlines()[0] if l else "?"
        cname = v.get("client_name") or "?"
        lines.append(f"\n🕙 {_fmt_sched(v['scheduled_at'])}\n"
                     f"👤 {cname}\n{ltxt}")
        kb.append([InlineKeyboardButton(
            f"❌ Hủy lịch {_fmt_sched(v['scheduled_at'])}",
            callback_data=f"vw:del:{v['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def vw_delete(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, vid = _parse_vw_cb(q.data)
    v = db.get_viewing(vid)
    if v and v["broker_id"] == uid:
        db.delete_viewing(vid)
    await q.edit_message_text("Đã hủy lịch xem ạ.", reply_markup=MENU_KB)


# ================================================================ templates

