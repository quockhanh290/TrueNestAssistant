"""Cross-broker matching/broadcast."""
import asyncio
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

from feat_clients import parse_client_cb, _client_req_summary

# ---- Phase 1: inventory verification + match scoring ----

# Da Nang district adjacency for match scoring (+10 for neighbours).
ADJACENT_DISTRICTS = {
    "Sơn Trà": ["Ngũ Hành Sơn", "Hải Châu"],
    "Hải Châu": ["Sơn Trà", "Ngũ Hành Sơn", "Cẩm Lệ", "Thanh Khê",
                 "Liên Chiểu"],
    "Ngũ Hành Sơn": ["Sơn Trà", "Hải Châu", "Cẩm Lệ"],
    "Liên Chiểu": ["Thanh Khê", "Hải Châu"],
    "Cẩm Lệ": ["Hải Châu", "Ngũ Hành Sơn", "Thanh Khê"],
    "Thanh Khê": ["Hải Châu", "Liên Chiểu", "Cẩm Lệ"],
}

MATCH_PASS_SCORE = 50   # minimum score for a listing to be forwarded
MATCH_INVENTORY_MIN = 40  # minimum best-score to pass the inventory gate


def _parsed_float(lst, key):
    try:
        v = (lst.get("parsed") or {}).get(key)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _client_float(c, key):
    try:
        v = c.get(key)
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def score_match(lst, c):
    """0-100 match score between a listing and client requirements.

    Bedrooms: exact +40, off by 1 +20. Price: within budget +30,
    within 20% over max +15. District: exact +20, adjacent +10.
    >= 3 photos +10. Missing requirement on the client side gives
    neutral partial credit (never 0 for unknown).
    """
    score = 0
    # Bedrooms
    lb = _parsed_float(lst, "bedrooms")
    cb = _client_float(c, "bedrooms")
    if lb is not None and cb is not None:
        if lb == cb:
            score += 40
        elif abs(lb - cb) == 1:
            score += 20
    elif cb is None:
        score += 20
    # Price
    lp = _parsed_float(lst, "price_vnd")
    bmin = _client_float(c, "budget_min")
    bmax = _client_float(c, "budget_max")
    if lp is not None and (bmin or bmax):
        over_max = bool(bmax and lp > bmax)
        under_min = bool(bmin and lp < bmin)
        if not over_max and not under_min:
            score += 30
        elif over_max and lp <= bmax * 1.2:
            score += 15
    elif lp is not None:
        score += 15
    # District
    ld = ((lst.get("parsed") or {}).get("district") or "").strip()
    cd = (c.get("district") or "").strip()
    if cd and ld:
        if ld == cd:
            score += 20
        elif ld in ADJACENT_DISTRICTS.get(cd, []):
            score += 10
    elif not cd:
        score += 10
    # Photos
    photos = lst.get("photo_file_ids") or []
    if len(photos) >= 3:
        score += 10
    return min(score, 100)


def _responder_candidates(broker_id, c):
    """Broad inventory fetch for a responder; score_match() ranks them.

    Uses loose DB filters (price with 20% headroom, no district filter)
    then narrows bedrooms to exact +/-1 in Python so scoring branches
    (off-by-one, adjacent district) stay meaningful.
    """
    f = {"status": "active"}
    bmin = _client_float(c, "budget_min")
    bmax = _client_float(c, "budget_max")
    if bmin:
        f["min_price"] = bmin * 0.8
    if bmax:
        f["max_price"] = bmax * 1.2
    listings = db.search_listings(broker_id, f, limit=50)
    cb = _client_float(c, "bedrooms")
    if cb is not None:
        kept = []
        for l in listings:
            lb = _parsed_float(l, "bedrooms")
            if lb is None or abs(lb - cb) <= 1:
                kept.append(l)
        listings = kept
    return listings


# Slots reserved while a responder is picking listings (request_id -> set).
# Prevents a 4th broker grabbing a slot mid-pick; the DB record is only
# created AFTER scoring passes.
_pending_picks = {}


def _pending_count(request_id):
    return len(_pending_picks.get(request_id, set()))

