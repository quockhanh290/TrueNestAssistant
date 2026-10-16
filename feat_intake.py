"""Listing intake: collection buffer, parsing, confirmation, missing fields."""
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

async def on_new_listing_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped 📝 Gửi tin mới — arm the collection buffer."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    # rate limit
    if db.count_recent_listings(uid, hours=1) >= config.RATE_LIMIT_PER_HOUR:
        await q.edit_message_text(
            f"Anh gửi nhiều quá rồi 😅 Em chỉ nhận tối đa "
            f"{config.RATE_LIMIT_PER_HOUR} tin/giờ thôi, anh nghỉ chút rồi gửi tiếp nhé.",
            reply_markup=MENU_KB,
        )
        return
    _buffers[uid] = {"texts": [], "photos": [], "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": q.message.chat_id}
    await natural_delay(update)
    await q.edit_message_text(
        "Ok anh, anh gửi tin đi ạ — text + ảnh, gửi nhiều tin nhắn cũng được, "
        "em chờ 30 giây rồi tổng hợp một thể 📥"
    )
    # schedule flush
    asyncio.create_task(_flush_after(uid, ctx))


async def _flush_after(uid, ctx):
    # Wait until the buffer deadline passes (extended by each new photo/text).
    # Fixes: broker sending photos one-by-one slowly would get split listings.
    while True:
        buf = _buffers.get(uid)
        if not buf:
            return
        now = time.time()
        wait = buf["deadline"] - now
        if wait <= 0:
            break
        await asyncio.sleep(min(wait + 0.5, 5))
    buf = _buffers.pop(uid, None)
    if not buf or (not buf["texts"] and not buf["photos"]):
        return
    await _process_buffer(uid, buf, ctx)


# ---------------------------------------------------------------- full pre-save confirmation

async def _process_buffer(uid, buf, ctx):
    chat_id = buf["chat_id"]
    raw = "\n".join(buf["texts"])
    photos = buf["photos"]
    result = listing_parser.parse_listing(raw, photo_count=len(photos))

    # auto-fill broker's saved phone when the text has none (per-listing
    # override: if the text itself contains a phone, it wins for this listing)
    broker_phone = db.get_broker_phone(uid)
    phone_autofilled = False
    if broker_phone and not result["fields"].get("primary_phone"):
        result["fields"]["primary_phone"] = broker_phone
        result["missing"] = [m for m in result["missing"]
                             if m != "primary_phone"]
        phone_autofilled = True

    await maybe_send_hint_to_chat(ctx, chat_id)
    await ctx.bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(random.uniform(1.0, 1.5))

    # create as DRAFT — the broker must confirm the full summary first
    listing_id = db.create_listing(
        uid, raw_text=raw, photo_file_ids=photos,
        parsed=result["fields"], missing_fields=result["missing"],
        status="draft",
    )
    pn = get_pronoun(uid)
    phone_note = f" (SĐT của {pn})" if phone_autofilled else ""
    ctx.user_data["confirming"] = {"listing_id": listing_id,
                                   "phone_note": phone_note}
    l = db.get_listing(listing_id)
    text, kb = _confirm_summary(l, pn, phone_note)
    await ctx.bot.send_message(chat_id, text, reply_markup=kb)


async def _finalize_after_confirm(update_or_q, ctx, uid, listing_id, chat_id,
                                via_callback):
    """Broker confirmed the summary ([Đúng rồi] button or typed 'đúng rồi'):
    ask missing critical fields (max 2) or finish the save."""
    ctx.user_data.pop("confirming", None)
    l = db.get_listing(listing_id)
    pn = get_pronoun(uid)

    async def _say(text, kb=None):
        if via_callback:
            await update_or_q.edit_message_text(text, reply_markup=kb)
        else:
            await update_or_q.message.reply_text(text, reply_markup=kb)

    if not l:
        await _say("Tin này không còn nữa.", MENU_KB)
        return
    p = l["parsed"]
    missing = []
    if not p.get("price_vnd"):
        missing.append("price_vnd")
    if not p.get("primary_phone"):
        missing.append("primary_phone")
    if len(l["photo_file_ids"]) < 1:
        missing.append("photos")
    missing = [m for m in missing
               if m in config.CRITICAL_FIELDS][:config.MAX_MISSING_QUESTIONS]
    if missing:
        db.set_listing_status(listing_id, "pending_info", changed_by="bot")
        db.update_listing(listing_id, missing_fields=missing)
        await _say(f"Ok {pn}, em lưu nháp rồi nhé. Còn thiếu chút thông tin:")
        await _ask_missing(chat_id, uid, listing_id, missing[0], ctx,
                           remaining=missing[1:])
    else:
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        from feat_write import _maybe_write_post_finish  # lazy: avoid cycle
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await _say("Xong! Em đã lưu tin rồi nhé ✓", MENU_KB)


