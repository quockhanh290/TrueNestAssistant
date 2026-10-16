"""Client/lead management (CRUD, notes, matching, urgency)."""
import asyncio
import logging
import random
import re
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
    ("a", "Tất cả"), ("new", "🆕 Mới"), ("viewing", "👀 Đang xem"),
    ("rented", "✅ Đã thuê"),
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


# Highlight options for the listing-enrichment flow (after match warnings).
# Display labels match parser.parse_highlights() output so toggling merges
# cleanly with parsed highlights.
ENRICH_CATEGORIES = [
    ("👁️ View",
     ["View biển trực diện", "Ban công view biển", "View biển",
      "View sông", "View thành phố", "View núi"]),
    ("🏊 Tiện ích",
     ["Hồ bơi vô cực", "Hồ bơi", "Phòng gym", "Spa", "Sân tennis",
      "Khu BBQ"]),
    ("📍 Vị trí",
     ["Sát biển", "Mặt tiền biển", "Gần biển", "Gần chợ",
      "Gần trường học", "Gần sân bay", "Gần cầu Rồng",
      "Vị trí trung tâm", "Gần công viên"]),
    ("🏠 Tiện nghi",
     ["Ban công rộng", "Sân thượng", "Có thang máy", "Chỗ đậu ô tô",
      "An ninh 24/7"]),
    ("✨ Tình trạng",
     ["Mới xây", "Mới renovate", "Vừa sơn mới", "Nội thất mới 100%",
      "Mới 100%", "Khu yên tĩnh", "Thoáng mát", "Nhiều cây xanh",
      "Nhiều ánh sáng tự nhiên"]),
]
ENRICH_ALL = [opt for _, opts in ENRICH_CATEGORIES for opt in opts]
ENRICH_QUEUE_CAP = 30  # max listings per enrichment session


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
    # row 1: status filter
    srow = []
    for code, label in CLIENT_STATUS_FILTERS:
        mark = "● " if s == code else ""
        srow.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"clients:list:0:{code}:{u_}"))
    kb.append(srow)
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

# ---- free-text client intake ----

# Only strip the literal word "tên" (as in "tên Minh"); keep titles like
# "Anh"/"Chị" per spec ("anh/chị + name").
_NAME_STRIP_PREFIXES = {"tên", "ten"}

_REQ_KEYWORDS = {
    "cần", "can", "tìm", "tim", "muốn", "muon", "thuê", "thue",
    "phòng", "phong", "pn", "tr", "triệu", "trieu", "gấp", "gap",
    "ở", "khu", "đường", "duong", "quận", "quan", "cho",
    "tham", "khao", "khảo", "thôi", "thoi", "ạ", "a",
}


def _detect_client_urgency(text):
    """Detect urgency from free text. Returns 'urgent' | 'normal' | 'low'."""
    t = text.lower()
    if re.search(r"\bgấp\b|\bgap\b|asap|cần ngay|can ngay|trong tuần|trong tuan|"
                 r"tuần này|tuan nay|trong 1 tuần|\bsớm\b|\bsom\b", t):
        return "urgent"
    if re.search(r"tham khảo|tham khao|chưa cần|chua can|chưa gấp|chua gap|"
                 r"xem chơi|xem choi", t):
        return "low"
    return "normal"


def _pick_name_words(fragment):
    words = re.findall(r"[A-Za-zÀ-ỹà-ỹ]+", fragment)
    while words and words[0].lower() in _NAME_STRIP_PREFIXES:
        words.pop(0)
    picked = []
    for w in words:
        if w.lower() in _REQ_KEYWORDS:
            break
        picked.append(w)
        if len(picked) >= 3:
            break
    if not picked:
        return ""
    return " ".join(w.capitalize() for w in picked)


def _extract_client_name(text, phone):
    """Best-effort name extraction: words before the phone number,
    falling back to words after it."""
    t = text.strip()
    before, after = t, ""
    if phone:
        m = re.search(r"(?:\+?84|0)(?:[\s.\-]*\d){9}", t)
        if m:
            before = t[:m.start()]
            after = t[m.end():]
    return _pick_name_words(before) or _pick_name_words(after)


def parse_client_freetext(text):
    """Parse pasted client info into structured fields.

    Returns dict: name, phone, requirements (parse_query-style dict),
    requirements_raw, urgency.
    """
    phones = normalize_phone(text)
    phone = phones[0] if phones else ""
    req = listing_parser.parse_query(text)
    return {
        "name": _extract_client_name(text, phone),
        "phone": phone,
        "requirements": req,
        "requirements_raw": text.strip(),
        "urgency": _detect_client_urgency(text),
    }


def _req_dict_summary(req):
    """Compact summary for a parse_query-style requirements dict."""
    ptype = req.get("property_type")
    # avoid "Studio ... studio" duplication
    if req.get("bedrooms") == 0 and ptype == "studio":
        ptype = None
    pseudo = {
        "bedrooms": req.get("bedrooms"),
        "district": req.get("district"),
        "budget_min": req.get("min_price"),
        "budget_max": req.get("max_price"),
        "property_type": ptype,
    }
    return _client_req_summary(pseudo)


