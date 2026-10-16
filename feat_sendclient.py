"""Send listings to client -> track choice -> schedule viewing.

Flow:
  Step 1: broker picks 1-4 listings for a client (toggle)
  Step 2: bot generates a copy-ready message; broker confirms sent
  Step 3: follow-up — which unit did the client pick?
  Step 4: broker types viewing datetime (VN natural) -> viewing created
"""
import asyncio
import datetime
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import db

from utils import (
    MENU_KB, CLIENT_STATUS_EMOJI, CLIENT_STATUS_LABEL,
    get_pronoun, natural_delay, fmt_price, listing_line,
)

log = logging.getLogger("linh")

MAX_PICK = 4

VN_WD_FULL = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5",
              "Thứ 6", "Thứ 7", "Chủ nhật"]


def _strip_accents(text):
    import unicodedata as _uc
    nfkd = _uc.normalize("NFD", text)
    stripped = "".join(c for c in nfkd if not _uc.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D")


# ---------------------------------------------------------------- VN datetime

def parse_vn_datetime(text, now=None):
    """Parse Vietnamese natural datetime -> unix timestamp or None.

    Understands: hôm nay/mai/mốt, thứ 2..7/chủ nhật, dd/mm,
    9h sáng, 2h chiều, 14:00, 9h30...
    """
    now = now or datetime.datetime.now()
    t = _strip_accents(text.lower().strip())

    # ---- date part
    day = None
    # hôm nay / mai / mốt
    if re.search(r"\bhom nay\b", t):
        day = now.date()
    elif re.search(r"\bngay mai\b|\bmai\b", t):
        day = now.date() + datetime.timedelta(days=1)
    elif re.search(r"\bmot\b", t):
        day = now.date() + datetime.timedelta(days=2)
    else:
        # thứ N / chủ nhật
        m = re.search(r"thu\s*([2-7])", t)
        if m:
            want = int(m.group(1)) - 2  # Thứ 2=Mon(0) .. Thứ 7=Sat(5)
            delta = (want - now.weekday()) % 7
            if delta == 0:
                delta = 7  # "thứ 2" said on Monday = next Monday
            day = now.date() + datetime.timedelta(days=delta)
        elif re.search(r"chu\s*nhat|cn\b", t):
            delta = (6 - now.weekday()) % 7
            if delta == 0:
                delta = 7
            day = now.date() + datetime.timedelta(days=delta)
        else:
            # dd/mm[/yyyy]
            m = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
            if m:
                d, mo = int(m.group(1)), int(m.group(2))
                yr = now.year
                if m.group(3):
                    yr = int(m.group(3))
                    if yr < 100:
                        yr += 2000
                try:
                    cand = datetime.date(yr, mo, d)
                except ValueError:
                    return None
                if cand < now.date():
                    # past this year -> assume next year
                    try:
                        cand = datetime.date(yr + 1, mo, d)
                    except ValueError:
                        return None
                day = cand
    if day is None:
        # default: today if only a time was given and it's still ahead,
        # else tomorrow
        day = now.date()

    # ---- time part
    hour, minute = None, 0
    m = re.search(r"(\d{1,2})[:h](\d{2})", t)  # 14:00, 9h30
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d{1,2})\s*h\b", t)  # 9h
        if m:
            hour = int(m.group(1))
    if hour is None:
        return None
    # buổi: sáng (am), chiều/tối (pm if hour < 12)
    if hour < 12 and re.search(r"\b(chieu|toi|dem)\b", t):
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    dt = datetime.datetime.combine(day, datetime.time(hour, minute))
    if dt <= now:
        # time already passed today -> push to tomorrow (only when the
        # user didn't name an explicit date)
        if re.search(r"\bhom nay\b", t) or not re.search(
                r"(mai|mot|thu\s*[2-7]|chu\s*nhat|\d{1,2}[/-]\d{1,2})", t):
            dt += datetime.timedelta(days=1)
    return dt.timestamp()


def fmt_sched(ts):
    d = datetime.datetime.fromtimestamp(ts)
    return (f"{VN_WD_FULL[d.weekday()]}, {d.day}/{d.month} "
            f"lúc {d.strftime('%H:%M')}")