async def confirm_save_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lid = q.data.split(":", 2)[2]  # "cfm:save:<listing_id>" (ids contain ':')
    await _finalize_after_confirm(q, ctx, q.from_user.id, lid,
                                  q.message.chat_id, via_callback=True)


_CONFIRM_WORDS = {"đúng rồi", "dung roi", "đúng", "dung", "ok", "oke",
                  "okê", "chuẩn", "chuan", "ừ", "u", "ừm", "um"}


async def _handle_confirm_correction(update, ctx, confirming, text):
    """Text typed while a draft summary is pending confirmation.

    'đúng rồi'-style replies confirm; anything else is re-parsed and
    merged into the draft, then the summary is re-shown.
    """
    uid = update.effective_user.id
    listing_id = confirming["listing_id"]
    l = db.get_listing(listing_id)
    if not l:
        ctx.user_data.pop("confirming", None)
        return
    pn = get_pronoun(uid)

    if text.strip().lower() in _CONFIRM_WORDS:
        # treat as tapping [Đúng rồi, lưu tin]
        await _finalize_after_confirm(
            update, ctx, uid, listing_id, update.effective_chat.id,
            via_callback=False)
        return

    result = listing_parser.parse_listing(text)
    fields = {k: v for k, v in result["fields"].items()
              if k not in ("photo_count", "description") and v is not None}
    if not fields:
        await update.message.reply_text(
            f"Em chưa hiểu chỗ này lắm, {pn} ghi rõ hơn giúp em nhé? "
            "(VD: giá 13tr, 2PN)")
        return
    for k, v in fields.items():
        db.update_listing_field(listing_id, k, v, changed_by="broker")
    old_raw = l.get("raw_text") or ""
    db.update_listing(listing_id, raw_text=(old_raw + "\n" + text).strip())
    l = db.get_listing(listing_id)
    t, kb = _confirm_summary(l, pn, confirming.get("phone_note", ""))
    await natural_delay(update)
    await update.message.reply_text("Em cập nhật rồi nhé ✓\n\n" + t,
                                    reply_markup=kb)


async def _handle_confirm_photo(update, ctx, confirming, file_id, caption):
    """Photo sent while a draft summary is pending: attach to the draft
    and re-show the summary."""
    uid = update.effective_user.id
    listing_id = confirming["listing_id"]
    l = db.get_listing(listing_id)
    if not l:
        ctx.user_data.pop("confirming", None)
        return
    photos = l["photo_file_ids"] + [file_id]
    raw = l["raw_text"] or ""
    if caption:
        raw = (raw + "\n" + caption).strip()
        res = listing_parser.parse_listing(caption)
        for k, v in res["fields"].items():
            if k not in ("photo_count", "description") and v is not None:
                db.update_listing_field(listing_id, k, v, changed_by="broker")
    db.update_listing(listing_id, photo_file_ids=photos, raw_text=raw)
    l = db.get_listing(listing_id)
    pn = get_pronoun(uid)
    t, kb = _confirm_summary(l, pn, confirming.get("phone_note", ""))
    await natural_delay(update)
    await update.message.reply_text(
        f"Đã thêm ảnh ✓ (tổng {len(photos)} ảnh)\n\n" + t,
        reply_markup=kb)


