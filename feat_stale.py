"""7-day stale listing refresh — per-listing availability check.

Nudge (pending_nudges.py section 6e) sends one batched message per broker:

    📋 Anh có 47 tin cũ cần cập nhật (đang hiện 1-10):
    1. 🏠 2PN An Thượng, 12tr — 12 ngày chưa update
    ...

    Mỗi tin chọn 1 nhé 👇
    [1 ✅] [1 ❌] [1 ❓]
    ...
    [Xem thêm 10 tin]

Callbacks (all stateless — re-query on each tap):
  stale:ok:<id>       -> still available, bump updated_at
  stale:rented:<id>   -> mark rented
  stale:unsure:<id>   -> mark uncertain (still in matches, with ⚠️ warning)
  stale:more:<page>   -> next page of 10
  stale:rewrite:<id>  -> Pro: regenerate fresh FB post for reposting
"""

import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import feat_premium
import feat_write
from utils import MENU_KB, get_pronoun, natural_delay, fmt_price, listing_line

STALE_DAYS = 7
STALE_STATUSES = ("submitted", "uncertain")
PAGE_SIZE = 10


def _stale_for_broker(uid, path=None):
    """Stale listings for one broker, most-active first.

    Wholesalers may have hundreds — order by recent activity
    (inquiries + views) so the important ones surface first.
    """
    all_stale = db.stale_listings(older_than_days=STALE_DAYS,
                                  statuses=STALE_STATUSES, path=path)
    mine = [l for l in all_stale if l["broker_id"] == uid]
    mine.sort(key=lambda l: (l.get("inquiry_count", 0) * 10 +
                             l.get("view_count", 0)),
              reverse=True)
    return mine


def _listing_brief(l):
    """One-line summary: 🏠 2PN An Thượng, 12tr — 12 ngày chưa update."""
    p = l.get("parsed") or {}
    br = p.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = p.get("building_name") or p.get("district") or "?"
    price = p.get("price_vnd")
    price_s = f"{price / 1_000_000:g}tr" if price else "?/tháng"
    days = int((time.time() - l["updated_at"]) / 86400)
    return f"🏠 {br_s} {loc}, {price_s} — {days} ngày chưa update"


def build_stale_batch(uid, page=0, path=None):
    """Build (text, keyboard) for the stale-refresh batch message.

    Returns (text, InlineKeyboardMarkup, total_count).
    """
    stale = _stale_for_broker(uid, path=path)
    total = len(stale)
    start = page * PAGE_SIZE
    items = stale[start:start + PAGE_SIZE]
    pn = get_pronoun(uid)

    if not items:
        return None, None, total

    end = min(start + PAGE_SIZE, total)
    lines = [f"📋 {pn.capitalize()} có <b>{total}</b> tin cũ cần cập nhật "
             f"(đang hiện {start + 1}-{end}):",
             ""]
    kb = []
    for i, l in enumerate(items, start=start + 1):
        lines.append(f"{i}. {_listing_brief(l)}")
        kb.append([
            InlineKeyboardButton(f"{i} ✅",
                                 callback_data=f"stale:ok:{l['id']}"),
            InlineKeyboardButton(f"{i} ❌",
                                 callback_data=f"stale:rented:{l['id']}"),
            InlineKeyboardButton(f"{i} ❓",
                                 callback_data=f"stale:unsure:{l['id']}"),
        ])
    lines += ["", "Mỗi tin chọn 1 nhé 👇",
              "✅ Còn trống · ❌ Đã cho thuê · ❓ Ko chắc"]
    if end < total:
        kb.append([InlineKeyboardButton(
            f"Xem thêm 10 tin ({end + 1}-{min(end + PAGE_SIZE, total)}/{total})",
            callback_data=f"stale:more:{page + 1}")])
    kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")])
    return "\n".join(lines), InlineKeyboardMarkup(kb), total


async def stale_action_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle stale:* callbacks — all stateless."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    data = q.data[len("stale:"):]
    act, _, rest = data.partition(":")

    if act == "more":
        try:
            page = int(rest)
        except ValueError:
            page = 0
        text, kb, total = build_stale_batch(uid, page=page)
        if text is None:
            await q.edit_message_text("Hết tin cũ rồi ạ, tất cả đã cập nhật ✓",
                                      reply_markup=MENU_KB)
        else:
            await q.edit_message_text(text, parse_mode="HTML",
                                      reply_markup=kb)
        return

    if act == "rewrite":
        # Pro: regenerate fresh FB post for reposting
        if not feat_premium.requires_tier(uid, "refresh"):
            await feat_premium.send_gate(q, "refresh", uid, edit=True)
            return
        listing_id = rest
        l = db.get_listing(listing_id)
        if not l or l["broker_id"] != uid:
            await q.answer("Tin này không còn nữa.", show_alert=True)
            return
        # rewriting for repost confirms availability
        db.touch_listing(listing_id)
        post = feat_write.generate_post(l, lang="vi")
        await q.message.reply_text(
            f"✍️ Bài đăng mới cho tin này:\n\n{post}\n\n"
            f"{pn.capitalize()} copy đăng lại nhé!",
            reply_markup=MENU_KB)
        return

    # ok / rented / unsure — listing_id follows (ids contain ':', split once)
    listing_id = rest
    l = db.get_listing(listing_id)
    if not l or l["broker_id"] != uid:
        await q.answer("Tin này không còn nữa.", show_alert=True)
        return

    brief = _listing_brief(l)
    if act == "ok":
        db.touch_listing(listing_id)  # bumps updated_at, stays submitted
        toast = "Đã cập nhật: vẫn còn trống ✓"
    elif act == "rented":
        db.set_listing_status(listing_id, "rented", changed_by="broker")
        toast = f"Đã đánh dấu đã cho thuê ✓ Chúc mừng {pn}!"
    elif act == "unsure":
        db.set_listing_status(listing_id, "uncertain", changed_by="broker")
        toast = "Đã đánh dấu ko chắc — tin vẫn hiện nhưng có cảnh báo ⚠️"
    else:
        return

    await q.answer(toast)

    # rebuild the batch (decided listing drops out automatically)
    text, kb, total = build_stale_batch(uid, page=0)
    rewrite_row = None
    if act == "ok" and feat_premium.requires_tier(uid, "refresh"):
        # Pro: offer to rewrite the just-confirmed listing for reposting
        rewrite_row = [InlineKeyboardButton(
            "✍️ Viết lại tin vừa rồi để đăng",
            callback_data=f"stale:rewrite:{listing_id}")]
    if text is None:
        await q.edit_message_text(
            "Xong! Tất cả tin cũ đã được cập nhật ✓", reply_markup=MENU_KB)
    else:
        if rewrite_row:
            # insert before the Menu row
            rows = kb.inline_keyboard
            kb = InlineKeyboardMarkup(rows[:-1] + [rewrite_row] + rows[-1:])
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
