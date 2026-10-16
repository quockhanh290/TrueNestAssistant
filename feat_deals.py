"""Commission tracking."""
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

def _month_bounds(yyyymm):
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    start = datetime.datetime(y, m, 1)
    end = (datetime.datetime(y + 1, 1, 1) if m == 12
           else datetime.datetime(y, m + 1, 1))
    return start.timestamp(), end.timestamp()


def _cur_yyyymm():
    return datetime.datetime.now().strftime("%Y%m")


def _fmt_month_vn(yyyymm):
    return f"THÁNG {int(yyyymm[4:])}/{yyyymm[:4]}"


def _fmt_money_full(v):
    return f"{int(v or 0):,}".replace(",", ".") + "đ"


def _deal_line(d):
    dt = datetime.datetime.fromtimestamp(d["closed_at"]).strftime("%d/%m")
    lst = ""
    if d.get("listing_id"):
        l = db.get_listing(d["listing_id"])
        if l:
            p = l["parsed"]
            br = p.get("bedrooms")
            br_s = ("studio" if br == 0.0
                    else (f"{int(br)}PN" if br else "?PN"))
            loc = p.get("building_name") or p.get("district") or "?"
            lst = f"🏠 {br_s} {loc} - "
    cname = d.get("client_name") or "?"
    return (f"• {dt} - {lst}👤 {cname} - "
            f"{fmt_price(d.get('commission_vnd'))}")


async def cmd_commission(update, ctx):
    import feat_premium
    uid = update.effective_user.id
    if not feat_premium.requires_tier(uid, "commission"):
        await feat_premium.send_gate(update, "commission", uid)
        return
    await _send_commission(update.message, uid, _cur_yyyymm(), edit=False)


async def _send_commission(msg_or_q, uid, yyyymm, edit):
    pn = get_pronoun(uid)
    start, end = _month_bounds(yyyymm)
    deals = db.list_deals(uid, start, end)
    total = sum(d["commission_vnd"] or 0 for d in deals)
    lines = [f"💰 <b>{_fmt_month_vn(yyyymm)}</b>",
             f"✅ {len(deals)} deal đã chốt",
             f"💵 Tổng hoa hồng: {_fmt_money_full(total)}"]
    if deals:
        lines.append("\nChi tiết:")
        lines += [_deal_line(d) for d in deals]
    else:
        lines.append(f"\n{pn.capitalize()} chưa có deal nào trong tháng này.")
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    pm = (datetime.datetime(y, m - 1, 1) if m > 1
          else datetime.datetime(y - 1, 12, 1))
    kb = [
        [InlineKeyboardButton("➕ Thêm deal mới", callback_data="deal:new")],
        [InlineKeyboardButton("◀ Tháng trước",
                              callback_data=f"cms:m:{pm.strftime('%Y%m')}"),
         InlineKeyboardButton("Tháng này", callback_data="cms:cur")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ]
    markup = InlineKeyboardMarkup(kb)
    if edit:
        await msg_or_q.edit_message_text("\n".join(lines), parse_mode="HTML",
                                         reply_markup=markup)
    else:
        await msg_or_q.reply_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=markup)


async def cms_nav(update, ctx):
    q = update.callback_query
    await q.answer()
    rest = q.data[len("cms:"):]
    yyyymm = _cur_yyyymm() if rest == "cur" else rest[2:]
    await _send_commission(q, update.effective_user.id, yyyymm, edit=True)