def _fmt_budget(req):
    """'dưới 15tr' / '8-15tr' / 'trên 20tr' / '(chưa rõ)'."""
    bmin = req.get("min_price")
    bmax = req.get("max_price")
    if bmin and bmax:
        return f"{fmt_price(bmin)}-{fmt_price(bmax)}"
    if bmax:
        return f"dưới {fmt_price(bmax)}"
    if bmin:
        return f"trên {fmt_price(bmin)}"
    return "(chưa rõ)"


def _fmt_bedrooms(req):
    br = req.get("bedrooms")
    if br is None:
        return "(chưa rõ)"
    try:
        return "Studio" if float(br) == 0 else f"{int(float(br))}PN"
    except (TypeError, ValueError):
        return "(chưa rõ)"


def _paste_confirm_text(parsed):
    req = parsed.get("requirements") or {}
    urg_e = CLIENT_URGENCY_EMOJI.get(parsed.get("urgency"), "🟡")
    urg_l = CLIENT_URGENCY_LABEL.get(parsed.get("urgency"), "Bình thường")
    lines = ["Em bóc được như này, đúng không ạ?"]
    lines.append(f"👤 Tên: <b>{parsed.get('name') or '(chưa rõ)'}</b>")
    lines.append(f"📱 SĐT: <b>{parsed.get('phone') or '(chưa có)'}</b>")
    lines.append(f"🛏️ Phòng: <b>{_fmt_bedrooms(req)}</b>")
    lines.append(f"💰 Ngân sách: <b>{_fmt_budget(req)}</b>")
    lines.append(f"📍 Khu vực: <b>{req.get('district') or '(chưa rõ)'}</b>")
    lines.append(f"{urg_e} Độ gấp: <b>{urg_l}</b>")
    return "\n".join(lines)


def _paste_confirm_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Đúng rồi, tìm tin",
                              callback_data="clients:pasteok")],
        [InlineKeyboardButton("✏️ Có chỗ chưa đúng",
                              callback_data="clients:pastefix")],
        [InlineKeyboardButton("❌ Hủy", callback_data="clients:cancel")],
    ])


def _paste_fix_picker_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Tên", callback_data="clients:fix:name"),
         InlineKeyboardButton("📱 SĐT", callback_data="clients:fix:phone")],
        [InlineKeyboardButton("🛏️ Phòng", callback_data="clients:fix:bedrooms"),
         InlineKeyboardButton("💰 Ngân sách", callback_data="clients:fix:budget")],
        [InlineKeyboardButton("📍 Khu vực", callback_data="clients:fix:district"),
         InlineKeyboardButton("🔴 Độ gấp", callback_data="clients:fix:urgency")],
        [InlineKeyboardButton("⬅️ Quay lại tóm tắt",
                              callback_data="clients:fixback")],
    ])


async def client_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pn = get_pronoun(q.from_user.id)
    ctx.user_data.pop("adding_client", None)
    await q.edit_message_text(
        f"Anh đã có thông tin khách viết sẵn chưa ạ?\n"
        f"(vd: copy từ Zalo/chat với khách rồi gửi em)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Có, em gửi luôn",
                                  callback_data="clients:addmode:paste")],
            [InlineKeyboardButton("❌ Chưa, hỏi từng câu",
                                  callback_data="clients:addmode:guided")],
            [InlineKeyboardButton("⬅️ Quay lại",
                                  callback_data="clients:list:0:a:a")],
        ]))


