"""Cross-broker matching/broadcast."""
import asyncio
import json
import logging
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update, WebAppInfo
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
    webapp_url,
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
    score = min(score, 100)
    # Completeness boost: reward well-filled listings, penalize sparse ones.
    # This creates the incentive loop: complete data → ranks higher in match.
    try:
        comp, _ = completeness_score(lst)
    except Exception:
        comp = 50
    if comp >= 80:
        score = min(score * 1.2, 100)
    elif comp < 50:
        score = score * 0.9
    return score


def filter_hard_criteria(listings, requirements):
    """Split listings into (passed, failed_summary) by the lead's hard criteria.

    A listing MUST pass ALL of these to be proposable (no tolerance, no bypass):
    - budget_max: price_vnd <= budget_max
    - bedrooms: exact match (no ±1)
    - district: exact match (no adjacent districts)
    - property_type: exact match (only when the requirement specifies one)
    - status: must be 'submitted' or 'active' (excludes rented/draft/etc.)

    listings: list of listing dicts (with 'parsed' and 'status').
    requirements: dict like the `client` dict passed to score_match()
                  (budget_max, bedrooms, district, property_type).

    Returns (passed_list, failed_summary). failed_summary only contains
    categories that had at least one failure, e.g.:
        {
            "bedrooms": {"required": 2, "have": [1, 3]},
            "budget": {"max": 15000000, "over": [18000000, 20000000]},
            "district": {"required": "Sơn Trà", "have": ["Hải Châu"]},
        }
    """
    passed = []
    br_have = set()
    budget_over = set()
    dist_have = set()
    pt_have = set()
    status_failed = 0

    req_max = _client_float(requirements, "budget_max")
    req_br = _client_float(requirements, "bedrooms")
    req_dist = (requirements.get("district") or "").strip()
    req_pt = (requirements.get("property_type") or "").strip()

    for lst in listings:
        p = lst.get("parsed") or {}
        ok = True

        # status — only live, submitted inventory
        if lst.get("status") not in ("submitted", "active"):
            status_failed += 1
            ok = False

        # budget_max — no tolerance; missing price cannot be verified
        if req_max is not None:
            lp = _parsed_float(lst, "price_vnd")
            if lp is None or lp > req_max:
                if lp is not None:
                    budget_over.add(lp)
                ok = False

        # bedrooms — exact match; missing value cannot be verified
        if req_br is not None:
            lb = _parsed_float(lst, "bedrooms")
            if lb is None or lb != req_br:
                if lb is not None:
                    br_have.add(lb)
                ok = False

        # district — exact match; missing value cannot be verified
        if req_dist:
            ld = (p.get("district") or "").strip()
            if not ld or ld != req_dist:
                if ld:
                    dist_have.add(ld)
                ok = False

        # property_type — exact match, only when the lead specifies one
        if req_pt:
            lpt = (p.get("property_type") or "").strip()
            if not lpt or lpt != req_pt:
                if lpt:
                    pt_have.add(lpt)
                ok = False

        if ok:
            passed.append(lst)

    failed = {}
    if req_br is not None and br_have:
        failed["bedrooms"] = {"required": req_br, "have": sorted(br_have)}
    if req_max is not None and budget_over:
        failed["budget"] = {"max": req_max, "over": sorted(budget_over)[:5]}
    if req_dist and dist_have:
        failed["district"] = {"required": req_dist, "have": sorted(dist_have)}
    if req_pt and pt_have:
        failed["property_type"] = {"required": req_pt,
                                   "have": sorted(pt_have)}
    if status_failed:
        failed["status"] = {"failed": status_failed}

    return passed, failed


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
    """Summary text + relay buttons for the requesting broker.

    Responder identities stay anonymous ("Môi giới N") until both sides
    agree to connect via the relay.
    """
    c = db.get_client(r["client_id"])
    client_name = (c.get("name") if c else None) or "khách"
    lines = [f"🎉 Có {len(resps)} môi giới phản hồi cho khách"
             f" <b>{client_name}</b>:"]
    kb = []
    for i, rp in enumerate(resps, start=1):
        lids, scores = _response_listings(rp)
        best = max([scores.get(lid, 0) for lid in lids] + [0])
        lines.append(f"<b>Môi giới {i}</b> (khớp cao nhất {best}%):")
        for lid in lids:
            lst = db.get_listing(lid)
            if not lst:
                continue
            sc = scores.get(lid)
            score_txt = f" — khớp {sc}%" if sc is not None else ""
            lines.append(f"  • {_listing_brief(lst)}{score_txt}")
        kb.append([InlineKeyboardButton(
            f"💬 Nhắn tin (Môi giới {i})",
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
    """DM the responder a web app deep link to pick listings.

    Web app flow (Khanh 2026-10-16): broker picks up to 5 listings via
    web app instead of Telegram inline keyboard.
    """
    req = r["requirements_summary"]
    url = webapp_url(view="propose", request_id=r["id"])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📱 Chọn tin đề xuất",
                             web_app=WebAppInfo(url=url)),
    ]])
    # Set expiry for the 1-hour submit window
    db.set_match_request_expiry(r["id"])
    await ctx.bot.send_message(
        chat_id=user_id,
        text=(f"✅ Anh đã giữ slot! Em mở web app để chọn tin nhé.\n\n"
              f"Yêu cầu: [{req}]\n"
              f"⏰ Còn 60 phút để submit (tối đa 5 tin)"),
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


async def process_outbox_notifications(ctx):
    """Bot poller: send queued webapp notifications (e.g. slot reopened).

    Call periodically from the bot's job queue. Sends each unsent
    notification to the broker group channel, then marks it sent.
    """
    for n in db.pop_unsent_notifications():
        try:
            if n["ntype"] == "slot_reopened":
                payload = n.get("payload") or {}
                summary = payload.get("summary") or "yêu cầu này"
                r = db.get_match_request(n["request_id"]) if n.get("request_id") else None
                if not r or not config.BROKER_GROUP_ID:
                    continue
                # Reply to the original broadcast message for context
                group_msg_id = r.get("group_message_id")
                await ctx.bot.send_message(
                    chat_id=int(config.BROKER_GROUP_ID),
                    text=(f"📢 Slot vừa mở lại!\n\n"
                          f"Yêu cầu: {summary}\n\n"
                          f"Ai có tin phù hợp thì reply tin gốc ngay nhé! 🤝"),
                    reply_to_message_id=group_msg_id,
                )
            # Mark sent regardless of type (unknown types are dropped)
            db.mark_notification_sent(n["id"])
        except Exception as e:
            log.warning("outbox notification %s failed: %s", n.get("id"), e)


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
    # Debt block: brokers with unpaid deals cannot reserve/submit.
    if db.has_unpaid_debt(replier.id):
        try:
            await msg.reply_text(
                "Anh còn công nợ chưa thanh toán 💰\n"
                "Anh up bill chuyển khoản vào chat riêng với em"
                " để tiếp tục nhé!")
        except Exception as e:
            log.warning("debt block reply failed: %s", e)
        return
    pend = _pending_picks.setdefault(r["id"], set())
    if replier.id in pend:
        try:
            await msg.reply_text(
                "Anh đang chọn tin rồi, check tin nhắn riêng với em nhé! 📩")
        except Exception:
            pass
        return
    # 4th+ responder (recorded + in-pick) -> tell them it's full,
    # but point them to the cross-broker fallback (Khanh 2026-10-16).
    if db.count_responses(r["id"]) + len(pend) >= db.MAX_RESPONDERS:
        try:
            c = db.get_client(r["client_id"])
            summary = _client_req_summary(c) if c else "yêu cầu này"
            await msg.reply_text(
                "Đã hết slot cho yêu cầu này rồi ạ 😔\n\n"
                "💡 Nhưng đừng bỏ cuộc! Có 2 cách vẫn còn cơ hội:\n"
                "• Theo dõi kênh này — nếu người reserve không có tin"
                " phù hợp, slot sẽ mở lại\n"
                "• Dùng Match liên broker trong web app để tìm tin"
                " từ broker khác\n\n"
                f"Yêu cầu: {summary}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔗 Mở match liên broker",
                        web_app=WebAppInfo(url=webapp_url(view="xbroker")),
                    ),
                ]]),
            )
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
    # Create DB row immediately so web app check_broker_slot() works
    # (in-memory _pending_picks alone is invisible to the web app).
    pend.add(replier.id)
    try:
        db.save_propose_response(r["id"], replier.id, [], {})
    except Exception as e:
        log.warning("reserve DB row failed: %s", e)
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