# ---------------------------------------------------------------- callbacks

def _parse_s2c_cb(data):
    """'send2client:start:cli:xxx' -> ('start', 'cli:xxx')."""
    rest = data[len("send2client:"):]
    act, _, payload = rest.partition(":")
    return act, payload


def _candidates(uid, client_id):
    """Pro: auto-matched; free: broker's active listings (like match flow)."""
    import feat_premium
    from feat_clients import _client_to_search_filters
    c = db.get_client(client_id)
    if c and feat_premium.requires_tier(uid, "auto_match"):
        matches = db.search_listings(
            uid, _client_to_search_filters(c), limit=8)
        if matches:
            return matches, True
    listings = db.search_listings(uid, {"status": "active"}, limit=10)
    if not listings:
        listings = [l for l in db.list_broker_listings(uid, limit=10)
                    if l.get("status") not in ("deleted", "draft")]
    return listings[:10], False


async def s2c_start(update, ctx):
    """Step 1: pick 1-4 listings for the client (toggle)."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    act, client_id = _parse_s2c_cb(q.data)
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    listings, auto = _candidates(uid, client_id)
    if not listings:
        await q.edit_message_text(
            f"{pn.capitalize()} chưa có tin nào đang trống để gửi.",
            reply_markup=MENU_KB)
        return
    ctx.user_data["send2client"] = {
        "client_id": client_id, "selected": [],
        "cands": [l["id"] for l in listings],
    }
    await _render_picker(q, ctx, uid, c, listings, auto)


async def _render_picker(q, ctx, uid, c, listings, auto):
    sel = set((ctx.user_data.get("send2client") or {}).get("selected", []))
    cname = c.get("name") or "(chưa có tên)"
    lines = [f"Chọn tin gửi cho <b>{cname}</b> "
             f"(đã chọn {len(sel)}/{MAX_PICK}):"]
    if auto:
        lines.append("<i>✨ Tự động gợi ý theo nhu cầu khách</i>")
    kb = []
    for l in listings:
        mark = "✅" if l["id"] in sel else "⬜"
        brief = listing_line(l).splitlines()[0]
        kb.append([InlineKeyboardButton(
            f"{mark} {brief[:52]}",
            callback_data=f"send2client:toggle:{l['id']}")])
    kb.append([InlineKeyboardButton("✅ Xong, tạo tin nhắn",
                                    callback_data="send2client:done")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại",
        callback_data=f"client:{c['id']}:0:a:a")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def s2c_toggle(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, listing_id = _parse_s2c_cb(q.data)
    s2c = ctx.user_data.get("send2client")
    if not s2c:
        await q.edit_message_text("Phiên chọn tin hết hạn, anh làm lại nhé.",
                                  reply_markup=MENU_KB)
        return
    sel = s2c.get("selected", [])
    if listing_id in sel:
        sel.remove(listing_id)
    elif len(sel) < MAX_PICK:
        sel.append(listing_id)
    else:
        await q.answer(f"Tối đa {MAX_PICK} căn thôi ạ!", show_alert=True)
        return
    s2c["selected"] = sel
    ctx.user_data["send2client"] = s2c
    c = db.get_client(s2c["client_id"])
    listings = [db.get_listing(lid) for lid in s2c.get("cands", [])]
    listings = [l for l in listings if l]
    await _render_picker(q, ctx, uid, c, listings, True)


def _listing_brief(l):
    """One listing as a numbered message block for the client."""
    p = l.get("parsed") or {}
    br = p.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "")
    addr_bits = [b for b in (p.get("building_name"), p.get("street"),
                             p.get("district")) if b]
    lines = [f"🏠 {br_s} {', '.join(addr_bits)}, "
             f"{fmt_price(p.get('price_vnd'))}/tháng".strip(" ,")]
    det = []
    if p.get("area_m2"):
        det.append(f"📐 {p['area_m2']:g}m²")
    furn = p.get("furnishing")
    if furn:
        det.append({"full": "full nội thất", "basic": "nội thất cơ bản",
                    "empty": "nhà trống"}.get(furn, furn))
    if det:
        lines.append("   " + ", ".join(det))
    hls = p.get("highlights") or []
    if hls:
        lines.append("   ✨ " + ", ".join(hls[:3]))
    return "\n".join(lines)


def _build_client_message(c, listings, pn):
    cname = c.get("name") or "anh/chị"
    lines = [f"Chào {cname}! Em có {len(listings)} căn hợp với nhu cầu "
             f"của {'anh' if pn == 'anh' else 'chị'} đây ạ:\n"]
    for i, l in enumerate(listings, 1):
        lines.append(f"{i}. {_listing_brief(l)}\n")
    lines.append("Anh/chị ưng căn nào để em sắp xếp đi xem ạ? 😊")
    return "\n".join(lines)


async def s2c_done(update, ctx):
    """Step 2: generate the copy-ready message."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    s2c = ctx.user_data.get("send2client")
    if not s2c or not s2c.get("selected"):
        await q.answer("Anh tích ít nhất 1 căn nhé!", show_alert=True)
        return
    c = db.get_client(s2c["client_id"])
    if not c:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    listings = [db.get_listing(lid) for lid in s2c["selected"]]
    listings = [l for l in listings if l]
    if not listings:
        await q.edit_message_text("Tin đã chọn không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    msg = _build_client_message(c, listings, pn)
    s2c["message"] = msg
    ctx.user_data["send2client"] = s2c
    await q.edit_message_text(
        msg + "\n\n<i>👆 Tin nhắn đã soạn xong</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Copy tin nhắn",
                                  callback_data="send2client:copy")],
            [InlineKeyboardButton("✅ Đã gửi cho khách",
                                  callback_data="send2client:sent")],
            [InlineKeyboardButton("⬅️ Chọn lại",
                                  callback_data=f"send2client:start:{c['id']}")],
        ]))