def _broadcast_text(req_summary, urgency, broker_label):
    """Group broadcast message. NEVER includes client name/phone or any
    broker's real identity (role label only until mutual consent)."""
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


# ---- anonymous relay: role-based labels until mutual consent ----

REQUESTER_LABEL = "🔍 Cần tìm listing"   # broker who posted the need
RESPONDER_LABEL = "🏠 Có listing"       # broker who responded with inventory


def _anon_label(uid, r):
    """Role-based anonymous label for a broker in this request."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return "môi giới"
    if uid == r["broker_id"]:
        return REQUESTER_LABEL
    return RESPONDER_LABEL


def _public_label(broker):
    """Real identity label, shown only after mutual consent."""
    b = broker or {}
    if b.get("username"):
        return f"@{b['username']}"
    return b.get("display_name") or b.get("name") or "môi giới"


def _relay_label(uid, r):
    """Label for a broker in this request's context.

    Anonymous (role-based) until both sides consented to connect;
    after mutual consent the real identity is shown.
    """
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return "môi giới"
    if uid != r["broker_id"]:
        rp = db.get_match_response(r["id"], uid)
        if rp and rp.get("requester_consent") and rp.get("responder_consent"):
            return _public_label(db.get_broker(uid))
    return _anon_label(uid, r)


def _contact_card(broker):
    """Contact info card revealed after mutual consent."""
    b = broker or {}
    lines = [f"👤 {b.get('display_name') or b.get('name') or 'Môi giới'}"]
    if b.get("username"):
        lines.append(f"✈️ Telegram: @{b['username']}")
    if b.get("phone"):
        lines.append(f"📱 SĐT: {b['phone']}")
    if b.get("zalo"):
        lines.append(f"💬 Zalo: {b['zalo']}")
    if b.get("facebook"):
        lines.append(f"📘 Facebook: {b['facebook']}")
    return "\n".join(lines)


def _listing_brief(lst):
    """Short '🏠 2PN Sơn Trà 12tr' for a listing (reads parsed fields)."""
    p = lst.get("parsed") or {}
    br = p.get("bedrooms")
    try:
        bed_txt = ("Studio " if float(br) == 0 else f"{int(float(br))}PN ") \
            if br is not None else ""
    except (TypeError, ValueError):
        bed_txt = ""
    dist = (p.get("district") or "").strip()
    price = p.get("price_vnd")
    return f"🏠 {bed_txt}{dist} {fmt_price(price)}".strip()


def _response_listings(rp):
    """(listing_ids, match_scores) from a match_responses row, JSON-decoded."""
    try:
        lids = json.loads(rp.get("listing_ids") or "[]")
    except (ValueError, TypeError):
        lids = []
    try:
        scores = json.loads(rp.get("match_scores") or "{}")
    except (ValueError, TypeError):
        scores = {}
    if not lids and rp.get("listing_id"):
        lids = [rp["listing_id"]]  # legacy rows
    return lids, scores


def _responses_text_kb(r, resps):
    """Summary text + relay/connect buttons for the requesting broker.

    Responder identities stay anonymous (role-based labels) until both
    sides agree to connect via the connect flow.
    """
    c = db.get_client(r["client_id"])
    client_name = (c.get("name") if c else None) or "khách"
    lines = [f"🎉 Có {len(resps)} phản hồi cho khách"
             f" <b>{client_name}</b>:"]
    kb = []
    for rp in resps:
        lids, scores = _response_listings(rp)
        best = max([scores.get(lid, 0) for lid in lids] + [0])
        lines.append(f"<b>{RESPONDER_LABEL}</b> (khớp cao nhất {best}%):")
        for lid in lids:
            lst = db.get_listing(lid)
            if not lst:
                continue
            sc = scores.get(lid)
            score_txt = f" — khớp {sc}%" if sc is not None else ""
            lines.append(f"  • {_listing_brief(lst)}{score_txt}")
        rid = rp["responder_broker_id"]
        msg_cb = f"mresp:msg:{r['id']}:{rid}"
        if rp.get("requester_consent") and rp.get("responder_consent"):
            lines.append("  ✅ Đã kết nối — xem SĐT trong tin nhắn riêng nhé")
            kb.append([InlineKeyboardButton(
                f"💬 Nhắn tin ({RESPONDER_LABEL})", callback_data=msg_cb)])
        elif rp.get("requester_consent"):
            lines.append("  ⏳ Đã gửi lời mời kết nối, đang chờ phản hồi…")
            kb.append([InlineKeyboardButton(
                f"💬 Nhắn tin ({RESPONDER_LABEL})", callback_data=msg_cb)])
        else:
            kb.append([
                InlineKeyboardButton(
                    f"💬 Nhắn tin", callback_data=msg_cb),
                InlineKeyboardButton(
                    "🤝 Kết nối",
                    callback_data=f"mresp:connect:{r['id']}:{rid}"),
            ])
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
    # broadcast stays anonymous: role label only, real identity is
    # revealed only after mutual consent in the connect flow
    broker_label = REQUESTER_LABEL
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
                                   r["urgency"], REQUESTER_LABEL)
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


def _parse_mpick_cb(data):
    """mpick:toggle:mr:<hex>:tg:<hex> | mpick:send:mr:<hex> |
    mpick:cancel:mr:<hex>. Both ids contain a colon."""
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    mr_id = (parts[2] + ":" + parts[3]) if len(parts) > 3 else ""
    listing_id = (parts[4] + ":" + parts[5]) if len(parts) > 5 else ""
    return act, mr_id, listing_id


def _picker_text_kb(pick):
    """Render the listing picker (toggle up to 3)."""
    cands = pick["candidates"]
    sel = set(pick["selected"])
    lines = [f"Chọn tối đa 3 tin phù hợp nhất để gửi"
             f" ({len(sel)}/3 đã chọn):"]
    kb = []
    for i, cd in enumerate(cands):
        mark = "✅" if cd["id"] in sel else "⬜"
        lines.append(f"{mark} {i + 1}. {_listing_brief(cd['listing'])}"
                     f" — khớp {cd['score']}%")
        kb.append([InlineKeyboardButton(
            f"{mark} Tin {i + 1}",
            callback_data=f"mpick:toggle:{pick['request_id']}:{cd['id']}")])
    kb.append([InlineKeyboardButton(
        f"✅ Gửi {len(sel)} tin này",
        callback_data=f"mpick:send:{pick['request_id']}")])
    kb.append([InlineKeyboardButton(
        "❌ Hủy", callback_data=f"mpick:cancel:{pick['request_id']}")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def _send_picker_dm(ctx, user_id, r, scored):
    """DM the responder their top-5 scored listings to pick from."""
    top5 = scored[:5]
    pick = {
        "request_id": r["id"],
        "candidates": [
            {"id": lst["id"], "score": sc, "listing": lst}
            for lst, sc in top5
        ],
        "selected": [],
    }
    # NOTE: user_data is per-user across chats, so setting it here in the
    # group handler is visible when they tap buttons in DM.
    ctx.application.user_data[user_id]["match_picking"] = pick
    text, kb = _picker_text_kb(pick)
    c = db.get_client(r["client_id"])
    req = r["requirements_summary"]
    await ctx.bot.send_message(
        chat_id=user_id,
        text=(f"Anh có {len(top5)} tin phù hợp với yêu cầu [{req}].\n\n"
              + text),
        reply_markup=kb)


async def match_pick_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Toggle one listing in the responder's pick (max 3)."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, listing_id = _parse_mpick_cb(q.data)
    pick = ctx.user_data.get("match_picking")
    if not pick or pick["request_id"] != mr_id:
        await q.edit_message_text(
            "Phiên chọn tin đã hết hạn, anh reply lại trong nhóm nhé.")
        return
    sel = pick["selected"]
    if listing_id in sel:
        sel.remove(listing_id)
    elif len(sel) >= 3:
        await q.answer("Tối đa 3 tin thôi ạ!", show_alert=True)
        return
    else:
        sel.append(listing_id)
    text, kb = _picker_text_kb(pick)
    await q.edit_message_text(text, reply_markup=kb)


async def match_pick_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Responder cancels picking; frees the reserved slot."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mpick_cb(q.data)
    ctx.user_data.pop("match_picking", None)
    _pending_picks.get(mr_id, set()).discard(uid)
    await q.edit_message_text(
        "Dạ ok, em hủy rồi nhé. Anh có thể reply lại trong nhóm"
        " bất cứ lúc nào.")


async def _notify_new_response(ctx, r, n):
    """DM the requesting broker: heads-up for 1st/2nd, full summary on 3rd."""
    if n >= db.MAX_RESPONDERS:
        db.update_match_request(r["id"], status="matched")
        await _send_full_summary(ctx, r)
        return
    c = db.get_client(r["client_id"])
    client_name = (c.get("name") if c else None) or "khách"
    try:
        await ctx.bot.send_message(
            chat_id=r["broker_id"],
            text=(f"🎉 Có môi giới phản hồi cho khách <b>{client_name}</b>"
                  f" ({n}/{db.MAX_RESPONDERS})."),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "👀 Xem phản hồi",
                    callback_data=f"mresp:view:{r['id']}")]]))
    except Exception as e:
        log.warning("notify broker failed: %s", e)


async def match_pick_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Responder submits picks -> score them -> record only if >= 1 passes."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mpick_cb(q.data)
    pick = ctx.user_data.get("match_picking")
    if not pick or pick["request_id"] != mr_id:
        await q.edit_message_text(
            "Phiên chọn tin đã hết hạn, anh reply lại trong nhóm nhé.")
        return
    r = db.get_match_request(mr_id)
    if not r or r["status"] not in ("open", "matched"):
        ctx.user_data.pop("match_picking", None)
        _pending_picks.get(mr_id, set()).discard(uid)
        await q.edit_message_text("Yêu cầu này đã đóng rồi ạ.")
        return
    c = db.get_client(r["client_id"])
    sel_ids = list(pick["selected"])
    if not sel_ids:
        await q.answer("Anh chọn ít nhất 1 tin nhé!", show_alert=True)
        return
    by_id = {cd["id"]: cd for cd in pick["candidates"]}
    passed = []
    for lid in sel_ids:
        lst = db.get_listing(lid)
        if not lst:
            continue
        sc = score_match(lst, c) if c else 0
        if sc >= MATCH_PASS_SCORE:
            passed.append((lid, sc))
    if not passed:
        text, kb = _picker_text_kb(pick)
        await q.edit_message_text(
            f"⚠️ Các tin này chưa đủ khớp (cần ≥{MATCH_PASS_SCORE}đ)."
            f" Anh chọn tin khác nhé.\n\n{text}",
            reply_markup=kb)
        return
    listing_ids = [lid for lid, _ in passed]
    match_scores = {lid: sc for lid, sc in passed}
    ok, n = db.add_match_response(
        mr_id, uid, q.from_user.username,
        listing_ids=listing_ids, match_scores=match_scores)
    ctx.user_data.pop("match_picking", None)
    _pending_picks.get(mr_id, set()).discard(uid)
    if not ok:
        await q.edit_message_text("Em đã nhận tin của anh rồi nhé ✓")
        return
    await q.edit_message_text(
        f"Em đã gửi {len(passed)} tin cho bên cần nhà rồi nhé ✓")
    r = db.get_match_request(mr_id)
    if r:
        await _notify_new_response(ctx, r, n)


async def on_group_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Detect replies to broadcast messages, verify the replier's inventory,
    and DM them a listing picker. The DB response record is only created
    AFTER scoring passes (slot reserved via _pending_picks meanwhile)."""
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
    if db.has_responded(r["id"], replier.id):
        return  # already recorded: ignore silently
    pend = _pending_picks.setdefault(r["id"], set())
    if replier.id in pend:
        try:
            await msg.reply_text(
                "Anh đang chọn tin rồi, check tin nhắn riêng với em nhé! 📩")
        except Exception:
            pass
        return
    # 4th+ responder (recorded + in-pick) -> tell them it's full.
    if db.count_responses(r["id"]) + len(pend) >= db.MAX_RESPONDERS:
        try:
            await msg.reply_text(
                "Yêu cầu này đã đủ 3 môi giới phản hồi rồi ạ.")
        except Exception as e:
            log.warning("full reply failed: %s", e)
        return
    # ---- inventory verification ----
    c = db.get_client(r["client_id"])
    if not c:
        return
    candidates = _responder_candidates(replier.id, c)
    scored = sorted(((l, score_match(l, c)) for l in candidates),
                    key=lambda t: t[1], reverse=True)
    if not scored or scored[0][1] < MATCH_INVENTORY_MIN:
        try:
            await msg.reply_text(
                "Anh chưa có tin nào phù hợp với yêu cầu này. "
                "Anh gửi tin vào bot trước đã nhé! 📝")
        except Exception as e:
            log.warning("no-match reply failed: %s", e)
        return
    # Reserve the slot, then DM the picker.
    pend.add(replier.id)
    try:
        await _send_picker_dm(ctx, replier.id, r, scored)
    except Exception as e:
        log.warning("picker DM failed: %s", e)
        pend.discard(replier.id)
        try:
            await msg.reply_text(
                "Em không nhắn riêng được cho anh. Anh mở chat riêng"
                " với em và bấm /start trước nhé!")
        except Exception:
            pass
        return
    try:
        await msg.reply_text(
            "Em đã gửi danh sách tin phù hợp vào tin nhắn riêng,"
            " anh check nhé! 📩")
    except Exception:
        pass


