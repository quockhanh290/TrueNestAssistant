"""Client/lead management (CRUD, notes, matching, urgency)."""
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

CLIENT_URGENCY_EMOJI = {"urgent": "🔴", "normal": "🟡", "low": "🟢"}

CLIENT_URGENCY_LABEL = {"urgent": "Gấp", "normal": "Bình thường",
                        "low": "Tham khảo"}

CLIENT_STATUS_FILTERS = [
    ("a", "Tất cả"),
    ("new", "🆕 Mới"),
    ("sent", "📤 Đã gửi"),
    ("pending_viewing", "⏳ Chờ chốt"),
    ("scheduled", "📅 Đã chốt"),
    ("viewed", "👀 Đã xem"),
    ("negotiating", "🤝 Đàm phán"),
    ("deposited", "💰 Đã cọc"),
    ("contracted", "📝 Đã kí"),
    ("rented", "✅ Xong"),
    ("cancelled", "❌ Hủy"),
]

CLIENT_URGENCY_FILTERS = [
    ("a", "Tất cả"), ("urgent", "🔴 Gấp"), ("normal", "🟡 Bth"),
    ("low", "🟢 TKhao"),
]

CLIENT_EDIT_FIELDS = [
    ("name", "👤 Tên"),
    ("phone", "📱 SĐT"),
    ("requirements", "💰 Nhu cầu"),
    ("urgency", "⏰ Mức gấp"),
]


def parse_client_cb(data, action):
    """Parse client callbacks. Client ids contain a colon (cli:<hex>).
    Returns (client_id, rest_parts)."""
    prefix = action + ":"
    rest = data[len(prefix):]
    parts = rest.split(":")
    client_id = parts[0] + ":" + parts[1]  # cli:<hex>
    return client_id, parts[2:]


def _client_req_summary(c):
    """'2PN Sơn Trà <15tr' — compact requirement summary."""
    parts = []
    br = c.get("bedrooms")
    if br is not None:
        try:
            parts.append("Studio" if float(br) == 0 else f"{int(float(br))}PN")
        except (TypeError, ValueError):
            pass
    if c.get("district"):
        parts.append(c["district"])
    bmin, bmax = c.get("budget_min"), c.get("budget_max")
    if bmin and bmax:
        parts.append(f"{fmt_price(bmin)}-{fmt_price(bmax)}")
    elif bmax:
        parts.append(f"<{fmt_price(bmax)}")
    elif bmin:
        parts.append(f">{fmt_price(bmin)}")
    if c.get("property_type"):
        parts.append(c["property_type"])
    return " ".join(parts) or "chưa rõ nhu cầu"


def _client_line(c):
    urg = CLIENT_URGENCY_EMOJI.get(c.get("urgency") or "normal", "🟡")
    st = CLIENT_STATUS_EMOJI.get(c.get("status") or "new", "🆕")
    sl = CLIENT_STATUS_LABEL.get(c.get("status") or "new", "mới")
    name = c.get("name") or "(chưa có tên)"
    phone = c.get("phone") or "chưa có SĐT"
    return (f"👤 {name} {urg}\n"
            f"📱 {phone}\n"
            f"💰 {_client_req_summary(c)} | {st} {sl}")


def _clients_back_kb(page, s, u):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Danh sách",
                             callback_data=f"clients:list:{page}:{s}:{u}")]])