QUESTION_TEXT = {
    "price_vnd": "Giá thuê bao nhiêu một tháng ạ?",
    "primary_phone": "Còn thiếu SĐT để khách liên hệ, anh cho em nhé?",
    "photos": "Anh gửi thêm ảnh của căn này giúp em nhé? (càng nhiều càng tốt)",
}


async def _ask_missing(chat_id, uid, listing_id, field, ctx, remaining):
    ctx.user_data["awaiting"] = {"listing_id": listing_id, "field": field,
                                 "remaining": remaining}
    await asyncio.sleep(1)
    await ctx.bot.send_message(chat_id, QUESTION_TEXT[field])


async def _flush_media_group(key, ctx):
    """Debounced flush of one album: merge its photos + caption into the
    user's collection buffer (creating one if needed)."""
    try:
        await asyncio.sleep(MEDIA_GROUP_WINDOW)
    except asyncio.CancelledError:
        return  # superseded by a newer message in the same album
    entry = _media_groups.pop(key, None)
    if not entry or not entry["photos"]:
        return
    uid = entry["uid"]
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].extend(entry["photos"])
        if entry["caption"]:
            buf["texts"].append(entry["caption"])
        buf["deadline"] = time.time() + COLLECT_WINDOW
    else:
        _buffers[uid] = {
            "texts": [entry["caption"]] if entry["caption"] else [],
            "photos": list(entry["photos"]),
            "deadline": time.time() + COLLECT_WINDOW,
            "chat_id": entry["chat_id"],
        }
        try:
            await ctx.bot.send_message(
                entry["chat_id"],
                "Nhận ảnh! Anh gửi thêm text mô tả giúp em nhé 📥")
        except Exception:
            pass
        asyncio.create_task(_flush_after(uid, ctx))


async def _handle_photo_answer(update, ctx, awaiting, file_id, caption):
    """User sent a photo while the bot was asking for missing photos:
    attach it to the pending listing instead of starting a new one."""
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    listing_id = awaiting["listing_id"]
    listing = db.get_listing(listing_id)
    if not listing:
        ctx.user_data.pop("awaiting", None)
        return
    photos = listing["photo_file_ids"] + [file_id]
    raw = listing["raw_text"]
    if caption:
        raw = (raw + "\n" + caption).strip()
    db.update_listing(listing_id, photo_file_ids=photos, raw_text=raw)

    remaining = [m for m in awaiting.get("remaining", [])]
    parsed = listing["parsed"]
    still = []
    if "price_vnd" not in parsed:
        still.append("price_vnd")
    if "primary_phone" not in parsed:
        still.append("primary_phone")
    if len(photos) < 1:
        still.append("photos")
    still = [s for s in still if s in remaining][:config.MAX_MISSING_QUESTIONS]

    db.update_listing(listing_id, missing_fields=still)
    await natural_delay(update)
    if still:
        await _ask_missing(chat_id, uid, listing_id, still[0], ctx,
                           remaining=still[1:])
    else:
        ctx.user_data.pop("awaiting", None)
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        await update.message.reply_text(
            f"Đã nhận ảnh ✓ (tổng {len(photos)} ảnh)")
        from feat_write import _maybe_write_post_finish  # lazy: avoid cycle
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(0.5)
        await update.message.reply_text(
            "Xong! Em đã lưu tin rồi nhé ✓",
            reply_markup=MENU_KB,
        )


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await react_heart(update.message)
    if ctx.user_data.get("onboarding") or ctx.user_data.get("editing_contact"):
        await update.message.reply_text(
            "Anh trả lời tin nhắn trên giúp em trước nhé? 😊")
        return
    uid = update.effective_user.id
    msg = update.message
    file_id = msg.photo[-1].file_id  # largest size
    caption = (msg.caption or "").strip()

    # 0. adding photos to an existing listing? (explicit mode)
    addp = ctx.user_data.get("adding_photos")
    if addp:
        from feat_listings import _handle_add_photo  # lazy: avoid cycle
        await _handle_add_photo(update, ctx, addp, file_id, caption)
        return

    # 0b. confirming a draft summary? attach the photo to the draft
    confirming = ctx.user_data.get("confirming")
    if confirming:
        await _handle_confirm_photo(update, ctx, confirming, file_id, caption)
        return

    # 1. answering a missing-field question that wants photos?
    awaiting = ctx.user_data.get("awaiting")
    if awaiting and awaiting.get("field") == "photos":
        await _handle_photo_answer(update, ctx, awaiting, file_id, caption)
        return

    # 2. part of an album? buffer by media_group_id, debounce, then merge
    mg_id = msg.media_group_id
    if mg_id:
        key = f"{uid}:{mg_id}"
        entry = _media_groups.get(key)
        if entry and entry.get("task"):
            entry["task"].cancel()
        if entry is None:
            entry = {"photos": [], "caption": "", "uid": uid,
                     "chat_id": msg.chat.id, "task": None}
            _media_groups[key] = entry
        entry["photos"].append(file_id)
        if caption and not entry["caption"]:
            entry["caption"] = caption
        entry["task"] = asyncio.create_task(_flush_media_group(key, ctx))
        return

    # 3. single photo — caption goes through the same pipeline as text
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].append(file_id)
        if caption:
            buf["texts"].append(caption)
        buf["deadline"] = time.time() + COLLECT_WINDOW
    else:
        _buffers[uid] = {"texts": [caption] if caption else [],
                         "photos": [file_id],
                         "deadline": time.time() + COLLECT_WINDOW,
                         "chat_id": msg.chat.id}
        await update.message.reply_text(
            "Nhận ảnh! Anh gửi thêm text mô tả giúp em nhé 📥")
        asyncio.create_task(_flush_after(uid, ctx))