async def match_responses_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show the current responder list with relay buttons."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    if not r or r["broker_id"] != uid:
        return
    db.mark_responses_seen(r["id"])
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


# ---- mutual-consent connect: reveal real contact info ----

async def match_connect_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Requester taps 'Kết nối' -> ask the responder to accept/decline."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, target = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    if not r or r["broker_id"] != uid or not target.isdigit():
        return
    responder_id = int(target)
    rp = db.get_match_response(mr_id, responder_id)
    if not rp:
        return
    if rp.get("requester_consent") and rp.get("responder_consent"):
        await q.answer("Đã kết nối rồi nhé!", show_alert=True)
        return
    db.set_match_consent(mr_id, responder_id, requester_consent=1)
    pn = get_pronoun(uid)
    try:
        await ctx.bot.send_message(
            chat_id=responder_id,
            text=(f"🤝 <b>{REQUESTER_LABEL}</b> muốn kết nối trực tiếp"
                  f" với {pn} về yêu cầu [{r['requirements_summary']}].\n\n"
                  f"Đồng ý thì em gửi thông tin liên hệ của 2 bên cho nhau nhé.",
                  ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Đồng ý kết nối",
                    callback_data=f"mresp:accept:{mr_id}")],
                [InlineKeyboardButton(
                    "❌ Từ chối",
                    callback_data=f"mresp:decline:{mr_id}")],
            ]))
    except Exception as e:
        log.warning("connect request DM failed: %s", e)
        await q.edit_message_text(
            "Em chưa nhắn được cho bên kia, anh thử lại sau nhé.")
        return
    await q.edit_message_text(
        "Em đã gửi lời mời kết nối rồi nhé ✓\n"
        "Bên kia đồng ý là em gửi thông tin liên hệ ngay.")