async def client_add_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clients:addmode:paste | clients:addmode:guided"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    data = q.data
    if data == "clients:addmode:paste":
        ctx.user_data["adding_client"] = {"step": "paste"}
        await q.edit_message_text(
            f"Ok {pn} gửi thông tin khách vào đây nhé 📋\n"
            f"(vd: \"Anh Tuấn 0901234567 cần 2PN dưới 15tr ở Sơn Trà, "
            f"cần gấp trong tuần này\")",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Hủy",
                                     callback_data="clients:cancel")]]))
        return
    # guided: existing step-by-step flow
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

    if step == "paste_fix" and addc.get("fix_text"):
        field = addc.get("fixing_field")
        parsed = addc.get("parsed") or {}
        req = parsed.get("requirements") or {}
        t = text.strip()
        if field == "name":
            if t:
                parsed["name"] = t
        elif field == "phone":
            tl = t.lower()
            if tl in ("bỏ qua", "bo qua", "skip", "chưa có", "chua co", ""):
                parsed["phone"] = ""
            else:
                phones = normalize_phone(text)
                if not phones:
                    await update.message.reply_text(
                        "SĐT này chưa đúng định dạng, gõ lại giúp em nhé?")
                    return
                parsed["phone"] = phones[0]
        elif field == "district":
            dist, _ = listing_parser.parse_district(text)
            if dist:
                req["district"] = dist
            else:
                # keep raw text as district if not in catalog
                req["district"] = t
        elif field == "budget":
            br = listing_parser.parse_query(text)
            req.pop("min_price", None)
            req.pop("max_price", None)
            if br.get("min_price"):
                req["min_price"] = br["min_price"]
            if br.get("max_price"):
                req["max_price"] = br["max_price"]
            if not br.get("min_price") and not br.get("max_price"):
                await update.message.reply_text(
                    "Em chưa hiểu ngân sách, gõ lại giúp em nhé "
                    "(vd: 8-12tr, dưới 15tr)?")
                return
        parsed["requirements"] = req
        addc["parsed"] = parsed
        addc["step"] = "paste_confirm"
        addc.pop("fixing_field", None)
        addc.pop("fix_text", None)
        await update.message.reply_text(
            _paste_confirm_text(parsed),
            parse_mode="HTML",
            reply_markup=_paste_confirm_kb())
        return

    if step == "paste":
        parsed = parse_client_freetext(text)
        addc["parsed"] = parsed
        addc["step"] = "paste_confirm"
        await update.message.reply_text(
            _paste_confirm_text(parsed),
            parse_mode="HTML",
            reply_markup=_paste_confirm_kb())
        return

    if step == "paste_confirm":
        # user typed instead of tapping; re-parse
        parsed = parse_client_freetext(text)
        addc["parsed"] = parsed
        await update.message.reply_text(
            _paste_confirm_text(parsed),
            parse_mode="HTML",
            reply_markup=_paste_confirm_kb())
        return

    if step == "name":
        t = text.strip().lower()
        if t in ("giữ nguyên", "giu nguyen", "giữ", "giu", "ok",
                 "giữ lại") and addc.get("name"):
            name = addc["name"]
        else:
            name = text.strip()
            if not name:
                await update.message.reply_text("Tên khách là gì ạ?")
                return
            addc["name"] = name
        addc["step"] = "phone"
        phone_hint = f" (em có \"{addc['phone']}\"" if addc.get("phone") else ""
        await update.message.reply_text(
            f"SĐT của {name}?{phone_hint} (gõ “bỏ qua” nếu chưa có, "
            f"“giữ nguyên” để giữ)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Bỏ qua",
                                     callback_data="clientadd:skipphone")]]))
        return

    if step == "phone":
        t = text.strip().lower()
        if t in ("giữ nguyên", "giu nguyen", "giữ", "giu", "ok",
                 "giữ lại") and addc.get("phone"):
            pass  # keep pre-filled
        elif t in ("bỏ qua", "bo qua", "skip", ""):
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
            f"Khách cần tìm gì? (vd: 2PN Sơn Trà dưới 15tr)"
            f" — gõ “giữ nguyên” để giữ nhu cầu đã bóc")
        return

    if step == "req":
        t = text.strip().lower()
        if (t in ("giữ nguyên", "giu nguyen", "giữ", "giu", "ok", "giữ lại")
                and addc.get("requirements")):
            pass  # keep pre-filled
        else:
            req = listing_parser.parse_query(text)
            addc["requirements"] = req
            addc["requirements_raw"] = text.strip()
        addc["step"] = "urgency"
        urg_hint = ""
        if addc.get("prefill_urgency"):
            urg_l = CLIENT_URGENCY_LABEL.get(addc["prefill_urgency"], "")
            urg_hint = f" (em đoán: {urg_l} — bấm nút hoặc gõ “giữ nguyên”)"
        await update.message.reply_text(
            f"Mức độ gấp của khách này thế nào ạ?{urg_hint}",
            reply_markup=_client_urgency_kb())
        return

    if step == "urgency":
        # typed fallback for the urgency buttons
        t = text.strip().lower()
        if (t in ("giữ nguyên", "giu nguyen", "giữ", "giu", "ok", "giữ lại")
                and addc.get("prefill_urgency")):
            await _finish_add_client(update.message, ctx, uid, addc,
                                     addc["prefill_urgency"], pn)
            return
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
        [InlineKeyboardButton("🔍 Tìm tin phù hợp",
                              callback_data=f"client:match:{cid}")],
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
    # proactive tip: 1st client milestone (exact count only)
    try:
        import hints as _hints  # lazy: avoid cycle
        n = db.count_clients(uid)
        tip = _hints.tip_after_client(n)
        if tip:
            chat_id = (update_or_msg.message.chat_id
                       if hasattr(update_or_msg, "message")
                       else update_or_msg.chat_id)
            if ctx.bot:
                await ctx.bot.send_message(
                    chat_id=chat_id, text=tip,
                    reply_markup=MENU_KB, parse_mode="HTML")
    except Exception:
        pass


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


