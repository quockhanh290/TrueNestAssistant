"""Viewing schedule + reminders."""
import asyncio
import datetime
import json
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
    """Start scheduling from a client: pick date first, listings later."""
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
                                   "client_name": c.get("name") or "",
                                   "listing_ids": []}
    await _send_date_picker(q, ctx)


async def _send_date_picker(q, ctx):
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


async def vw_from_listing(update, ctx):
    """Start scheduling from a listing: listing pre-selected, pick a client."""
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
    ctx.user_data["scheduling"] = {"listing_ids": [listing_id]}
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
    """Client chosen — show the date picker."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, payload = _parse_vw_cb(q.data)
    sched = ctx.user_data.get("scheduling") or {}
    if act == "cc":
        c = db.get_client(payload)
        if not c or c["broker_id"] != uid:
            await q.edit_message_text("Khách này không còn nữa.",
                                      reply_markup=MENU_KB)
            return
        sched["client_id"] = payload
        sched["client_name"] = c.get("name") or ""
        sched.setdefault("listing_ids", [])
    ctx.user_data["scheduling"] = sched
    await _send_date_picker(q, ctx)


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
    sched.setdefault("listing_ids", [])
    ctx.user_data["scheduling"] = sched
    await _send_listing_picker(q, ctx, uid, sched)


def _picker_candidates(uid, sched):
    """Client's viewed listings first, else broker's active listings."""
    cands = []
    client_id = sched.get("client_id")
    if client_id:
        c = db.get_client(client_id)
        for lid in (c.get("viewed_listings") or []):
            l = db.get_listing(lid)
            if l and l.get("broker_id") == uid:
                cands.append(l)
    if not cands:
        cands = db.search_listings(uid, {"status": "active"}, limit=12)
    # keep pre-selected ones even if not in candidates
    seen = {l["id"] for l in cands}
    for lid in sched.get("listing_ids", []):
        if lid not in seen:
            l = db.get_listing(lid)
            if l and l.get("broker_id") == uid:
                cands.insert(0, l)
                seen.add(lid)
    return cands


async def _send_listing_picker(q, ctx, uid, sched):
    cands = _picker_candidates(uid, sched)
    sched["candidates"] = [l["id"] for l in cands]
    ctx.user_data["scheduling"] = sched
    sel = set(sched.get("listing_ids", []))
    if not cands:
        pn = get_pronoun(uid)
        await q.edit_message_text(
            f"{pn.capitalize()} chưa có tin đang trống nào để dẫn khách xem.",
            reply_markup=MENU_KB)
        return
    lines = [f"Chọn căn sẽ dẫn xem (tích 1-3 căn, đã chọn {len(sel)}/3):"]
    kb = []
    for i, l in enumerate(cands, 1):
        mark = "✅" if l["id"] in sel else "⬜"
        lines.append(f"{mark} {i}. {listing_line(l).splitlines()[0]}")
        kb.append([InlineKeyboardButton(
            f"{mark} Căn {i}",
            callback_data=f"vw:lpick:toggle:{l['id']}")])
    kb.append([InlineKeyboardButton("✅ Xong, tiếp tục",
                                    callback_data="vw:lpick:done")])
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="vw:no")])
    cname = sched.get("client_name") or "khách"
    await q.edit_message_text(
        f"Đặt lịch cho <b>{cname}</b> — {lines[0]}\n" + "\n".join(lines[1:]),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def vw_lpick_toggle(update, ctx, listing_id):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sched = ctx.user_data.get("scheduling")
    if not sched:
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    sel = sched.get("listing_ids", [])
    if listing_id in sel:
        sel.remove(listing_id)
    elif len(sel) < 3:
        sel.append(listing_id)
    else:
        await q.answer("Tối đa 3 căn thôi ạ!", show_alert=True)
        return
    sched["listing_ids"] = sel
    ctx.user_data["scheduling"] = sched
    await _send_listing_picker(q, ctx, uid, sched)


async def vw_lpick_done(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sched = ctx.user_data.get("scheduling")
    if not sched or not sched.get("listing_ids"):
        await q.answer("Anh tích ít nhất 1 căn nhé!", show_alert=True)
        return
    cname = sched.get("client_name")
    if not cname and sched.get("client_id"):
        c = db.get_client(sched["client_id"])
        cname = (c or {}).get("name") or "?"
    dt = datetime.datetime.strptime(sched["date"] + sched["time"],
                                    "%Y%m%d%H%M")
    when = (f"{VN_WD_FULL[dt.weekday()]}, {dt.day}/{dt.month} "
            f"lúc {dt.strftime('%H:%M')}")
    lines = [f"📅 <b>Xác nhận lịch xem:</b>", f"👤 Khách: {cname}",
             f"🕙 Thời gian: {when}", "🏠 Các căn:"]
    for i, lid in enumerate(sched["listing_ids"], 1):
        l = db.get_listing(lid)
        brief = listing_line(l).splitlines()[0] if l else "?"
        lines.append(f"  {i}. {brief}")
    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Xác nhận", callback_data="vw:ok")],
            [InlineKeyboardButton("⬅️ Chọn lại căn",
                                  callback_data="vw:lpick:back")],
            [InlineKeyboardButton("❌ Hủy", callback_data="vw:no")],
        ]))


async def vw_lpick_back(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sched = ctx.user_data.get("scheduling")
    if not sched:
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    await _send_listing_picker(q, ctx, uid, sched)


async def vw_confirm(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    sched = ctx.user_data.pop("scheduling", None)
    if (not sched or not sched.get("date") or not sched.get("time")
            or not sched.get("listing_ids")):
        await q.edit_message_text("Phiên đặt lịch hết hạn, anh làm lại giúp em nhé.",
                                  reply_markup=MENU_KB)
        return
    dt = datetime.datetime.strptime(sched["date"] + sched["time"],
                                    "%Y%m%d%H%M")
    vid = db.create_viewing(uid, client_id=sched.get("client_id"),
                            client_name=sched.get("client_name") or "",
                            listing_ids=sched["listing_ids"],
                            scheduled_at=dt.timestamp())
    if sched.get("client_id"):
        db.touch_contact(sched["client_id"])
    n = len(sched["listing_ids"])
    await q.edit_message_text(
        f"Đã đặt lịch xem {n} căn ✓ Em sẽ nhắc {pn} trước 1 tiếng nhé!",
        reply_markup=MENU_KB)


async def vw_cancel(update, ctx):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("scheduling", None)
    await q.edit_message_text("Đã hủy đặt lịch ạ.", reply_markup=MENU_KB)


async def cmd_viewings(update, ctx):
    uid = update.effective_user.id
    import feat_premium
    if not feat_premium.requires_tier(uid, "viewings"):
        await feat_premium.send_gate(update, "viewings", uid)
        return
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
    # past viewings still missing feedback -> offer the feedback button
    pending_fb = [v for v in db.unfeedbacked_viewings(uid, min_hours=1,
                                                      max_hours=72)]
    if not items and not pending_fb:
        return (f"{pn.capitalize()} chưa có lịch xem nào sắp tới.",
                MENU_KB)
    lines = []
    kb = []
    if items:
        lines.append("<b>📅 Lịch xem sắp tới:</b>")
        for v in items:
            lids = v.get("listing_ids") or []
            cname = v.get("client_name") or "?"
            lines.append(f"\n🕙 {_fmt_sched(v['scheduled_at'])}\n👤 {cname}")
            for lid in lids:
                l = db.get_listing(lid)
                brief = listing_line(l).splitlines()[0] if l else "?"
                lines.append(f"  • {brief}")
            kb.append([InlineKeyboardButton(
                "❌ Hủy lịch", callback_data=f"vw:del:{v['id']}")])
    if pending_fb:
        lines.append("\n<b>💬 Chưa có feedback:</b>")
        for v in pending_fb:
            cname = v.get("client_name") or "?"
            lines.append(f"\n{_fmt_sched(v['scheduled_at'])} — 👤 {cname}")
            kb.append([InlineKeyboardButton(
                f"💬 Nhập feedback ({cname})",
                callback_data=f"vw:fb:{v['id']}")])
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


# ------------------------------------------------- post-viewing feedback

def _feedback_brief(vid_listing_id):
    l = db.get_listing(vid_listing_id)
    return listing_line(l).splitlines()[0] if l else "?"


async def vw_feedback_start(update, ctx):
    """Start per-listing feedback for a past viewing. callback vw:fb:{vid}."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, vid = _parse_vw_cb(q.data)
    await _begin_feedback(q, ctx, uid, vid)