# ---- mutual-consent connect ----

def _contact_card(broker):
    """Format broker contact info for reveal after mutual consent."""
    b = broker or {}
    lines = []
    name = b.get("display_name") or b.get("name") or "Môi giới"
    lines.append(f"👤 {name}")
    if b.get("username"):
        lines.append(f"📱 Telegram: @{b['username']}")
    if b.get("phone"):
        lines.append(f"📞 SĐT: {b['phone']}")
    if b.get("zalo"):
        lines.append(f"💬 Zalo: {b['zalo']}")
    return "\n".join(lines)


async def match_connect_request(update, ctx):
    """Requester taps 'Kết nối' — notify responder, set requester consent."""
    q = update.callback_query
    await q.answer()
    # data: mresp:connect:<request_id>:<responder_id>
    parts = q.data.split(":")
    if len(parts) != 4:
        return
    _, _, req_id, responder_id = parts
    try:
        responder_id = int(responder_id)
    except ValueError:
        return
    uid = q.from_user.id

    row, just_unlocked = db.set_match_consent(
        req_id, responder_id, requester_consent=True)
    if not row:
        await q.edit_message_text("Yêu cầu này không còn nữa.")
        return

    if just_unlocked:
        # Both already consented (responder was faster) — reveal now
        await _reveal_contacts(ctx, req_id, responder_id)
        return

    # Notify responder
    r = db.get_match_request(req_id)
    summary = (r.get("requirements_summary") or "")[:80] if r else ""
    try:
        await ctx.bot.send_message(
            chat_id=responder_id,
            text=(f"🤝 <b>🔍 Cần tìm listing</b> muốn kết nối với anh!\n"
                  f"Yêu cầu: {summary}\n\n"
                  f"Anh đồng ý chia sẻ thông tin liên hệ không?"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Đồng ý kết nối",
                                      callback_data=f"mresp:accept:{req_id}")],
                [InlineKeyboardButton("❌ Từ chối",
                                      callback_data=f"mresp:decline:{req_id}")],
            ]))
    except Exception as e:
        log.warning("connect notify failed: %s", e)
    await q.edit_message_text(
        "Đã gửi yêu cầu kết nối! Em báo anh khi bên kia phản hồi nhé ⏳")