async def client_paste_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clients:pasteok | clients:pastefix | clients:fixback"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    addc = ctx.user_data.get("adding_client")
    if not addc or addc.get("step") not in ("paste_confirm", "paste_fix"):
        await q.edit_message_text("Phiên thêm khách đã hết hạn, làm lại nhé 😊",
                                  reply_markup=MENU_KB)
        return
    parsed = addc.get("parsed") or {}
    data = q.data

    if data == "clients:pastefix":
        addc["step"] = "paste_fix"
        await q.edit_message_text(
            "Chỗ nào chưa đúng ạ? 👇",
            reply_markup=_paste_fix_picker_kb())
        return

    if data == "clients:fixback":
        addc["step"] = "paste_confirm"
        addc.pop("fixing_field", None)
        await q.edit_message_text(
            _paste_confirm_text(parsed),
            parse_mode="HTML",
            reply_markup=_paste_confirm_kb())
        return

    if data == "clients:pasteok":
        # Save the client, then ask for extra requirements before matching.
        cid = db.create_client(
            uid, name=parsed.get("name", ""), phone=parsed.get("phone", ""),
            requirements_raw=parsed.get("requirements_raw", ""),
            requirements=parsed.get("requirements") or {},
            urgency=parsed.get("urgency") or "normal")
        ctx.user_data.pop("adding_client", None)
        c = db.get_client(cid)
        ctx.user_data["client_extra_req"] = {"client_id": cid}
        await q.edit_message_text(
            f"Đã lưu khách <b>{c.get('name') or 'mới'}</b> ✓\n\n"
            f"Khách có yêu cầu đặc biệt gì thêm không ạ?\n"
            f"(vd: “cần view biển”, “không chung chủ”, "
            f"“có chỗ để ô tô”)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➡️ Bỏ qua, tìm luôn",
                    callback_data=f"clients:extrareq:skip:{cid}")],
            ]))
        return


async def client_extrareq_skip_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clients:extrareq:skip:<client_id> — skip extra requirements."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    er = ctx.user_data.pop("client_extra_req", None)
    # client ids look like "cli:<hex>" — rejoin everything after the prefix
    cid = ":".join(q.data.split(":")[3:])
    if not er or er.get("client_id") != cid:
        await q.edit_message_text("Phiên này đã hết hạn, làm lại nhé 😊",
                                  reply_markup=MENU_KB)
        return
    c = db.get_client(cid)
    if not c or c["broker_id"] != uid:
        return
    await _show_match_results(q, ctx, uid, cid, c, pn, limit=8)


async def _handle_extra_req(update, ctx, er, text):
    """Text handler for the extra-requirements step (after paste confirm).

    Parses typed requirements, merges structured filters into the client,
    then runs the inventory match with highlight keywords.
    """
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    cid = er.get("client_id")
    c = db.get_client(cid)
    if not c or c["broker_id"] != uid:
        ctx.user_data.pop("client_extra_req", None)
        return
    req = listing_parser.parse_query(text)
    hls = listing_parser.parse_highlights(text)
    updates = {}
    # only fill in blanks — never overwrite what the broker confirmed
    if req.get("bedrooms") is not None and c.get("bedrooms") is None:
        updates["bedrooms"] = req["bedrooms"]
    if req.get("min_price") and not c.get("budget_min"):
        updates["budget_min"] = req["min_price"]
    if req.get("max_price") and not c.get("budget_max"):
        updates["budget_max"] = req["max_price"]
    if req.get("district") and not c.get("district"):
        updates["district"] = req["district"]
    if req.get("property_type") and not c.get("property_type"):
        updates["property_type"] = req["property_type"]
    if req.get("building_name"):
        # building isn't a client column; keep it in the raw text + keywords
        pass
    new_raw = ((c.get("requirements_raw") or "") + "\n+ " + text.strip()
               ).strip()
    updates["requirements_raw"] = new_raw
    db.update_client(cid, **updates)
    extra_keywords = list(hls) if hls else [text.strip()]
    ctx.user_data.pop("client_extra_req", None)
    c = db.get_client(cid)

    async def _deliver(t, kb):
        await update.message.reply_text(t, parse_mode="HTML",
                                        reply_markup=kb)

    await _run_match_and_show(ctx, uid, cid, c, pn, 8, extra_keywords,
                              _deliver)