async def deal_new(update, ctx):
    """Smart deal entry: suggest (listing, client) pairs first."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    pairs = db.suggested_deal_pairs(uid)
    if not pairs:
        clients = db.list_clients(uid, limit=10)
        if not clients:
            await q.edit_message_text(
                f"{pn.capitalize()} chưa có khách ở trạng thái đàm phán/cọc/thuê "
                f"để nhập deal. Thêm khách trước nhé!",
                reply_markup=MENU_KB)
            return
        kb = [[InlineKeyboardButton(
            f"👤 {c.get('name') or '(chưa có tên)'}",
            callback_data=f"deal:mc:{c['id']}")] for c in clients]
        kb.append([InlineKeyboardButton("❌ Hủy", callback_data="cms:cur")])
        await q.edit_message_text(
            "Chưa có cặp gợi ý. Chọn khách cho deal này:",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    st_label = {"rented": "đã thuê", "deposited": "đã cọc",
                "negotiating": "đàm phán"}
    lines = ["Chọn deal để nhập hoa hồng:"]
    kb = []
    for i, pr in enumerate(pairs, 1):
        c, l = pr["client"], pr["listing"]
        p = l["parsed"]
        br = p.get("bedrooms")
        br_s = ("studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN"))
        loc = p.get("building_name") or p.get("district") or "?"
        cname = c.get("name") or "?"
        lines.append(
            f"\n{i}. 🏠 {br_s} {loc} — 👤 {cname}\n"
            f"   (trạng thái: {st_label.get(c['status'], c['status'])})")
        kb.append([InlineKeyboardButton(
            f"{i}. {cname} — {br_s} {loc}",
            callback_data=f"deal:pick:{c['id']}:{l['id']}")])
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="cms:cur")])
    await q.edit_message_text("\n".join(lines),
                              reply_markup=InlineKeyboardMarkup(kb))


def _parse_deal_pick(data):
    """'deal:pick:cli:xxx:tg:yyy' -> ('cli:xxx', 'tg:yyy')."""
    payload = data[len("deal:pick:"):]
    i = payload.find(":tg:")
    if i < 0:
        return None, None
    return payload[:i], payload[i + 1:]


async def deal_pick(update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    client_id, listing_id = _parse_deal_pick(q.data)
    c = db.get_client(client_id) if client_id else None
    l = db.get_listing(listing_id) if listing_id else None
    if (not c or c["broker_id"] != uid or not l
            or l["broker_id"] != uid):
        await q.edit_message_text("Thông tin deal không còn hợp lệ.",
                                  reply_markup=MENU_KB)
        return
    await _ask_deal_amount(q, ctx, uid, c, l, edit=True)


async def deal_pick_client(update, ctx):
    """Manual flow step 1: client chosen, now pick a listing."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    client_id = q.data[len("deal:mc:"):]
    c = db.get_client(client_id)
    if not c or c["broker_id"] != uid:
        await q.edit_message_text("Khách này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    # Pre-fill: if this client already has a chosen listing, skip the pick.
    l = _get_client_choice_listing(c)
    if l and l.get("broker_id") == uid:
        await _ask_deal_amount(q, ctx, uid, c, l, edit=True)
        return
    ctx.user_data["deal_new"] = {"client_id": client_id}
    listings = db.search_listings(uid, {"status": "active"}, limit=10)
    kb = [[InlineKeyboardButton(
        listing_line(l).splitlines()[0],
        callback_data=f"deal:ml:{l['id']}")] for l in listings]
    kb.append([InlineKeyboardButton("❌ Hủy", callback_data="cms:cur")])
    await q.edit_message_text(
        f"Deal cho <b>{c.get('name')}</b> — chọn tin:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def deal_pick_listing(update, ctx):
    """Manual flow step 2: listing chosen, ask for the amount."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    dn = ctx.user_data.pop("deal_new", None)
    listing_id = q.data[len("deal:ml:"):]
    c = db.get_client(dn["client_id"]) if dn else None
    l = db.get_listing(listing_id)
    if (not c or c["broker_id"] != uid or not l
            or l["broker_id"] != uid):
        await q.edit_message_text("Thông tin deal không còn hợp lệ.",
                                  reply_markup=MENU_KB)
        return
    await _ask_deal_amount(q, ctx, uid, c, l, edit=True)


async def _ask_deal_amount(msg_or_q, ctx, uid, c, l, edit):
    p = l["parsed"]
    br = p.get("bedrooms")
    br_s = ("studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN"))
    loc = p.get("building_name") or p.get("district") or "?"
    ctx.user_data["adding_deal"] = {"client_id": c["id"],
                                    "listing_id": l["id"],
                                    "client_name": c.get("name") or ""}
    text = (f"Hoa hồng deal này bao nhiêu ạ? 🎉\n"
            f"👤 {c.get('name') or '?'} — 🏠 {br_s} {loc}\n"
            f"(vd: 15tr, hoặc gõ “bỏ qua”)")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Hủy", callback_data="cms:cur")]])
    if edit:
        await msg_or_q.edit_message_text(text, reply_markup=kb)
    else:
        await msg_or_q.reply_text(text, reply_markup=kb)


async def _handle_add_deal(update, ctx, ad, text):
    uid = update.effective_user.id
    t = text.strip().lower()
    if t in ("bỏ qua", "bo qua", "skip", "hủy", "huy", "cancel"):
        ctx.user_data.pop("adding_deal", None)
        await update.message.reply_text("Ok, em không lưu deal này ạ.",
                                        reply_markup=MENU_KB)
        return
    val, _ = listing_parser.parse_price(text)
    if not val or val <= 0:
        await update.message.reply_text(
            "Em chưa hiểu số tiền, anh nhập lại giúp em nhé? (vd: 15tr)")
        return
    db.create_deal(uid, client_id=ad.get("client_id"),
                   client_name=ad.get("client_name") or "",
                   listing_id=ad.get("listing_id"),
                   commission_vnd=val)
    c = db.get_client(ad["client_id"]) if ad.get("client_id") else None
    if c and c["status"] != "rented":
        db.update_client(ad["client_id"], status="rented")
    ctx.user_data.pop("adding_deal", None)
    await update.message.reply_text(
        f"Đã lưu deal ✓ Hoa hồng {fmt_price(val)} 🎉",
        reply_markup=MENU_KB)


# ---------------------------------------------------------------- auto prompt

# Statuses that trigger the automatic commission prompt.
COMMISSION_TRIGGER_STATUSES = ("contracted", "rented")


def _get_client_choice_listing(c):
    """Return the listing from client_choice, or None.

    Defensive: client_choice column/function may not exist in older DBs.
    choice format: {"id": "tg:xxx", "chosen_at": ...} or plain id string.
    """
    if not c:
        return None
    choice = c.get("client_choice")
    if not choice:
        return None
    if isinstance(choice, str):
        try:
            choice = json.loads(choice)
        except (json.JSONDecodeError, ValueError):
            pass  # plain string id
    lid = choice.get("id") if isinstance(choice, dict) else choice
    if not lid:
        return None
    try:
        return db.get_listing(lid)
    except Exception:
        return None


def _listing_short(l):
    """Short listing label: '2PN An Thượng, 15tr'."""
    p = l.get("parsed") or {}
    br = p.get("bedrooms")
    br_s = ("studio" if br == 0.0
            else (f"{int(br)}PN" if br else "?PN"))
    loc = p.get("building_name") or p.get("district") or "?"
    price = p.get("price")
    price_s = f", {fmt_price(price)}" if price else ""
    return f"{br_s} {loc}{price_s}"


async def prompt_commission_for_client(uid, client_id, ctx, new_status=None):
    """Auto-prompt for commission when a client reaches contracted/rented.

    Called from client_set_status hook. If the client has a chosen listing
    (client_choice), we already know the pair — just ask for the amount.
    Otherwise fall back to the manual pick flow.
    """
    pn = get_pronoun(uid)
    c = db.get_client(client_id)
    if not c or c.get("broker_id") != uid:
        return
    st_label = {"contracted": "kí HĐ", "rented": "hoàn thành"}.get(
        new_status or c.get("status"), "chốt deal")

    l = _get_client_choice_listing(c)
    cname = c.get("name") or "Khách"

    if l and l.get("broker_id") == uid:
        # We know the pair — ask for amount directly.
        ctx.user_data["adding_deal"] = {
            "client_id": c["id"],
            "listing_id": l["id"],
            "client_name": cname,
        }
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭️ Bỏ qua",
                                 callback_data="deal:skip_auto")]])
        await ctx.bot.send_message(
            uid,
            f"🎉 Chúc mừng {pn}!\n"
            f"Khách <b>{cname}</b> đã {st_label} căn "
            f"<b>{_listing_short(l)}</b>!\n\n"
            f"Hoa hồng deal này bao nhiêu ạ?\n"
            f"(Gõ số tiền, vd: 7500000)",
            parse_mode="HTML",
            reply_markup=kb)
    else:
        # No known listing — fall back to manual pick.
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Nhập deal thủ công",
                                  callback_data="deal:new")],
            [InlineKeyboardButton("⏭️ Bỏ qua",
                                  callback_data="deal:skip_auto")],
        ])
        await ctx.bot.send_message(
            uid,
            f"🎉 Chúc mừng {pn}! Khách <b>{cname}</b> đã {st_label}!\n\n"
            f"Em chưa biết căn nào, {pn} chọn giúp em nhé:",
            parse_mode="HTML",
            reply_markup=kb)


async def deal_skip_auto(update, ctx):
    """Broker skipped the auto commission prompt."""
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("adding_deal", None)
    await q.edit_message_text("Ok ạ! Khi nào muốn nhập thì vào 💰 Hoa hồng nhé.",
                              reply_markup=MENU_KB)


# ---------------------------------------------------------------- router