async def cmd_clients(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_broker(u.id, u.username, u.full_name)
    await natural_delay(update)
    await _send_client_list(update.message, u.id, page=0, s="a", u_="a",
                            edit=False)


async def _send_client_list(msg_or_q, uid, page, s, u_, edit):
    """Render the client list. msg_or_q: message (new msg) or callback query."""
    per = 5
    status = None if s == "a" else s
    urgency = None if u_ == "a" else u_
    total = db.count_clients(uid, status=status, urgency=urgency)
    items = db.list_clients(uid, status=status, urgency=urgency,
                            limit=per, offset=page * per)
    pn = get_pronoun(uid)

    kb = []
    # status filter — Free: 4 basic, Pro: all 10 (2 rows)
    import feat_premium
    from utils import FREE_CLIENT_STATUSES
    is_pro = feat_premium.requires_tier(uid, "send2client")
    filters = [f for f in CLIENT_STATUS_FILTERS
               if f[0] == "a" or is_pro or f[0] in FREE_CLIENT_STATUSES]
    srow, srow2 = [], []
    for i, (code, label) in enumerate(filters):
        mark = "● " if s == code else ""
        btn = InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"clients:list:0:{code}:{u_}")
        (srow if i < 6 else srow2).append(btn)
    kb.append(srow)
    if srow2:
        kb.append(srow2)
    # row 2: urgency filter
    urow = []
    for code, label in CLIENT_URGENCY_FILTERS:
        mark = "● " if u_ == code else ""
        urow.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"clients:list:0:{s}:{code}"))
    kb.append(urow)

    if not items:
        text = (f"{pn.capitalize()} chưa có khách nào. Bấm ➕ Thêm khách để bắt đầu nhé!"
                if total == 0 else
                "Không có khách nào khớp bộ lọc. Thử nới điều kiện ra nhé?")
    else:
        lines = [f"<b>👥 Khách hàng ({total}):</b>"]
        for i, c in enumerate(items, start=page * per + 1):
            if i > page * per + 1:
                lines.append("━━━━━━━━━━━━")
            lines.append(f"{i}. {_client_line(c)}")
            kb.append([InlineKeyboardButton(
                f"{i}. Chi tiết",
                callback_data=f"client:{c['id']}:{page}:{s}:{u_}")])
        text = "\n".join(lines)

    kb.append([InlineKeyboardButton("➕ Thêm khách",
                                    callback_data="clients:new"),
               InlineKeyboardButton("💰 Hoa hồng",
                                    callback_data="cms:cur")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️", callback_data=f"clients:list:{page-1}:{s}:{u_}"))
    if (page + 1) * per < total:
        nav.append(InlineKeyboardButton(
            "➡️", callback_data=f"clients:list:{page+1}:{s}:{u_}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])

    markup = InlineKeyboardMarkup(kb)
    if edit:
        await msg_or_q.edit_message_text(text, parse_mode="HTML",
                                         reply_markup=markup)
    else:
        await msg_or_q.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def show_clients(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: menu:clients | clients:list:{page}:{s}:{u}"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    if data == "menu:clients":
        page, s, u_ = 0, "a", "a"
    else:
        _, _, page_s, s, u_ = data.split(":")
        page = int(page_s) if page_s.isdigit() else 0
    await _send_client_list(q, uid, page, s, u_, edit=True)


# ---- add client (step-by-step) ----

async def client_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pn = get_pronoun(q.from_user.id)
    ctx.user_data["adding_client"] = {"step": "name"}
    await q.edit_message_text(
        f"Khách tên gì ạ?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy", callback_data="clients:cancel")]]))


async def client_add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("adding_client", None)
    pn = get_pronoun(q.from_user.id)
    await q.edit_message_text(f"Ok, {pn} đổi ý thì thêm sau nhé 😊",
                              reply_markup=MENU_KB)


def _client_urgency_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Gấp — cần trong 1 tuần",
                              callback_data="clientadd:urg:urgent")],
        [InlineKeyboardButton("🟡 Bình thường — trong 1 tháng",
                              callback_data="clientadd:urg:normal")],
        [InlineKeyboardButton("🟢 Chỉ tham khảo",
                              callback_data="clientadd:urg:low")],
        [InlineKeyboardButton("❌ Hủy", callback_data="clients:cancel")],
    ])


