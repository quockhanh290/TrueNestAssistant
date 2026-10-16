"""Evening interactive checklist (eve:* callbacks).

The 21h summary offers [Lam luon] / [De mai]. "Lam luon" lists each
pending item as a button; tapping one marks it done and jumps straight
into the relevant flow (feedback / price edit / client detail).
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import feat_clients
import feat_listings
import feat_viewings
from utils import MENU_KB, get_pronoun

log = logging.getLogger("linh")

EVE_KIND_LABEL = {
    "feedback": "💬 Feedback",
    "refresh": "💰 Cập nhật giá",
    "call": "📞 Gọi lại",
}


def _parse_eve_cb(data):
    """'eve:go:feedback:vw:<hex>' -> ('go', 'feedback', 'vw:<hex>')."""
    parts = data.split(":", 3)
    act = parts[1] if len(parts) > 1 else ""
    kind = parts[2] if len(parts) > 2 else ""
    ref = parts[3] if len(parts) > 3 else ""
    return act, kind, ref


async def eve_now(update, ctx):
    """Broker chose [Lam luon] — show each pending item as an action."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    items = db.list_checklist(uid)
    if not items:
        await q.edit_message_text(
            "Hết việc rồi, đi ngủ thôi 😴", reply_markup=MENU_KB)
        return
    lines = ["Việc nào trước ạ? (bấm theo thứ tự)"]
    kb = []
    for i, it in enumerate(items, 1):
        kind_l = EVE_KIND_LABEL.get(it["kind"], it["kind"])
        label = it.get("label") or it["ref_id"]
        lines.append(f"{i}. {kind_l}: {label}")
        kb.append([InlineKeyboardButton(
            f"{i}. {kind_l}: {label[:30]}",
            callback_data=f"eve:go:{it['kind']}:{it['ref_id']}")])
    kb.append([InlineKeyboardButton("✅ Xong, đi ngủ",
                                    callback_data="eve:done")])
    await q.edit_message_text("\n".join(lines),
                              reply_markup=InlineKeyboardMarkup(kb))


async def eve_later(update, ctx):
    """Broker chose [De mai] — items stay for the morning brief."""
    q = update.callback_query
    await q.answer()
    n = len(db.list_checklist(q.from_user.id))
    await q.edit_message_text(
        f"Ok, {n} việc này mai 8h em nhắc lại nhé 😴",
        reply_markup=MENU_KB)


async def eve_done(update, ctx):
    """[Xong, di ngu] — clear remaining items, goodnight."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    db.clear_checklist(uid)
    await q.edit_message_text(
        f"Ngủ ngon {pn}! Mai 8h em nhắc tiếp 😴",
        reply_markup=MENU_KB)


async def eve_go(update, ctx):
    """Tap one item -> mark done, jump into the flow. eve:go:{kind}:{ref}."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act, kind, ref = _parse_eve_cb(q.data)
    if not kind or not ref:
        return
    db.clear_checklist_item(uid, kind, ref)
    if kind == "feedback":
        await feat_viewings._begin_feedback(q, ctx, uid, ref)
    elif kind == "refresh":
        l = db.get_listing(ref)
        if not l or l.get("broker_id") != uid:
            await q.edit_message_text("Tin này không còn nữa.",
                                      reply_markup=MENU_KB)
            return
        await feat_listings._prompt_edit_field(q, ref, "price_vnd",
                                               "0", "s:a", ctx)
    elif kind == "call":
        c = db.get_client(ref)
        if not c or c.get("broker_id") != uid:
            await q.edit_message_text("Khách này không còn nữa.",
                                      reply_markup=MENU_KB)
            return
        await feat_clients.show_client_detail(update, ctx,
                                              client_id=ref)
    else:
        await eve_now(update, ctx)