async def match_connect_accept(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Responder accepts -> mutual consent: reveal contacts to both sides."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    rp = db.get_match_response(mr_id, uid) if r else None
    if not r or not rp:
        await q.edit_message_text("Yêu cầu này không còn nữa ạ.")
        return
    if not rp.get("requester_consent"):
        await q.edit_message_text("Bên kia đã rút lời mời rồi ạ.")
        return
    _, just_unlocked = db.set_match_consent(mr_id, uid, responder_consent=1)
    requester_id = r["broker_id"]
    if just_unlocked:
        db.bump_match_stats(requester_id, contacts_unlocked=1)
        db.bump_match_stats(uid, contacts_unlocked=1)
        req_card = _contact_card(db.get_broker(requester_id))
        resp_card = _contact_card(db.get_broker(uid))
        try:
            await ctx.bot.send_message(
                chat_id=requester_id,
                text=(f"🎉 <b>{RESPONDER_LABEL}</b> đã đồng ý kết nối!\n\n"
                      f"{resp_card}\n\n"
                      f"Hai bên tự trao đổi tiếp nhé 🤝"),
                parse_mode="HTML")
        except Exception as e:
            log.warning("unlock DM to requester failed: %s", e)
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text=(f"🎉 Đã kết nối với <b>{REQUESTER_LABEL}</b>!\n\n"
                      f"{req_card}\n\n"
                      f"Hai bên tự trao đổi tiếp nhé 🤝"),
                parse_mode="HTML")
        except Exception as e:
            log.warning("unlock DM to responder failed: %s", e)
    await q.edit_message_text(
        "Đã kết nối ✓ Em đã gửi thông tin liên hệ của 2 bên rồi nhé.")