async def _handle_add_client(update, ctx, addc, text):
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    step = addc.get("step")

    if step == "name":
        name = text.strip()
        if not name:
            await update.message.reply_text("Tên khách là gì ạ?")
            return
        addc["name"] = name
        addc["step"] = "phone"
        await update.message.reply_text(
            f"SĐT của {name}? (gõ “bỏ qua” nếu chưa có)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Bỏ qua",
                                     callback_data="clientadd:skipphone")]]))
        return

    if step == "phone":
        t = text.strip().lower()
        if t in ("bỏ qua", "bo qua", "skip", ""):
            addc["phone"] = ""
        else:
            phones = normalize_phone(text)
            if not phones:
                await update.message.reply_text(
                    "SĐT này chưa đúng định dạng, kiểm tra lại giúp em nhé?")
                return
            addc["phone"] = phones[0]
        addc["step"] = "req"
        await update.message.reply_text(
            f"Khách cần tìm gì? (vd: 2PN Sơn Trà dưới 15tr)")
        return

    if step == "req":
        req = listing_parser.parse_query(text)
        addc["requirements"] = req
        addc["requirements_raw"] = text.strip()
        addc["step"] = "urgency"
        await update.message.reply_text(
            "Mức độ gấp của khách này thế nào ạ?",
            reply_markup=_client_urgency_kb())
        return

    if step == "urgency":
        # typed fallback for the urgency buttons
        t = text.strip().lower()
        urg = {"gấp": "urgent", "gap": "urgent", "urgent": "urgent",
               "bình thường": "normal", "binh thuong": "normal",
               "normal": "normal",
               "tham khảo": "low", "tham khao": "low", "low": "low"}.get(t)
        if not urg:
            await update.message.reply_text(
                "Chọn giúp em 1 mức nhé 👇",
                reply_markup=_client_urgency_kb())
            return
        await _finish_add_client(update.message, ctx, uid, addc, urg, pn)


async def _finish_add_client(update_or_msg, ctx, uid, addc, urgency, pn):
    cid = db.create_client(
        uid, name=addc.get("name", ""), phone=addc.get("phone", ""),
        requirements_raw=addc.get("requirements_raw", ""),
        requirements=addc.get("requirements") or {},
        urgency=urgency)
    ctx.user_data.pop("adding_client", None)
    urg_e = CLIENT_URGENCY_EMOJI.get(urgency, "🟡")
    text = (f"Em đã lưu khách <b>{addc.get('name')}</b> {urg_e} ✓\n"
            f"💰 {_client_req_summary(db.get_client(cid))}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Xem khách",
                              callback_data=f"client:{cid}:0:a:a")],
        [InlineKeyboardButton("➕ Thêm khách khác",
                              callback_data="clients:new")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ])
    send = (update_or_msg.edit_message_text
            if hasattr(update_or_msg, "edit_message_text")
            else update_or_msg.reply_text)
    await send(text, parse_mode="HTML", reply_markup=kb)


async def client_add_urgency_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clientadd:urg:{urg} | clientadd:skipphone"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    addc = ctx.user_data.get("adding_client")
    if not addc:
        await q.edit_message_text("Phiên thêm khách đã hết hạn, làm lại nhé 😊",
                                  reply_markup=MENU_KB)
        return
    data = q.data
    if data == "clientadd:skipphone":
        addc["phone"] = ""
        addc["step"] = "req"
        await q.edit_message_text("Khách cần tìm gì? (vd: 2PN Sơn Trà dưới 15tr)")
        return
    urg = data.split(":")[-1]
    if urg not in ("urgent", "normal", "low"):
        return
    await _finish_add_client(q, ctx, uid, addc, urg, pn)


# ---- client detail ----