async def _begin_feedback(q, ctx, uid, vid):
    """Core of vw_feedback_start — reusable from the evening checklist."""
    v = db.get_viewing(vid)
    if not v or v["broker_id"] != uid:
        await q.edit_message_text("Lịch xem này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    lids = v.get("listing_ids") or []
    if not lids:
        await q.edit_message_text("Lịch xem này không gắn căn nào.",
                                  reply_markup=MENU_KB)
        return
    ctx.user_data["viewing_feedback"] = {
        "viewing_id": vid, "listing_ids": lids, "idx": 0, "fb": {},
    }
    cname = v.get("client_name") or "khách"
    n = len(lids)
    await q.edit_message_text(
        f"Hôm qua {get_pronoun(uid)} dẫn <b>{cname}</b> xem {n} căn."
        f" Cho em xin feedback từng căn nhé.\n\n"
        f"Căn 1/{n}: {_feedback_brief(lids[0])}\n"
        f"Khách nói sao ạ? (gõ “bỏ qua” nếu không có ý kiến)",
        parse_mode="HTML")


async def _handle_viewing_feedback(update, ctx, vf, text):
    """Multi-step: one free-text feedback per listing in the viewing."""
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    t = text.strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("viewing_feedback", None)
        await update.message.reply_text("Ok, để sau nhập cũng được ạ 😊",
                                        reply_markup=MENU_KB)
        return
    lids = vf["listing_ids"]
    idx = vf["idx"]
    if t.lower() not in ("bỏ qua", "bo qua", "skip", ""):
        vf["fb"][lids[idx]] = t
    idx += 1
    vf["idx"] = idx
    if idx < len(lids):
        n = len(lids)
        await update.message.reply_text(
            f"Đã lưu ✓\n\nCăn {idx + 1}/{n}: {_feedback_brief(lids[idx])}\n"
            f"Khách nói sao ạ? (gõ “bỏ qua” nếu không có ý kiến)")
        return
    # done — persist
    ctx.user_data.pop("viewing_feedback", None)
    db.update_viewing(vf["viewing_id"],
                      feedback=json.dumps(vf["fb"], ensure_ascii=False),
                      status="done")
    v = db.get_viewing(vf["viewing_id"])
    if v and v.get("client_id"):
        db.touch_contact(v["client_id"])
    cname = (v.get("client_name") if v else None) or "khách"
    await update.message.reply_text(
        f"Cảm ơn {pn}! Em đã lưu feedback buổi xem với {cname} ✓",
        reply_markup=MENU_KB)


def parse_feedback_map(v):
    """feedback column -> {listing_id: text}. Handles legacy plain text."""
    raw = (v.get("feedback") or "").strip()
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {"_all": raw}


# ================================================================ templates