async def match_connect_accept(update, ctx):
    """Responder accepts — set consent, reveal if both agreed."""
    q = update.callback_query
    await q.answer()
    # data: mresp:accept:<request_id>
    parts = q.data.split(":")
    if len(parts) != 3:
        return
    req_id = parts[2]
    uid = q.from_user.id

    row, just_unlocked = db.set_match_consent(
        req_id, uid, responder_consent=True)
    if not row:
        await q.edit_message_text("Yêu cầu này không còn nữa.")
        return

    if just_unlocked:
        await _reveal_contacts(ctx, req_id, uid)
    else:
        await q.edit_message_text(
            "Anh đã đồng ý! Đợi bên kia xác nhận nữa là em kết nối 2 anh nhé ⏳")


async def match_connect_decline(update, ctx):
    """Responder declines — notify requester, reset consents."""
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    if len(parts) != 3:
        return
    req_id = parts[2]
    uid = q.from_user.id

    row = db.get_match_response(req_id, uid)
    if not row:
        return
    # Reset both consents
    db.set_match_consent(req_id, uid,
                         requester_consent=False, responder_consent=False)
    await q.edit_message_text("Đã từ chối kết nối.")
    # Notify requester (stay anonymous)
    r = db.get_match_request(req_id)
    if r:
        try:
            await ctx.bot.send_message(
                chat_id=r["broker_id"],
                text="🏠 <b>Có listing</b> đã từ chối kết nối. "
                     "Anh thử với tin khác nhé!",
                parse_mode="HTML")
        except Exception as e:
            log.warning("decline notify failed: %s", e)


async def _reveal_contacts(ctx, request_id, responder_id):
    """Both consented — send each side the other's contact card via DM."""
    r = db.get_match_request(request_id)
    if not r:
        return
    requester_id = r["broker_id"]
    rb = db.get_broker(responder_id) or {}
    qb = db.get_broker(requester_id) or {}
    db.bump_match_stats(requester_id, contacts_unlocked=1)
    db.bump_match_stats(responder_id, contacts_unlocked=1)
    try:
        await ctx.bot.send_message(
            chat_id=requester_id,
            text=f"🎉 <b>Kết nối thành công!</b>\n\n{_contact_card(rb)}\n\n"
                 f"2 anh tự trao đổi tiếp nhé!",
            parse_mode="HTML")
    except Exception as e:
        log.warning("reveal to requester failed: %s", e)
    try:
        await ctx.bot.send_message(
            chat_id=responder_id,
            text=f"🎉 <b>Kết nối thành công!</b>\n\n{_contact_card(qb)}\n\n"
                 f"2 anh tự trao đổi tiếp nhé!",
            parse_mode="HTML")
    except Exception as e:
        log.warning("reveal to responder failed: %s", e)


# ---- delete client ----



async def cmd_matchstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show this broker's match statistics. Command: /matchstats"""
    uid = update.effective_user.id
    pn = get_pronoun(uid)
    b = db.get_broker(uid)
    if not b:
        await update.message.reply_text(
            "Anh/chị chưa đăng ký. Bấm /start để bắt đầu nhé.")
        return
    reqs = db.list_broker_requests(uid)
    total = len(reqs)
    open_n = sum(1 for r in reqs if r["status"] == "open")
    matched = sum(1 for r in reqs if r["status"] == "matched")
    closed = sum(1 for r in reqs if r["status"] == "closed")
    # responses received across all my requests
    resp_total = 0
    for r in reqs:
        try:
            resps = db.list_responses(r["id"])
            resp_total += len(resps)
        except Exception:
            pass
    avg = (resp_total / total) if total else 0
    await update.message.reply_text(
        f"📊 <b>Thống kê match của {pn}</b>\n\n"
        f"📢 Broadcast đã gửi: {total}\n"
        f"⏳ Đang mở: {open_n}\n"
        f"✅ Đã match: {matched}\n"
        f"🔒 Đã đóng: {closed}\n"
        f"💬 Phản hồi nhận được: {resp_total} (TB {avg:.1f}/broadcast)",
        parse_mode="HTML")