def _client_detail_text(c, pn):
    from utils import client_pipeline_bar, FREE_CLIENT_STATUSES
    import feat_premium
    is_pro = feat_premium.requires_tier(c["broker_id"], "send2client")
    urg_e = CLIENT_URGENCY_EMOJI.get(c.get("urgency") or "normal", "🟡")
    urg_l = CLIENT_URGENCY_LABEL.get(c.get("urgency") or "normal", "Bình thường")
    st = c.get("status") or "new"
    st_e = CLIENT_STATUS_EMOJI.get(st, "•")
    st_l = CLIENT_STATUS_LABEL.get(st, st)
    pro_only = (not is_pro) and (st not in FREE_CLIENT_STATUSES)
    lines = [
        f"👤 <b>{c.get('name') or '(chưa có tên)'}</b> {urg_e}",
        f"📱 SĐT: {c.get('phone') or 'chưa có'}",
        f"💰 Nhu cầu: {_client_req_summary(c)}",
    ]
    if c.get("requirements_raw"):
        lines.append(f"   <i>“{c['requirements_raw']}”</i>")
    lines.append(f"⏰ Mức gấp: {urg_e} {urg_l}")
    lines.append(f"📌 Trạng thái: {st_e} {st_l}{' 💎' if pro_only else ''}")
    bar = client_pipeline_bar(st, full=is_pro)
    if bar:
        lines.append(f"\n🔄 <i>{bar}</i>")
    if c.get("notes"):
        lines.append(f"📝 Ghi chú:\n{c['notes']}")
    n_viewed = len(c.get("viewed_listings") or [])
    if n_viewed:
        lines.append(f"🏠 Đã gửi/xem: {n_viewed} tin")
    sent = c.get("sent_listings") or []
    if sent:
        import datetime as _dt
        parts = []
        for s in sent[-4:]:
            d = _dt.datetime.fromtimestamp(s.get("sent_at") or 0)
            parts.append(d.strftime("%d/%m"))
        lines.append(f"📤 Đã gửi tin: {len(sent)} ({', '.join(parts)})")
    choice = c.get("client_choice")
    if choice and choice.get("id"):
        lines.append("✅ Khách đã chọn 1 căn (xem lịch xem)")
    return "\n".join(lines)


def _client_detail_kb(c, page, s, u_):
    import feat_premium
    is_pro = feat_premium.requires_tier(c["broker_id"], "send2client")
    cid = c["id"]
    pro_mark = "" if is_pro else " 💎"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Gợi ý tin",
                              callback_data=f"client:match:{cid}"),
         InlineKeyboardButton("📝 Thêm ghi chú",
                              callback_data=f"client:note:{cid}")],
        [InlineKeyboardButton(f"📤 Gửi tin cho khách{pro_mark}",
                              callback_data=f"send2client:start:{cid}")],
        [InlineKeyboardButton(f"📝 Khách chọn căn nào?{pro_mark}",
                              callback_data=f"send2client:followup:{cid}"),
         InlineKeyboardButton("📅 Đặt lịch xem",
                              callback_data=f"vw:c:{cid}")],
        [InlineKeyboardButton("💬 Mẫu tin nhắn",
                              callback_data=f"tpl:list:{cid}"),
         InlineKeyboardButton("📢 Yêu cầu đã đăng",
                              callback_data=f"client:reqs:{cid}")],
        [InlineKeyboardButton("🔄 Đổi trạng thái",
                              callback_data=f"client:status:{cid}"),
         InlineKeyboardButton("✏️ Sửa",
                              callback_data=f"client:edit:{cid}")],
        [InlineKeyboardButton("🗑 Xóa khách",
                              callback_data=f"client:delete:{cid}")],
        [InlineKeyboardButton("⬅️ Danh sách",
                              callback_data=f"clients:list:{page}:{s}:{u_}")],
    ])


async def show_client_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             client_id=None, page=0, s="a", u_="a"):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    if client_id is None:
        client_id, rest = parse_client_cb(q.data, "client")
        if len(rest) >= 3:
            page, s, u_ = int(rest[0]), rest[1], rest[2]
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    await q.edit_message_text(_client_detail_text(c, pn), parse_mode="HTML",
                              reply_markup=_client_detail_kb(c, page, s, u_))


# ---- add note ----

async def client_note_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    client_id, _ = parse_client_cb(q.data, "client:note")
    c = db.get_client(client_id)
    if not c:
        return
    ctx.user_data["adding_note"] = {"client_id": client_id}
    await q.edit_message_text(
        f"Ghi chú cho <b>{c.get('name')}</b>:\n"
        "(vd: khách thích view biển, không thích tầng thấp)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy",
                                 callback_data=f"client:{client_id}:0:a:a")]]))


async def _handle_add_note(update, ctx, addn, text):
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    t = text.strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("adding_note", None)
        c = db.get_client(addn["client_id"])
        await update.message.reply_text(
            _client_detail_text(c, pn), parse_mode="HTML",
            reply_markup=_client_detail_kb(c, 0, "a", "a"))
        return
    if not t:
        await update.message.reply_text("Ghi gì đó giúp em nhé?")
        return
    db.add_note(addn["client_id"], t)
    ctx.user_data.pop("adding_note", None)
    c = db.get_client(addn["client_id"])
    await update.message.reply_text(
        f"Đã lưu ghi chú ✓\n\n{_client_detail_text(c, pn)}",
        parse_mode="HTML",
        reply_markup=_client_detail_kb(c, 0, "a", "a"))