async def client_paste_fix_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clients:fix:<field> — show fix options for one field."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    addc = ctx.user_data.get("adding_client")
    if not addc or addc.get("step") not in ("paste_confirm", "paste_fix"):
        await q.edit_message_text("Phiên thêm khách đã hết hạn, làm lại nhé 😊",
                                  reply_markup=MENU_KB)
        return
    field = q.data.split(":")[-1]
    addc["step"] = "paste_fix"
    addc["fixing_field"] = field
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Quay lại", callback_data="clients:pastefix")]])

    if field == "name":
        addc["fix_text"] = True
        await q.edit_message_text(
            "Gõ tên đúng của khách vào đây nhé 👇",
            reply_markup=back_kb)
        return
    if field == "phone":
        addc["fix_text"] = True
        await q.edit_message_text(
            "Gõ SĐT đúng của khách vào đây nhé 👇\n(gõ “bỏ qua” nếu chưa có)",
            reply_markup=back_kb)
        return
    if field == "district":
        addc["fix_text"] = True
        await q.edit_message_text(
            "Khách muốn ở khu vực nào ạ? (vd: Sơn Trà)\n"
            "Gõ vào đây nhé 👇",
            reply_markup=back_kb)
        return
    addc["fix_text"] = False

    if field == "bedrooms":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Studio", callback_data="clients:fixval:bedrooms:0"),
             InlineKeyboardButton("1PN", callback_data="clients:fixval:bedrooms:1"),
             InlineKeyboardButton("2PN", callback_data="clients:fixval:bedrooms:2")],
            [InlineKeyboardButton("3PN", callback_data="clients:fixval:bedrooms:3"),
             InlineKeyboardButton("4PN", callback_data="clients:fixval:bedrooms:4"),
             InlineKeyboardButton("5PN+", callback_data="clients:fixval:bedrooms:5")],
            [InlineKeyboardButton("❌ Bỏ chọn", callback_data="clients:fixval:bedrooms:none")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="clients:pastefix")],
        ])
        await q.edit_message_text("Khách cần mấy phòng ngủ ạ? 🛏️",
                                  reply_markup=kb)
        return
    if field == "budget":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Dưới 5tr", callback_data="clients:fixval:budget:5"),
             InlineKeyboardButton("Dưới 10tr", callback_data="clients:fixval:budget:10")],
            [InlineKeyboardButton("Dưới 15tr", callback_data="clients:fixval:budget:15"),
             InlineKeyboardButton("Dưới 20tr", callback_data="clients:fixval:budget:20")],
            [InlineKeyboardButton("Dưới 30tr", callback_data="clients:fixval:budget:30"),
             InlineKeyboardButton("Trên 30tr", callback_data="clients:fixval:budget:min30")],
            [InlineKeyboardButton("✏️ Tự gõ (vd: 8-12tr)",
                                  callback_data="clients:fixval:budget:custom")],
            [InlineKeyboardButton("❌ Bỏ chọn", callback_data="clients:fixval:budget:none")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="clients:pastefix")],
        ])
        await q.edit_message_text("Ngân sách của khách khoảng bao nhiêu ạ? 💰",
                                  reply_markup=kb)
        return
    if field == "urgency":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Gấp — cần trong 1 tuần",
                                  callback_data="clients:fixval:urgency:urgent")],
            [InlineKeyboardButton("🟡 Bình thường — trong 1 tháng",
                                  callback_data="clients:fixval:urgency:normal")],
            [InlineKeyboardButton("🟢 Chỉ tham khảo",
                                  callback_data="clients:fixval:urgency:low")],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="clients:pastefix")],
        ])
        await q.edit_message_text("Mức độ gấp của khách này thế nào ạ? ⏰",
                                  reply_markup=kb)
        return
    # unknown field — back to picker
    await q.edit_message_text("Chỗ nào chưa đúng ạ? 👇",
                              reply_markup=_paste_fix_picker_kb())


async def client_paste_fixval_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: clients:fixval:<field>:<value> — apply a picked fix."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    addc = ctx.user_data.get("adding_client")
    if not addc or addc.get("step") != "paste_fix":
        await q.edit_message_text("Phiên thêm khách đã hết hạn, làm lại nhé 😊",
                                  reply_markup=MENU_KB)
        return
    parts = q.data.split(":")
    field, value = parts[2], parts[3]
    parsed = addc.get("parsed") or {}
    req = parsed.get("requirements") or {}

    if field == "bedrooms":
        if value == "none":
            req.pop("bedrooms", None)
        else:
            req["bedrooms"] = float(value)
    elif field == "budget":
        req.pop("min_price", None)
        req.pop("max_price", None)
        if value == "custom":
            addc["fix_text"] = True
            addc["fixing_field"] = "budget"
            await q.edit_message_text(
                "Gõ ngân sách vào đây nhé (vd: 8-12tr, dưới 15tr) 👇",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Quay lại",
                                         callback_data="clients:pastefix")]]))
            return
        elif value == "min30":
            req["min_price"] = 30_000_000.0
        elif value != "none":
            req["max_price"] = float(value) * 1_000_000
    elif field == "urgency":
        parsed["urgency"] = value

    parsed["requirements"] = req
    addc["parsed"] = parsed
    addc["step"] = "paste_confirm"
    addc.pop("fixing_field", None)
    # back to summary for re-confirmation
    await q.edit_message_text(
        _paste_confirm_text(parsed),
        parse_mode="HTML",
        reply_markup=_paste_confirm_kb())


# ---- client detail ----

def _client_detail_text(c, pn):
    urg_e = CLIENT_URGENCY_EMOJI.get(c.get("urgency") or "normal", "🟡")
    urg_l = CLIENT_URGENCY_LABEL.get(c.get("urgency") or "normal", "Bình thường")
    st_e = CLIENT_STATUS_EMOJI.get(c.get("status") or "new", "🆕")
    st_l = CLIENT_STATUS_LABEL.get(c.get("status") or "new", "mới")
    lines = [
        f"👤 <b>{c.get('name') or '(chưa có tên)'}</b> {urg_e}",
        f"📱 SĐT: {c.get('phone') or 'chưa có'}",
        f"💰 Nhu cầu: {_client_req_summary(c)}",
    ]
    if c.get("requirements_raw"):
        lines.append(f"   <i>“{c['requirements_raw']}”</i>")
    lines.append(f"⏰ Mức gấp: {urg_e} {urg_l}")
    lines.append(f"📌 Trạng thái: {st_e} {st_l}")
    if c.get("notes"):
        lines.append(f"📝 Ghi chú:\n{c['notes']}")
    n_viewed = len(c.get("viewed_listings") or [])
    if n_viewed:
        lines.append(f"🏠 Đã gửi/xem: {n_viewed} tin")
    return "\n".join(lines)