async def s2c_copy(update, ctx):
    """Send the message as plain text so the broker can copy/forward."""
    q = update.callback_query
    await q.answer()
    s2c = ctx.user_data.get("send2client")
    msg = (s2c or {}).get("message")
    if not msg:
        await q.edit_message_text("Tin nhắn hết hạn, anh làm lại nhé.",
                                  reply_markup=MENU_KB)
        return
    # plain text (no HTML) — easy to copy or forward to Zalo/Messenger
    await ctx.bot.send_message(q.message.chat_id, msg)


async def s2c_sent(update, ctx):
    """Step 2 done: record sent listings + arm the 2-day follow-up."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    s2c = ctx.user_data.pop("send2client", None)
    if not s2c or not s2c.get("selected"):
        await q.edit_message_text("Phiên gửi tin hết hạn, anh làm lại nhé.",
                                  reply_markup=MENU_KB)
        return
    c = db.get_client(s2c["client_id"])
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    db.record_sent_listings(s2c["client_id"], s2c["selected"])
    for lid in s2c["selected"]:
        db.link_listing(s2c["client_id"], lid)
    db.update_client(s2c["client_id"], status="sent")
    db.touch_contact(s2c["client_id"])
    n = len(s2c["selected"])
    cname = c.get("name") or "khách"
    await q.edit_message_text(
        f"Đã lưu: gửi {n} tin cho <b>{cname}</b> ✓\n\n"
        f"2 ngày nữa em sẽ nhắc {pn} hỏi lại khách ưng căn nào nhé ⏰",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📝 Cập nhật ngay",
                callback_data=f"send2client:followup:{c['id']}")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
        ]))


# ---------------------------------------------------------------- Step 3

async def s2c_followup(update, ctx):
    """Step 3: which unit did the client pick?"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, client_id = _parse_s2c_cb(q.data)
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    sent = c.get("sent_listings") or []
    listings = []
    for s in sent:
        l = db.get_listing(s.get("id"))
        if l:
            listings.append(l)
    if not listings:
        await q.edit_message_text(
            "Chưa gửi tin nào cho khách này.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Quay lại",
                    callback_data=f"client:{client_id}:0:a:a")]]))
        return
    cname = c.get("name") or "khách"
    kb = []
    for l in listings:
        brief = listing_line(l).splitlines()[0]
        kb.append([InlineKeyboardButton(
            f"🏠 {brief[:52]}",
            callback_data=f"send2client:chose:{l['id']}")])
    kb.append([InlineKeyboardButton("❌ Khách không ưng căn nào",
                                    callback_data="send2client:nochoice")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    ctx.user_data["send2client"] = {"client_id": client_id,
                                    "followup": True}
    await q.edit_message_text(
        f"<b>{cname}</b> đã chọn căn nào chưa ạ?",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def s2c_nochoice(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    s2c = ctx.user_data.pop("send2client", None)
    if not s2c:
        await q.edit_message_text("Phiên hết hạn.", reply_markup=MENU_KB)
        return
    c = db.get_client(s2c["client_id"])
    db.add_note(s2c["client_id"],
                "Khách không ưng căn nào đã gửi — cần tìm thêm")
    db.touch_contact(s2c["client_id"])
    await q.edit_message_text(
        f"Em đã ghi chú lại ✓ {pn.capitalize()} tìm thêm căn khác"
        f" gửi cho khách nhé!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📤 Gửi tin khác",
                callback_data=f"send2client:start:{s2c['client_id']}")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
        ]))


# ---------------------------------------------------------------- Step 4

async def s2c_chose(update, ctx):
    """Client picked a listing -> ask for the viewing datetime."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, listing_id = _parse_s2c_cb(q.data)
    s2c = ctx.user_data.get("send2client") or {}
    client_id = s2c.get("client_id")
    c = db.get_client(client_id) if client_id else None
    l = db.get_listing(listing_id)
    if not c or not l or c["broker_id"] != uid:
        await q.edit_message_text("Thông tin hết hạn, anh làm lại nhé.",
                                  reply_markup=MENU_KB)
        return
    db.record_client_choice(client_id, listing_id)
    db.link_listing(client_id, listing_id)
    db.update_client(client_id, status="pending_viewing")
    s2c["awaiting_dt"] = listing_id
    ctx.user_data["send2client"] = s2c
    brief = listing_line(l).splitlines()[0]
    await q.edit_message_text(
        f"Khách chốt căn này ạ? 🏠 {brief}\n\n"
        f"Chốt đi xem ngày giờ nào ạ?\n"
        f"<i>(vd: \"mai 9h sáng\" / \"thứ 7 2h chiều\" / \"15/11 14:00\")</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy",
                                 callback_data=f"client:{client_id}:0:a:a")]]))


async def handle_s2c_datetime(update, ctx, s2c, text):
    """Free-text viewing datetime after the client chose a listing."""
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    t = text.strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("send2client", None)
        await update.message.reply_text("Đã hủy đặt lịch ạ.",
                                        reply_markup=MENU_KB)
        return True
    listing_id = s2c.get("awaiting_dt")
    client_id = s2c.get("client_id")
    c = db.get_client(client_id) if client_id else None
    l = db.get_listing(listing_id) if listing_id else None
    if not c or not l:
        ctx.user_data.pop("send2client", None)
        await update.message.reply_text("Phiên hết hạn, anh làm lại nhé.",
                                        reply_markup=MENU_KB)
        return True
    ts = parse_vn_datetime(t)
    if not ts:
        await update.message.reply_text(
            "Em chưa hiểu ngày giờ này 😅 Anh gõ lại giúp em nhé\n"
            "(vd: \"mai 9h sáng\" / \"thứ 7 2h chiều\" / \"15/11 14:00\")")
        return True
    if ts < time.time():
        await update.message.reply_text(
            "Giờ này đã qua rồi ạ 😅 Anh chọn giờ khác nhé!")
        return True
    ctx.user_data.pop("send2client", None)
    vid = db.create_viewing(uid, client_id=client_id,
                            client_name=c.get("name") or "",
                            listing_ids=[listing_id],
                            scheduled_at=ts)
    db.update_client(client_id, status="scheduled")
    db.touch_contact(client_id)
    cname = c.get("name") or "khách"
    brief = listing_line(l).splitlines()[0]
    await update.message.reply_text(
        f"Đã đặt lịch xem ✓\n\n"
        f"👤 {cname}\n"
        f"🏠 {brief}\n"
        f"🕙 {fmt_sched(ts)}\n\n"
        f"Em sẽ nhắc {pn} trước 1 tiếng nhé ⏰",
        reply_markup=MENU_KB)
    return True