# ---- change status ----

async def client_status_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    import feat_premium
    from utils import FREE_CLIENT_STATUSES
    is_pro = feat_premium.requires_tier(uid, "send2client")
    client_id, _ = parse_client_cb(q.data, "client:status")
    c = db.get_client(client_id)
    if not c:
        return
    kb = []
    for st in db.CLIENT_STATUSES:
        if not is_pro and st not in FREE_CLIENT_STATUSES:
            continue
        mark = "● " if c.get("status") == st else ""
        kb.append([InlineKeyboardButton(
            f"{mark}{CLIENT_STATUS_EMOJI[st]} {CLIENT_STATUS_LABEL[st]}",
            callback_data=f"client:setstatus:{client_id}:{st}")])
    if not is_pro:
        kb.append([InlineKeyboardButton(
            "💎 Mở khóa đủ 10 trạng thái — xem gói Pro",
            callback_data="premium:plans")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    await q.edit_message_text("Đổi trạng thái khách:",
                              reply_markup=InlineKeyboardMarkup(kb))


async def client_set_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, rest = parse_client_cb(q.data, "client:setstatus")
    new_status = rest[0] if rest else "new"
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        return
    # Free tier can't set Pro-only statuses (also blocks forged callbacks)
    import feat_premium
    from utils import FREE_CLIENT_STATUSES
    if (not feat_premium.requires_tier(uid, "send2client")
            and new_status not in FREE_CLIENT_STATUSES):
        await q.answer("Trạng thái này cần gói Pro 💎", show_alert=True)
        return
    if new_status not in db.CLIENT_STATUSES:
        return
    db.update_client(client_id, status=new_status)
    db.touch_contact(client_id)
    c = db.get_client(client_id)
    st_e = CLIENT_STATUS_EMOJI.get(new_status, "•")
    st_l = CLIENT_STATUS_LABEL.get(new_status, new_status)
    await q.edit_message_text(
        f"Đã đổi trạng thái thành {st_e} {st_l} ✓\n\n"
        f"{_client_detail_text(c, pn)}",
        parse_mode="HTML",
        reply_markup=_client_detail_kb(c, 0, "a", "a"))


# ---- edit client ----

async def client_edit_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    client_id, _ = parse_client_cb(q.data, "client:edit")
    c = db.get_client(client_id)
    if not c:
        return
    kb = [[InlineKeyboardButton(label,
                                callback_data=f"client:editfield:{client_id}:{f}")]
           for f, label in CLIENT_EDIT_FIELDS]
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    await q.edit_message_text("Sửa thông tin gì?",
                              reply_markup=InlineKeyboardMarkup(kb))


async def client_edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    client_id, rest = parse_client_cb(q.data, "client:editfield")
    field = rest[0] if rest else ""
    c = db.get_client(client_id)
    if not c:
        return
    if field == "urgency":
        kb = [
            [InlineKeyboardButton(
                f"{CLIENT_URGENCY_EMOJI[u]} {CLIENT_URGENCY_LABEL[u]}",
                callback_data=f"client:seturg:{client_id}:{u}")]
            for u in ("urgent", "normal", "low")
        ]
        kb.append([InlineKeyboardButton(
            "⬅️ Quay lại", callback_data=f"client:edit:{client_id}")])
        await q.edit_message_text("Chọn mức gấp:",
                                  reply_markup=InlineKeyboardMarkup(kb))
        return
    prompts = {
        "name": f"Tên hiện tại: {c.get('name') or 'chưa có'}. Tên mới là gì?",
        "phone": (f"SĐT hiện tại: {c.get('phone') or 'chưa có'}. "
                  "SĐT mới là gì? (gõ “xóa” để bỏ)"),
        "requirements": ("Nhu cầu hiện tại: "
                         f"{_client_req_summary(c)}. Nhập nhu cầu mới "
                         "(vd: 2PN Sơn Trà dưới 15tr):"),
    }
    ctx.user_data["editing_client"] = {"client_id": client_id, "field": field}
    await q.edit_message_text(
        prompts.get(field, "Nhập giá trị mới:"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Hủy",
                                 callback_data=f"client:{client_id}:0:a:a")]]))