async def match_connect_decline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Responder declines -> notify the requester (stays anonymous)."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, mr_id, _ = _parse_mresp_cb(q.data)
    r = db.get_match_request(mr_id)
    rp = db.get_match_response(mr_id, uid) if r else None
    if not r or not rp:
        await q.edit_message_text("Yêu cầu này không còn nữa ạ.")
        return
    db.set_match_consent(mr_id, uid, requester_consent=0)
    try:
        await ctx.bot.send_message(
            chat_id=r["broker_id"],
            text=(f"{RESPONDER_LABEL} đã từ chối kết nối cho yêu cầu"
                  f" [{r['requirements_summary']}]."),
            parse_mode="HTML")
    except Exception as e:
        log.warning("decline notify failed: %s", e)
    await q.edit_message_text("Dạ ok, em đã báo lại bên kia rồi nhé.")


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


# ---- admin: match demand dashboard ----

def _broker_short(b):
    b = b or {}
    if b.get("username"):
        return f"@{b['username']}"
    return b.get("display_name") or b.get("name") or f"id:{b.get('user_id')}"


async def cmd_matchstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/matchstats — admin-only cross-broker match demand dashboard.

    Used to decide whether Phase 2 (per-match fee) is worth building.
    """
    if update.effective_user.id != config.ADMIN_TELEGRAM_ID:
        await update.message.reply_text("⛔ Lệnh này chỉ dành cho admin.")
        return
    stats = db.match_overview_stats()
    w, m = stats["week"], stats["month"]

    def conv(s):
        if not s["responses"]:
            return "—"
        return f"{s['unlocks'] / s['responses'] * 100:.0f}%"

    lines = [
        "📊 <b>MATCH STATS</b>",
        "",
        f"🕐 <b>7 ngày:</b> {w['requests']} yêu cầu ·"
        f" {w['responses']} phản hồi · {w['unlocks']} kết nối",
        f"🗓️ <b>30 ngày:</b> {m['requests']} yêu cầu ·"
        f" {m['responses']} phản hồi · {m['unlocks']} kết nối",
        f"📈 <b>Tỉ lệ mở khóa liên hệ</b> (kết nối/phản hồi):"
        f" 7d {conv(w)} · 30d {conv(m)}",
        "",
        "🏆 <b>Top đăng nhu cầu:</b>",
    ]
    top_req = db.top_match_requesters(limit=5)
    if top_req:
        for i, b in enumerate(top_req, start=1):
            lines.append(f"  {i}. {_broker_short(b)}"
                         f" — {b['match_requests_sent']} yêu cầu")
    else:
        lines.append("  (chưa có)")
    lines.append("")
    lines.append("🤝 <b>Top phản hồi:</b>")
    top_resp = db.top_match_responders(limit=5)
    if top_resp:
        for i, b in enumerate(top_resp, start=1):
            lines.append(f"  {i}. {_broker_short(b)}"
                         f" — {b['responses']} phản hồi")
    else:
        lines.append("  (chưa có)")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ---- delete client ----