async def _handle_answer(update, ctx, awaiting, text):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    listing_id = awaiting["listing_id"]
    field = awaiting["field"]
    listing = db.get_listing(listing_id)
    if not listing:
        ctx.user_data.pop("awaiting", None)
        return

    parsed = listing["parsed"]
    if field == "price_vnd":
        price, _ = listing_parser.parse_price(text)
        if price:
            parsed["price_vnd"] = price
            await natural_delay(update)
            await update.message.reply_text(f"Ok, đã nhận giá {fmt_price(price)}/tháng ✓")
        else:
            await update.message.reply_text(
                "Em chưa hiểu giá này lắm, anh ghi lại giúp em VD: 12tr ạ?")
            return  # stay on same question
    elif field == "primary_phone":
        phone, _ = listing_parser.parse_phone(text)
        if phone:
            parsed["primary_phone"] = phone
            # save to broker profile too (for future auto-fill)
            db.update_broker(uid, phone=phone)
            if not (db.get_broker(uid) or {}).get("zalo"):
                db.update_broker(uid, zalo=phone)
            await natural_delay(update)
            await update.message.reply_text("Đã lưu SĐT ✓")
        else:
            await update.message.reply_text(
                "Số này em chưa nhận ra, anh ghi lại 10 số giúp em nhé?")
            return

    remaining = [m for m in awaiting["remaining"]]
    # recompute what's still missing
    still = []
    if "price_vnd" not in parsed:
        still.append("price_vnd")
    if "primary_phone" not in parsed:
        still.append("primary_phone")
    if len(listing["photo_file_ids"]) < 1:
        still.append("photos")
    still = [s for s in still if s in remaining][:config.MAX_MISSING_QUESTIONS]

    db.update_listing(listing_id, parsed=parsed, missing_fields=still)
    if still:
        await _ask_missing(chat_id, uid, listing_id, still[0], ctx,
                           remaining=still[1:])
    else:
        ctx.user_data.pop("awaiting", None)
        db.set_listing_status(listing_id, "submitted", changed_by="bot")
        from feat_write import _maybe_write_post_finish  # lazy: avoid cycle
        if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
            return
        await asyncio.sleep(1)
        await update.message.reply_text(
            "Xong! Em đã lưu tin rồi nhé ✓",
            reply_markup=MENU_KB,
        )


# ---------------------------------------------------------------- advanced query