async def client_set_urgency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, rest = parse_client_cb(q.data, "client:seturg")
    urg = rest[0] if rest else "normal"
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        return
    db.update_client(client_id, urgency=urg)
    c = db.get_client(client_id)
    await q.edit_message_text(
        f"Đã đổi mức gấp ✓\n\n{_client_detail_text(c, pn)}",
        parse_mode="HTML",
        reply_markup=_client_detail_kb(c, 0, "a", "a"))


async def _handle_edit_client(update, ctx, ced, text):
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    client_id, field = ced["client_id"], ced["field"]
    t = text.strip()
    if t.lower() in ("hủy", "huy", "cancel"):
        ctx.user_data.pop("editing_client", None)
        c = db.get_client(client_id)
        await update.message.reply_text(
            _client_detail_text(c, pn), parse_mode="HTML",
            reply_markup=_client_detail_kb(c, 0, "a", "a"))
        return
    if field == "name":
        if not t:
            await update.message.reply_text("Tên khách là gì ạ?")
            return
        db.update_client(client_id, name=t)
    elif field == "phone":
        if t.lower() in ("xóa", "xoa", "delete", ""):
            db.update_client(client_id, phone="")
        else:
            phones = normalize_phone(t)
            if not phones:
                await update.message.reply_text(
                    "SĐT này chưa đúng định dạng, kiểm tra lại giúp em nhé?")
                return
            db.update_client(client_id, phone=phones[0])
    elif field == "requirements":
        req = listing_parser.parse_query(t)
        db.update_client(client_id, requirements_raw=t, requirements=req)
    ctx.user_data.pop("editing_client", None)
    c = db.get_client(client_id)
    await update.message.reply_text(
        f"Cập nhật xong ✓\n\n{_client_detail_text(c, pn)}",
        parse_mode="HTML",
        reply_markup=_client_detail_kb(c, 0, "a", "a"))


# ---- match listings ----

def _client_to_search_filters(c):
    f = {"status": "active"}  # only available listings
    if c.get("bedrooms") is not None:
        f["bedrooms"] = float(c["bedrooms"])
    if c.get("budget_min"):
        f["min_price"] = float(c["budget_min"])
    if c.get("budget_max"):
        f["max_price"] = float(c["budget_max"])
    if c.get("district"):
        f["district"] = c["district"]
    if c.get("property_type"):
        f["property_type"] = c["property_type"]
    return f