def _client_detail_kb(c, page, s, u_):
    cid = c["id"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Gợi ý tin",
                              callback_data=f"client:match:{cid}"),
         InlineKeyboardButton("📝 Thêm ghi chú",
                              callback_data=f"client:note:{cid}")],
        [InlineKeyboardButton("📤 Gửi tin cho khách 💎",
                              callback_data=f"send2client:start:{cid}")],
        [InlineKeyboardButton("📅 Đặt lịch xem",
                              callback_data=f"vw:c:{cid}"),
         InlineKeyboardButton("💬 Mẫu tin nhắn",
                              callback_data=f"tpl:list:{cid}")],
        [InlineKeyboardButton("📢 Yêu cầu đã đăng",
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
    client_id, _ = parse_client_cb(q.data, "client:status")
    c = db.get_client(client_id)
    if not c:
        return
    kb = []
    # Group into 2 columns for phone readability (was 10 single rows)
    statuses = [st for st in db.CLIENT_STATUSES if st != "cancelled"]
    for i in range(0, len(statuses), 2):
        row = []
        for st in statuses[i:i+2]:
            mark = "● " if c.get("status") == st else ""
            row.append(InlineKeyboardButton(
                f"{mark}{CLIENT_STATUS_EMOJI[st]} {CLIENT_STATUS_LABEL[st]}",
                callback_data=f"client:setstatus:{client_id}:{st}"))
        kb.append(row)
    # Cancelled on its own row at the bottom
    mark = "● " if c.get("status") == "cancelled" else ""
    kb.append([InlineKeyboardButton(
        f"{mark}{CLIENT_STATUS_EMOJI['cancelled']} {CLIENT_STATUS_LABEL['cancelled']}",
        callback_data=f"client:setstatus:{client_id}:cancelled")])
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
    # Auto-prompt for commission on contracted/rented.
    if new_status in ("contracted", "rented"):
        try:
            import feat_deals
            await feat_deals.prompt_commission_for_client(
                uid, client_id, ctx, new_status)
        except Exception:
            log.exception("commission auto-prompt failed")


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


def _manual_picker_content(uid, client_id, c, pn):
    """(text, kb) for the Free-tier manual listing picker."""
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
    return "\n".join(lines), InlineKeyboardMarkup(kb)


def _nomatch_content(uid, client_id, c, pn):
    """(text, kb) when no inventory matches."""
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
    return text, InlineKeyboardMarkup(kb)


def _strip_acc(s):
    return listing_parser._strip_accents(str(s or "").lower())


def _rank_by_keywords(matches, extra_keywords):
    """Stable re-rank: listings whose highlights contain any keyword first."""
    if not extra_keywords:
        return matches
    kws = [_strip_acc(k) for k in extra_keywords if _strip_acc(k)]
    if not kws:
        return matches

    def _score(l):
        hls = (_strip_acc(h) for h in
               (l.get("parsed") or {}).get("highlights") or [])
        hls = list(hls)
        return sum(1 for k in kws if any(k in h for h in hls))

    return sorted(matches, key=_score, reverse=True)


def _completeness_boost_key(l):
    """Sort key: completeness-boosted rank. Higher completeness → higher rank.

    Listings with score >= 80 get +20% boost, < 50 get -10% penalty.
    This incentivizes brokers to fill in complete listing data.
    """
    try:
        comp, _ = completeness_score(l)
    except Exception:
        comp = 50
    # Use a synthetic base of 50 so boost/penalty applies even without
    # a prior relevance score — higher completeness always ranks higher.
    base = 50
    if comp >= 80:
        return base * 1.2
    if comp < 50:
        return base * 0.9
    return base


def is_high_completeness(l):
    """True if listing is complete enough for the ⭐ indicator."""
    try:
        comp, _ = completeness_score(l)
    except Exception:
        return False
    return comp >= 80


def _enrichment_warnings(uid, c, extra_keywords):
    """Find search criteria that can't match well because the broker's
    own listings lack that data.

    Returns [(display_label, missing_count, total)] — max 3, only where
    >30% of active listings are missing the data.
    """
    listings = db.list_broker_listings(
        uid, limit=2000,
        statuses=("draft", "pending_info", "submitted", "uncertain"))
    total = len(listings)
    if not total:
        return []
    warns = []
    crits = []
    if c.get("bedrooms") is not None:
        crits.append(("số phòng ngủ",
                      lambda p: p.get("bedrooms") is None))
    if c.get("budget_min") or c.get("budget_max"):
        crits.append(("giá thuê",
                      lambda p: p.get("price_vnd") is None))
    if c.get("district"):
        crits.append(("khu vực",
                      lambda p: not p.get("district")))
    if c.get("property_type"):
        crits.append(("loại hình",
                      lambda p: not p.get("property_type")))
    for label, is_missing in crits:
        missing = sum(1 for l in listings
                      if is_missing(l.get("parsed") or {}))
        if missing / total > 0.3:
            warns.append((label, missing, total))
    seen = {w[0] for w in warns}
    for kw in (extra_keywords or []):
        kw_n = _strip_acc(kw)
        if not kw_n or kw in seen:
            continue
        has = 0
        for l in listings:
            hls = (l.get("parsed") or {}).get("highlights") or []
            if any(kw_n in _strip_acc(h) for h in hls):
                has += 1
        missing = total - has
        if missing / total > 0.3:
            warns.append((kw, missing, total))
            seen.add(kw)
    return warns[:3]


def _match_hits_content(uid, client_id, c, pn, limit, extra_keywords):
    """(text, kb, matches, warnings) for the Pro auto-match results."""
    matches = db.search_listings(uid, _client_to_search_filters(c),
                                 limit=limit)
    matches = _rank_by_keywords(matches, extra_keywords)
    # Completeness boost: complete listings rank higher (incentive loop)
    matches = sorted(matches, key=_completeness_boost_key, reverse=True)
    kb = []
    for i, l in enumerate(matches, start=1):
        kb.append([InlineKeyboardButton(
            f"{i}. Gửi cho khách",
            callback_data=f"client:send:{client_id}:{l['id']}")])
    kb.append([InlineKeyboardButton(
        "👀 Xem khách",
        callback_data=f"client:{client_id}:0:a:a")])
    kb.append([InlineKeyboardButton(
        "⬅️ Menu", callback_data="menu:back")])
    lines = [f"Em tìm được <b>{len(matches)}</b> tin phù hợp "
             f"với <b>{c.get('name')}</b>:"]
    if extra_keywords:
        lines.append(f"🎯 Ưu tiên: {', '.join(extra_keywords)}")
    for i, l in enumerate(matches, start=1):
        lines.append("")
        star = " ⭐" if is_high_completeness(l) else ""
        lines.append(f"{i}. {listing_line(l)}{star}")
    lines.append("")
    lines.append("Chọn tin để gửi cho khách nhé 👇")
    warnings = _enrichment_warnings(uid, c, extra_keywords)
    if warnings:
        lines.append("")
        lines.append(
            f"Nhưng có <b>{len(warnings)} điểm</b> chưa match được:")
        for label, missing, total in warnings:
            lines.append("")
            lines.append(
                f'⚠️ "{label}" — {missing}/{total} tin của anh '
                f"chưa có thông tin này.")
        lines.append("Lần sau khi nhập tin, anh nhớ điền thêm nhé!")
        lines.append("")
        lines.append("💡 Càng điền đầy đủ, lần sau em match càng chuẩn!")
    return "\n".join(lines), InlineKeyboardMarkup(kb), matches, warnings


async def _run_match_and_show(ctx, uid, client_id, c, pn, limit=8,
                              extra_keywords=None, deliver=None,
                              show_enrich_prompt=True):
    """Shared match core. deliver: async (text, kb) -> None."""
    import feat_premium
    if not feat_premium.requires_tier(uid, "auto_match"):
        text, kb = _manual_picker_content(uid, client_id, c, pn)
        await deliver(text, kb)
        return
    text, kb, matches, warnings = _match_hits_content(
        uid, client_id, c, pn, limit, extra_keywords)
    if not matches:
        text, kb = _nomatch_content(uid, client_id, c, pn)
        await deliver(text, kb)
        return
    if warnings and show_enrich_prompt:
        text += ("\n\nAnh có muốn cập nhật hàng của mình luôn không?\n"
                 "Để lần sau em match chuẩn hơn ạ! 💪")
        rows = list(kb.inline_keyboard) + [
            [InlineKeyboardButton("✅ Cập nhật ngay",
                                  callback_data="enrich:start")],
            [InlineKeyboardButton("⏭️ Để sau",
                                  callback_data="enrich:later")],
        ]
        kb = InlineKeyboardMarkup(rows)
        ctx.user_data["enrich_ctx"] = {
            "client_id": client_id, "limit": limit,
            "extra_keywords": extra_keywords or [],
        }
    await deliver(text, kb)


async def _show_match_results(q, ctx, uid, client_id, c, pn, limit=8,
                              extra_keywords=None, show_enrich_prompt=True):
    """Render inventory match results for a client.

    Pro: auto-match up to `limit` listings. Free: manual picker.
    Called from client_match and the paste intake flow.
    """

    async def _deliver(text, kb):
        await q.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=kb)

    await _run_match_and_show(ctx, uid, client_id, c, pn, limit,
                              extra_keywords, _deliver, show_enrich_prompt)


def _enrich_missing(l):
    """Highlight options from ENRICH_ALL not yet on this listing."""
    hls = set((l.get("parsed") or {}).get("highlights") or [])
    return [o for o in ENRICH_ALL if o not in hls]


async def _enrich_finish(q, ctx, uid):
    en = ctx.user_data.pop("enrich", None) or {}
    total = len(en.get("ids") or [])
    updated = en.get("updated", 0)
    await q.edit_message_text(
        f"Xong! Đã cập nhật <b>{updated}/{total}</b> tin. 🎉\n"
        f"Lần sau em match chuẩn hơn cho anh nhé 😊",
        parse_mode="HTML", reply_markup=MENU_KB)


async def _render_enrich_current(q, ctx, uid):
    """Render the current listing in the enrichment queue (toggle UI).

    Auto-skips listings that became complete or were deleted.
    """
    en = ctx.user_data.get("enrich")
    if not en:
        return
    ids = en["ids"]
    # advance past deleted / already-complete listings
    while en["pos"] < len(ids):
        l = db.get_listing(ids[en["pos"]])
        if not l or l.get("status") == "deleted":
            en["pos"] += 1
            continue
        if not _enrich_missing(l):
            en["pos"] += 1
            continue
        break
    if en["pos"] >= len(ids):
        await _enrich_finish(q, ctx, uid)
        return
    l = db.get_listing(ids[en["pos"]])
    total = len(ids)
    pos = en["pos"]
    pending = set(en.get("pending") or [])
    existing = (l.get("parsed") or {}).get("highlights") or []
    missing = _enrich_missing(l)
    lines = [f"📝 Cập nhật tin <b>{pos + 1}/{total}</b>:", "",
             f"🏠 {listing_line(l)}"]
    if existing:
        lines.append(f"Đã có: ✅ {', '.join(existing)}")
    else:
        lines.append("Đã có: <i>(chưa có điểm nổi bật nào)</i>")
    lines.append("Còn thiếu — chọn thêm nhé:")
    kb = []
    for cat, opts in ENRICH_CATEGORIES:
        cat_missing = [o for o in opts if o in missing]
        if not cat_missing:
            continue
        lines.append("")
        lines.append(f"<b>{cat}:</b>")
        row = []
        for o in cat_missing:
            idx = missing.index(o)
            mark = "✓" if o in pending else "☐"
            row.append(InlineKeyboardButton(
                f"{mark} {o}", callback_data=f"enrich:t:{idx}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
    kb.append([InlineKeyboardButton("✅ Xong tin này →",
                                    callback_data="enrich:next")])
    kb.append([InlineKeyboardButton("⏭️ Bỏ qua tin này",
                                    callback_data="enrich:skip")])
    kb.append([InlineKeyboardButton("🏁 Xong luôn",
                                    callback_data="enrich:done")])
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(kb))


async def enrich_start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:start — build the queue, show first listing."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ctx.user_data.pop("enrich_ctx", None)
    listings = db.list_broker_listings(
        uid, limit=2000,
        statuses=("draft", "pending_info", "submitted", "uncertain"))
    scored = []
    for l in listings:
        m = len(_enrich_missing(l))
        if m:
            scored.append((m, l["id"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    ids = [lid for _, lid in scored[:ENRICH_QUEUE_CAP]]
    if not ids:
        await q.edit_message_text(
            "Tin của anh đã đầy đủ thông tin rồi! 🎉",
            reply_markup=MENU_KB)
        return
    ctx.user_data["enrich"] = {"ids": ids, "pos": 0, "updated": 0,
                               "pending": []}
    await _render_enrich_current(q, ctx, uid)


async def enrich_later_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:later — dismiss the prompt, re-show plain results."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    ectx = ctx.user_data.pop("enrich_ctx", None) or {}
    cid = ectx.get("client_id")
    c = db.get_client(cid) if cid else None
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Ok, khi nào cần thì bảo em nhé 😊",
                                  reply_markup=MENU_KB)
        return
    await _show_match_results(q, ctx, uid, cid, c, pn,
                              limit=ectx.get("limit", 8),
                              extra_keywords=ectx.get("extra_keywords"),
                              show_enrich_prompt=False)


async def enrich_toggle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:t:<idx> — toggle a highlight option."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    en = ctx.user_data.get("enrich")
    if not en or en["pos"] >= len(en["ids"]):
        return
    try:
        idx = int(q.data.split(":")[-1])
    except (ValueError, IndexError):
        return
    l = db.get_listing(en["ids"][en["pos"]])
    if not l or l.get("broker_id") != uid:
        return
    missing = _enrich_missing(l)
    if not 0 <= idx < len(missing):
        return
    opt = missing[idx]
    pending = set(en.get("pending") or [])
    if opt in pending:
        pending.discard(opt)
    else:
        pending.add(opt)
    en["pending"] = sorted(pending)
    await _render_enrich_current(q, ctx, uid)


async def _enrich_advance(q, ctx, uid, save):
    en = ctx.user_data.get("enrich")
    if not en or en["pos"] >= len(en["ids"]):
        return
    lid = en["ids"][en["pos"]]
    if save:
        l = db.get_listing(lid)
        if l and l.get("broker_id") == uid:
            p = l.get("parsed") or {}
            hls = list(p.get("highlights") or [])
            added = [o for o in (en.get("pending") or [])
                     if o not in hls]
            if added:
                p["highlights"] = hls + added
                db.update_listing(lid, parsed=p)
                en["updated"] = en.get("updated", 0) + 1
    en["pos"] += 1
    en["pending"] = []
    await _render_enrich_current(q, ctx, uid)


async def enrich_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:next — save toggles, go to next listing."""
    q = update.callback_query
    await q.answer()
    await _enrich_advance(q, ctx, q.from_user.id, save=True)


async def enrich_skip_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:skip — skip without saving, go to next."""
    q = update.callback_query
    await q.answer()
    await _enrich_advance(q, ctx, q.from_user.id, save=False)


async def enrich_done_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """callback: enrich:done — finish early with summary."""
    q = update.callback_query
    await q.answer()
    await _enrich_finish(q, ctx, q.from_user.id)


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
    await _show_match_results(q, ctx, uid, client_id, c, pn, limit=5)


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