async def _manual_listing_picker(q, ctx, uid, client_id, c, pn):
    """Free tier: broker manually picks listings to send (no auto-match)."""
    import feat_premium
    listings = db.search_listings(uid, {"status": "active"}, limit=10)
    # fall back to any non-deleted listings if no 'active'
    if not listings:
        listings = [l for l in db.list_broker_listings(uid, limit=10)
                    if l.get("status") not in ("deleted", "draft")]
    lines = [
        f"Chọn tin để gửi cho <b>{c.get('name')}</b> "
        f"({_client_req_summary(c)}):",
        "",
        "<i>💎 Gói Pro tự động gợi ý tin phù hợp —"
        " /premium để nâng cấp</i>",
    ]
    kb = []
    for l in listings[:10]:
        kb.append([InlineKeyboardButton(
            f"🏠 {listing_line(l)}",
            callback_data=f"client:send:{client_id}:{l['id']}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def client_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, _ = parse_client_cb(q.data, "client:match")
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        return
    await maybe_send_hint(q.message)
    # Free tier: manual listing picker (no auto-match)
    import feat_premium
    if not feat_premium.requires_tier(uid, "auto_match"):
        await _manual_listing_picker(q, ctx, uid, client_id, c, pn)
        return
    matches = db.search_listings(uid, _client_to_search_filters(c), limit=5)
    if not matches:
        kb = []
        if config.BROKER_GROUP_ID:
            kb.append([InlineKeyboardButton(
                "✅ Đăng lên nhóm",
                callback_data=f"client:broadcast:{client_id}")])
            kb.append([InlineKeyboardButton(
                "❌ Thôi",
                callback_data=f"client:match:{client_id}")])
        kb.append([InlineKeyboardButton(
            "⬅️ Quay lại",
            callback_data=f"client:{client_id}:0:a:a")])
        text = (
            f"Em chưa tìm thấy tin nào của {pn} phù hợp với "
            f"<b>{c.get('name')}</b> ({_client_req_summary(c)})."
        )
        if config.BROKER_GROUP_ID:
            text += (
                f"\n\n{pn.capitalize()} có muốn đăng nhu cầu này lên nhóm"
                f" môi giới để anh em hỗ trợ không?\n"
                f"(Chỉ hiện nhu cầu, không lộ SĐT khách)"
            )
        else:
            text += " Thử nới nhu cầu ra nhé?"
        await q.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    lines = [f"Em tìm thấy <b>{len(matches)}</b> tin phù hợp với "
             f"<b>{c.get('name')}</b>:"]
    kb = []
    for i, l in enumerate(matches, start=1):
        if i > 1:
            lines.append("━━━━━━━━━━━━")
        lines.append(f"{i}. {listing_line(l)}")
        kb.append([InlineKeyboardButton(
            f"{i}. Gửi cho khách",
            callback_data=f"client:send:{client_id}:{l['id']}")])
    kb.append([InlineKeyboardButton(
        "⬅️ Quay lại", callback_data=f"client:{client_id}:0:a:a")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def client_send_listing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Format a copy-friendly message for the broker to forward to the client."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    client_id, rest = parse_client_cb(q.data, "client:send")
    listing_id = ":".join(rest)  # tg:<hex> may itself contain colons
    c = db.get_client(client_id)
    l = db.get_listing(listing_id)
    if not c or not l or c["broker_id"] != uid:
        return
    db.link_listing(client_id, listing_id)
    p = l["parsed"]
    broker = db.get_broker(uid) or {}
    contact = broker.get("phone") or p.get("primary_phone") or ""
    br = p.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "")
    addr_bits = [b for b in (p.get("building_name"), p.get("street"),
                             p.get("district")) if b]
    msg = (f"🏠 Em gợi ý cho {c.get('name')} căn này:\n\n"
           f"{br_s} {', '.join(addr_bits)}, {fmt_price(p.get('price_vnd'))}/tháng\n")
    if p.get("area_m2"):
        msg += f"📐 {p['area_m2']:g}m²\n"
    if contact:
        msg += f"📱 Liên hệ: {contact}\n"
    msg += (f"\n{pn.capitalize()} xem thử có hợp không ạ? "
            f"Em gửi thêm ảnh nếu cần nhé 😊")
    await q.edit_message_text(
        msg + "\n\n<i>👆 Copy đoạn trên gửi cho khách nhé</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Quay lại",
                callback_data=f"client:match:{client_id}")]]))


# ---- cross-broker match broadcast ----

async def client_delete_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    client_id, _ = parse_client_cb(q.data, "client:delete")
    c = db.get_client(client_id)
    if not c:
        return
    await q.edit_message_text(
        f"Xóa khách <b>{c.get('name')}</b>? Hành động này không thể hoàn tác.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ Xóa luôn",
                callback_data=f"client:delconfirm:{client_id}")],
            [InlineKeyboardButton(
                "❌ Giữ lại",
                callback_data=f"client:{client_id}:0:a:a")],
        ]))


async def client_delete_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    client_id, _ = parse_client_cb(q.data, "client:delconfirm")
    c = db.get_client(client_id)
    if c and c["broker_id"] == uid:
        db.delete_client(client_id)
    await q.edit_message_text("Em đã xóa khách rồi ạ 🗑",
                              reply_markup=InlineKeyboardMarkup([[
                                  InlineKeyboardButton(
                                      "⬅️ Danh sách",
                                      callback_data="clients:list:0:a:a")]]))


# ================================================================ viewings

