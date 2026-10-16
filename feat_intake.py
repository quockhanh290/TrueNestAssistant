"""Listing intake: collection buffer, parsing, confirmation, missing fields."""
import asyncio
import json
import logging
import os
import random
import re
import time
import unicodedata

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
    get_forward_source, strip_forward_noise,
)

log = logging.getLogger("linh")

async def on_new_listing_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped 📝 Gửi tin mới — ask whether they have a listing ready
    or want guided step-by-step help."""
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
    # clear any stale guided state
    ctx.user_data.pop("guided", None)
    await natural_delay(update)
    await q.edit_message_text(
        "Anh đã có tin viết sẵn chưa ạ?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Rồi, em gửi luôn",
                                  callback_data="guided:mode:free")],
            [InlineKeyboardButton("❌ Chưa, em giúp em viết",
                                  callback_data="guided:mode:guided")],
        ]),
    )


async def _flush_after(uid, ctx):    # Wait until the buffer deadline passes (extended by each new photo/text).
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
    buf = _buffers.get(uid)
    if not buf or (not buf["texts"] and not buf["photos"]):
        _buffers.pop(uid, None)
        return
    # Ask: đủ chưa? (instead of auto-processing)
    n_photos = len(buf["photos"])
    n_texts = len([t for t in buf["texts"] if t.strip()])
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    parts = []
    if n_texts:
        parts.append(f"{n_texts} đoạn text")
    if n_photos:
        parts.append(f"{n_photos} ảnh")
    desc = " + ".join(parts) or "trống"
    try:
        await ctx.bot.send_message(
            buf["chat_id"],
            f"Em nhận được {desc} rồi. Anh gửi đủ chưa ạ? 🤔",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Đủ rồi, xử lý đi",
                                      callback_data="buf:done")],
                [InlineKeyboardButton("📸 Đợi em gửi thêm",
                                      callback_data="buf:more")],
            ]))
    except Exception:
        buf = _buffers.pop(uid, None)
        if buf:
            await _process_buffer(uid, buf, ctx)


async def buf_confirm_done(update, ctx):
    """Broker confirmed buffer is complete — process it."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    buf = _buffers.pop(uid, None)
    if not buf:
        await q.edit_message_text("Hết hạn rồi, anh gửi lại giúp em nhé 😅")
        return
    gd = ctx.user_data.get("guided")
    if gd and buf.get("guided") and GUIDED_STEPS[gd["step"]] == "photos":
        # guided photo step done — keep photos, move to description step
        gd["answers"]["photos"] = buf["photos"]
        gd["step"] = GUIDED_STEPS.index("description")
        await q.edit_message_text("Nhận đủ ảnh rồi ✓")
        await _guided_show(update, ctx, edit=False)
        return
    await q.edit_message_text("Ok, em đang xử lý... ⏳")
    await _process_buffer(uid, buf, ctx)


async def buf_confirm_more(update, ctx):
    """Broker wants to send more — extend deadline by 30s."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    buf = _buffers.get(uid)
    if not buf:
        await q.edit_message_text("Hết hạn rồi, anh gửi lại giúp em nhé 😅")
        return
    buf["deadline"] = time.time() + 30
    await q.edit_message_text(
        "Ok anh cứ gửi tiếp nhé, em chờ thêm 30s 📥")
    asyncio.create_task(_flush_after(uid, ctx))


async def stray_confirm_yes(update, ctx):
    """Stray photo belongs to the suggested recent listing — attach it."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sp = ctx.user_data.pop("stray_photo", None)
    if not sp:
        await q.edit_message_text("Hết hạn rồi, anh gửi lại giúp em nhé 😅")
        return
    listing_id = sp["listing_id"]
    file_id = sp["file_id"]
    db.add_listing_photo(listing_id, file_id)
    await q.edit_message_text("Đã thêm ảnh vào tin rồi anh ✓ 📸")


async def stray_confirm_new(update, ctx):
    """Stray photo is for a new listing — start a fresh buffer."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sp = ctx.user_data.pop("stray_photo", None)
    if not sp:
        await q.edit_message_text("Hết hạn rồi, anh gửi lại giúp em nhé 😅")
        return
    from utils import _buffers, COLLECT_WINDOW
    _buffers[uid] = {"texts": [sp["caption"]] if sp.get("caption") else [],
                     "photos": [sp["file_id"]],
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": sp["chat_id"]}
    await q.edit_message_text(
        "Ok, tin mới nhé! Anh gửi thêm text/ảnh giúp em 📥 (em chờ 5s)")
    asyncio.create_task(_flush_after(uid, ctx))


# ---------------------------------------------------------------- full pre-save confirmation

async def _process_buffer(uid, buf, ctx, field_overrides=None):
    chat_id = buf["chat_id"]
    raw = "\n".join(buf["texts"])
    photos = buf["photos"]
    result = listing_parser.parse_listing(raw, photo_count=len(photos))
    if field_overrides:
        # guided answers the parser can't derive (e.g. availability date)
        result["fields"].update({k: v for k, v in field_overrides.items()
                                 if v is not None})

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
    fwd_source = buf.get("forward_source") or ""
    ctx.user_data["confirming"] = {"listing_id": listing_id,
                                   "phone_note": phone_note,
                                   "forward_source": fwd_source}
    l = db.get_listing(listing_id)
    text, kb = _confirm_summary(l, pn, phone_note, fwd_source)
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
    t, kb = _confirm_summary(l, pn, confirming.get("phone_note", ""), confirming.get("forward_source", ""))
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
    t, kb = _confirm_summary(l, pn, confirming.get("phone_note", ""), confirming.get("forward_source", ""))
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
        if not buf.get("forward_source") and entry.get("forward_source"):
            buf["forward_source"] = entry["forward_source"]
    else:
        _buffers[uid] = {
            "texts": [entry["caption"]] if entry["caption"] else [],
            "photos": list(entry["photos"]),
            "deadline": time.time() + COLLECT_WINDOW,
            "chat_id": entry["chat_id"],
            "forward_source": entry.get("forward_source"),
        }
        fwd = entry.get("forward_source")
        fwd_note = f" (forward từ {fwd})" if fwd else ""
        has_caption = entry.get("caption") and entry["caption"].strip()
        try:
            await ctx.bot.send_message(
                entry["chat_id"],
                f"Nhận {len(entry['photos'])} ảnh{fwd_note}! " +
                ("Anh gửi thêm ảnh nếu có nhé 📥"
                 if has_caption else
                 "Anh gửi thêm text mô tả giúp em nhé 📝"))
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

    # 1b. guided intake but not on the photo step yet — hold the photo
    gd = ctx.user_data.get("guided")
    if gd and GUIDED_STEPS[gd["step"]] != "photos":
        await update.message.reply_text(
            "Mình đang trả lời câu hỏi của em, ảnh để gửi ở bước sau nhé 📸\n"
            "(gõ /huy để hủy)")
        return

    # 2. part of an album? buffer by media_group_id, debounce, then merge
    # Note: forwarded albums keep a (fresh) media_group_id, so this path
    # works for forwards too. If media_group_id is ever missing on a
    # forward, the photo falls through to step 3 and the 5s buffer groups it.
    mg_id = msg.media_group_id
    if mg_id:
        key = f"{uid}:{mg_id}"
        entry = _media_groups.get(key)
        if entry and entry.get("task"):
            entry["task"].cancel()
        if entry is None:
            entry = {"photos": [], "caption": "", "uid": uid,
                     "chat_id": msg.chat.id, "task": None,
                     "forward_source": get_forward_source(msg)}
            _media_groups[key] = entry
        entry["photos"].append(file_id)
        if caption and not entry["caption"]:
            fwd_cap = get_forward_source(msg)
            entry["caption"] = strip_forward_noise(caption) if fwd_cap else caption
        if not entry.get("forward_source"):
            fwd = get_forward_source(msg)
            if fwd:
                entry["forward_source"] = fwd
        entry["task"] = asyncio.create_task(_flush_media_group(key, ctx))
        return

    # 3. single photo — caption goes through the same pipeline as text
    fwd_source = get_forward_source(msg)
    if fwd_source and caption:
        caption = strip_forward_noise(caption)
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].append(file_id)
        if caption:
            buf["texts"].append(caption)
        buf["deadline"] = time.time() + COLLECT_WINDOW
        if not buf.get("forward_source") and fwd_source:
            buf["forward_source"] = fwd_source
    elif fwd_source:
        # Forwarded photo with no active buffer: this is new shared content,
        # not a forgotten attachment — skip the "stray photo?" question and
        # start a fresh listing buffer directly. (Without this, each photo
        # of a forwarded album lacking media_group_id would trigger its own
        # stray-photo prompt.)
        _buffers[uid] = {"texts": [caption] if caption else [],
                         "photos": [file_id],
                         "deadline": time.time() + COLLECT_WINDOW,
                         "chat_id": msg.chat.id,
                         "forward_source": fwd_source}
        await update.message.reply_text(
            f"Em nhận 1 ảnh (forward từ {fwd_source}) rồi! "
            "Đang đợi thêm... 📥\n"
            "(anh gửi text/ảnh tiếp trong 5s nhé)")
        asyncio.create_task(_flush_after(uid, ctx))
    else:
        # No active buffer — stray photo. Usually it's for the most recent
        # listing, so ask to confirm instead of starting a new one blindly.
        recent = db.list_broker_listings(
            uid, limit=1, statuses=["submitted", "draft", "pending_info",
                                    "rented", "expired"])
        if recent:
            lst = recent[0]
            created_ago = time.time() - (lst.get("created_at") or 0)
            if created_ago < 7200:  # within 2 hours
                p = lst.get("parsed") or {}
                br = p.get("bedrooms")
                br_s = "Studio" if br == 0 else (f"{int(br)}PN" if br else "")
                loc = p.get("building_name") or p.get("district") or ""
                label = f"{br_s} {loc}".strip() or "tin gần nhất"
                ctx.user_data["stray_photo"] = {
                    "file_id": file_id,
                    "caption": caption,
                    "listing_id": lst["id"],
                    "chat_id": msg.chat.id,
                }
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                await update.message.reply_text(
                    f"Ảnh này cho tin <b>{label}</b> phải không anh? 🤔",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Đúng rồi",
                                              callback_data="stray:yes")],
                        [InlineKeyboardButton("📝 Tin mới",
                                              callback_data="stray:new")],
                    ]))
                return
        _buffers[uid] = {"texts": [caption] if caption else [],
                         "photos": [file_id],
                         "deadline": time.time() + COLLECT_WINDOW,
                         "chat_id": msg.chat.id}
        if caption and caption.strip():
            await update.message.reply_text(
                "Em nhận ảnh + text rồi! Anh gửi thêm ảnh nếu có nhé 📥\n"
                "(em chờ 5s)")
        else:
            await update.message.reply_text(
                "Em nhận 1 ảnh rồi! Đang đợi text mô tả... 📝\n"
                "(anh gửi trong 5s nhé, em chờ)")
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



# ---------------------------------------------------------------- guided intake
# Step-by-step listing creation for brokers who don't have a listing written.

GUIDED_STEPS = ["bedrooms", "bathrooms", "ptype", "price", "area",
                "district", "area_loc", "street", "landmark", "building_detail",
                "floor", "furnishing", "pet",
                "availability", "lease_min", "deposit", "pay_schedule",
                "amenities", "photos", "description"]

GUIDED_DISTRICTS = [("st", "Sơn Trà"), ("hc", "Hải Châu"),
                    ("nhs", "Ngũ Hành Sơn"), ("lc", "Liên Chiểu"),
                    ("cl", "Cẩm Lệ"), ("tk", "Thanh Khê"),
                    ("hv", "Hòa Vang")]

GUIDED_PTYPES = [("lux_apt", "🏢 Chung cư cao cấp"),
                 ("house", "🏠 Nhà riêng nguyên căn"),
                 ("mini_apt", "🏘️ Căn hộ mini"),
                 ("serviced", "🏨 Căn hộ dịch vụ"),
                 ("villa", "🏰 Villa/Biệt thự"),
                 ("penthouse", "🏙️ Penthouse"),
                 ("shophouse", "🏪 Shophouse"),
                 ("street_house", "🏡 Nhà mặt tiền")]

GUIDED_AMENITIES = [
    ("pool", "🏊 Hồ bơi"), ("gym", "🏋️ Gym"),
    ("parking", "🚗 Chỗ đậu xe"), ("seaview", "🌊 View biển"),
    ("cityview", "🌃 View thành phố"), ("balcony", "🌳 Ban công"),
    ("pet", "🐕 Cho pet"), ("security", "🔒 An ninh 24/7"),
    ("laundry", "🧺 Giặt sấy"), ("wifi", "📶 Wifi mạnh"),
    ("kitchen", "🍳 Bếp đầy đủ"), ("ac", "❄️ Điều hòa"),
    ("cleaning", "🧹 Dọn phòng"),
]

_AMENITY_TEXT = {
    "pool": "hồ bơi", "gym": "gym", "parking": "chỗ đậu xe",
    "seaview": "view biển", "cityview": "view thành phố",
    "balcony": "ban công", "pet": "cho pet",
    "security": "an ninh 24/7", "laundry": "giặt sấy",
    "wifi": "wifi mạnh", "kitchen": "bếp đầy đủ",
    "ac": "điều hòa", "cleaning": "dọn phòng",
}

_PTYPE_TEXT = {"lux_apt": "chung cư cao cấp", "house": "nhà riêng nguyên căn",
               "mini_apt": "căn hộ mini", "serviced": "căn hộ dịch vụ",
               "villa": "villa/biệt thự", "penthouse": "penthouse",
               "shophouse": "shophouse", "street_house": "nhà mặt tiền"}

_GUIDED_CANCEL_WORDS = {"huy", "/huy", "huỷ", "hủy", "cancel"}
_GUIDED_SKIP_WORDS = {"bỏ qua", "bo qua", "skip", "ko", "không", "k"}

# ---------------------------------------------------------------- location data
# data/locations.json: {districts: [{code, name, areas: [{name, note, streets}]}]}

_LOCATIONS = None
_BUILDINGS_CACHE = None


def _load_locations():
    global _LOCATIONS
    if _LOCATIONS is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "locations.json")
        with open(p, encoding="utf-8") as f:
            _LOCATIONS = json.load(f)
    return _LOCATIONS


def _district_by_code(code):
    for d in _load_locations()["districts"]:
        if d["code"] == code:
            return d
    return None


def _load_buildings_cache():
    global _BUILDINGS_CACHE
    if _BUILDINGS_CACHE is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "buildings.json")
        with open(p, encoding="utf-8") as f:
            _BUILDINGS_CACHE = json.load(f)
    return _BUILDINGS_CACHE


_BUILDING_DISTRICT = {"hc": "Hai Chau", "st": "Son Tra",
                      "nhs": "Ngu Hanh Son", "tk": "Thanh Khe",
                      "cl": "Cam Le", "lc": "Lien Chieu", "hv": "Hoa Vang"}


def _unaccent(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "d").lower()


def _landmark_suggestions(district_code, area_name, limit=6):
    """Suggest buildings.json landmarks for a district, ranked by area match."""
    blds = _load_buildings_cache()
    dname = _BUILDING_DISTRICT.get(district_code)
    if not dname:
        return []
    area_words = [w for w in _unaccent(area_name).split() if len(w) > 2]
    scored = []
    for b in blds:
        if b.get("district") != dname:
            continue
        name = b.get("name") or ""
        nlow = _unaccent(name)
        score = sum(1 for w in area_words if w in nlow)
        scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out, seen = [], set()
    for score, name in scored:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _guided_back_kb(extra_rows=None):
    rows = list(extra_rows or [])
    rows.append([InlineKeyboardButton("⬅️ Quay lại",
                                     callback_data="guided:back")])
    return InlineKeyboardMarkup(rows)


def _guided_step_content(gd):
    """(text, keyboard) for the current guided step."""
    step = GUIDED_STEPS[gd["step"]]
    n = gd["step"] + 1
    total = len(GUIDED_STEPS)
    tag = f"({n}/{total})"

    if step == "bedrooms":
        kb = [
            [InlineKeyboardButton("Studio", callback_data="guided:set:bedrooms:0"),
             InlineKeyboardButton("1PN", callback_data="guided:set:bedrooms:1"),
             InlineKeyboardButton("2PN", callback_data="guided:set:bedrooms:2")],
            [InlineKeyboardButton("3PN", callback_data="guided:set:bedrooms:3"),
             InlineKeyboardButton("4PN", callback_data="guided:set:bedrooms:4"),
             InlineKeyboardButton("5PN+", callback_data="guided:set:bedrooms:5plus")],
        ]
        return f"Căn này mấy phòng ngủ ạ? {tag}", _guided_back_kb(kb)

    if step == "bathrooms":
        kb = [
            [InlineKeyboardButton("1", callback_data="guided:set:bathrooms:1"),
             InlineKeyboardButton("2", callback_data="guided:set:bathrooms:2"),
             InlineKeyboardButton("3", callback_data="guided:set:bathrooms:3")],
            [InlineKeyboardButton("4", callback_data="guided:set:bathrooms:4"),
             InlineKeyboardButton("5+", callback_data="guided:set:bathrooms:5plus")],
        ]
        return f"Mấy phòng tắm ạ? {tag}", _guided_back_kb(kb)

    if step == "ptype":
        kb = []
        for i in range(0, len(GUIDED_PTYPES), 2):
            row = [InlineKeyboardButton(label,
                                        callback_data=f"guided:set:ptype:{code}")
                   for code, label in GUIDED_PTYPES[i:i + 2]]
            kb.append(row)
        return f"Loại hình căn này là gì ạ? {tag}", _guided_back_kb(kb)

    if step == "price":
        return (f"Giá thuê bao nhiêu 1 tháng ạ? (vd: 12tr) {tag}",
                _guided_back_kb())

    if step == "area":
        kb = [[InlineKeyboardButton("Bỏ qua", callback_data="guided:skip")]]
        return (f"Diện tích bao nhiêu m² ạ? (vd: 65) {tag}",
                _guided_back_kb(kb))

    if step == "district":
        kb = []
        for i in range(0, len(GUIDED_DISTRICTS), 2):
            row = [InlineKeyboardButton(label,
                                        callback_data=f"guided:set:district:{code}")
                   for code, label in GUIDED_DISTRICTS[i:i + 2]]
            kb.append(row)
        return f"Quận nào ạ? {tag}", _guided_back_kb(kb)

    if step == "area_loc":
        d = _district_by_code(gd["answers"].get("district_code"))
        areas = d["areas"] if d else []
        kb = []
        for i in range(0, len(areas), 2):
            row = []
            for j, a in enumerate(areas[i:i + 2]):
                idx = i + j
                row.append(InlineKeyboardButton(
                    a["name"], callback_data=f"guided:set:area_loc:{idx}"))
            kb.append(row)
        dname = d["name"] if d else ""
        return (f"Khu vực nào trong {dname} ạ? {tag}",
                _guided_back_kb(kb))

    if step == "street":
        d = _district_by_code(gd["answers"].get("district_code"))
        area_name = gd["answers"].get("area_loc")
        streets = []
        if d:
            for a in d["areas"]:
                if a["name"] == area_name:
                    streets = a["streets"]
                    break
        kb = []
        for i in range(0, len(streets), 2):
            row = [InlineKeyboardButton(
                s, callback_data=f"guided:set:street:{i + j}")
                for j, s in enumerate(streets[i:i + 2])]
            kb.append(row)
        kb.append([InlineKeyboardButton("✏️ Gõ tay",
                                        callback_data="guided:set:street:custom")])
        kb.append([InlineKeyboardButton("Bỏ qua",
                                        callback_data="guided:skip")])
        return (f"Đường nào ở {area_name} ạ? {tag}",
                _guided_back_kb(kb))

    if step == "landmark":
        dcode = gd["answers"].get("district_code")
        area_name = gd["answers"].get("area_loc")
        opts = _landmark_suggestions(dcode, area_name or "")
        gd["landmark_options"] = opts
        kb = []
        for i, name in enumerate(opts):
            kb.append([InlineKeyboardButton(
                name[:40], callback_data=f"guided:set:landmark:{i}")])
        kb.append([InlineKeyboardButton("✏️ Gõ tay",
                                        callback_data="guided:set:landmark:custom")])
        kb.append([InlineKeyboardButton("Bỏ qua",
                                        callback_data="guided:skip")])
        if opts:
            q = f"Gần landmark nào? (tòa nhà, chợ, trường...) {tag}"
        else:
            q = f"Gần landmark nào không anh? {tag}"
        return q, _guided_back_kb(kb)

    if step == "building_detail":
        kb = [[InlineKeyboardButton("Bỏ qua", callback_data="guided:skip")]]
        return (f"Số nhà / tên tòa nhà cụ thể? (vd: số 12, tòa Mường Thanh) {tag}",
                _guided_back_kb(kb))

    if step == "floor":
        kb = [[InlineKeyboardButton("Bỏ qua", callback_data="guided:skip")]]
        return (f"Tầng mấy ạ? (vd: 5) {tag}",
                _guided_back_kb(kb))

    if step == "furnishing":
        kb = [[
            InlineKeyboardButton("Full", callback_data="guided:set:furnishing:full"),
            InlineKeyboardButton("Cơ bản", callback_data="guided:set:furnishing:basic"),
            InlineKeyboardButton("Trống", callback_data="guided:set:furnishing:empty"),
        ]]
        return f"Nội thất thế nào ạ? {tag}", _guided_back_kb(kb)

    if step == "pet":
        kb = [[
            InlineKeyboardButton("Có", callback_data="guided:set:pet:yes"),
            InlineKeyboardButton("Không", callback_data="guided:set:pet:no"),
            InlineKeyboardButton("Thương lượng", callback_data="guided:set:pet:neg"),
        ]]
        return f"Cho nuôi pet không ạ? {tag}", _guided_back_kb(kb)

    if step == "availability":
        kb = [
            [InlineKeyboardButton("✅ Trống sẵn",
                                  callback_data="guided:set:availability:now"),
             InlineKeyboardButton("📅 Ngày cụ thể",
                                  callback_data="guided:set:availability:date")],
            [InlineKeyboardButton("Bỏ qua", callback_data="guided:skip")],
        ]
        return (f"Tình trạng trống ạ? {tag}",
                _guided_back_kb(kb))

    if step == "lease_min":
        kb = [[
            InlineKeyboardButton("3 tháng",
                                 callback_data="guided:set:lease_min:3"),
            InlineKeyboardButton("6 tháng",
                                 callback_data="guided:set:lease_min:6"),
            InlineKeyboardButton("12 tháng",
                                 callback_data="guided:set:lease_min:12"),
        ]]
        return ("Hợp đồng tối thiểu mấy tháng ạ? "
                f"(hoặc gõ số khác) {tag}",
                _guided_back_kb(kb))

    if step == "deposit":
        kb = [[
            InlineKeyboardButton("1 tháng",
                                 callback_data="guided:set:deposit:1"),
            InlineKeyboardButton("2 tháng",
                                 callback_data="guided:set:deposit:2"),
            InlineKeyboardButton("3 tháng",
                                 callback_data="guided:set:deposit:3"),
        ]]
        return ("Đặt cọc mấy tháng ạ? "
                f"(hoặc gõ số khác) {tag}",
                _guided_back_kb(kb))

    if step == "pay_schedule":
        kb = [
            [InlineKeyboardButton(
                "Hàng tháng",
                callback_data="guided:set:pay_schedule:monthly"),
             InlineKeyboardButton(
                 "3 tháng/lần",
                 callback_data="guided:set:pay_schedule:quarterly")],
            [InlineKeyboardButton(
                "6 tháng/lần",
                callback_data="guided:set:pay_schedule:semiannual"),
             InlineKeyboardButton(
                 "1 năm/lần",
                 callback_data="guided:set:pay_schedule:yearly")],
        ]
        return f"Trả tiền theo lịch nào ạ? {tag}", _guided_back_kb(kb)

    if step == "amenities":
        chosen = set(gd["answers"].get("amenities") or [])
        kb = []
        for i in range(0, len(GUIDED_AMENITIES), 2):
            row = []
            for code, label in GUIDED_AMENITIES[i:i + 2]:
                mark = "✓ " if code in chosen else ""
                row.append(InlineKeyboardButton(
                    f"{mark}{label}",
                    callback_data=f"guided:amen:{code}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("✅ Xong",
                                        callback_data="guided:amen:done")])
        return ("Tiện ích nổi bật? (bấm để chọn nhiều, xong bấm ✅ Xong) "
                f"{tag}", _guided_back_kb(kb))

    if step == "photos":
        return ("Anh gửi ảnh nhé 📸 (gửi bao nhiêu cũng được — "
                f"5s không gửi thêm thì em hỏi) {tag}",
                _guided_back_kb())

    if step == "description":
        kb = [[InlineKeyboardButton("Xong ⏭️", callback_data="guided:skip")]]
        return ("Còn thông tin gì thêm không? "
                f"(mô tả, tiện ích, nội quy...) {tag}",
                _guided_back_kb(kb))

    return "Xong!", MENU_KB


async def _guided_show(update, ctx, edit=True):
    """Render the current guided step. edit=True for callback queries."""
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    text, kb = _guided_step_content(gd)
    if edit and update.callback_query:
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb)
    else:
        chat_id = gd.get("chat_id") or update.effective_chat.id
        await ctx.bot.send_message(chat_id, text, reply_markup=kb)


def _guided_advance(gd):
    gd["step"] += 1


async def guided_mode_free(update, ctx):
    """Broker has a listing ready — arm the free-form collection buffer."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ctx.user_data.pop("guided", None)
    _buffers[uid] = {"texts": [], "photos": [],
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": q.message.chat_id}
    await q.edit_message_text(
        "Ok anh, anh gửi tin đi ạ — text + ảnh, gửi nhiều tin nhắn cũng được 📥\n"
        "Em nhận text rồi thì bảo đang đợi ảnh, và ngược lại nhé.")
    asyncio.create_task(_flush_after(uid, ctx))


async def guided_mode_guided(update, ctx):
    """Broker wants step-by-step help — start the guided flow."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ctx.user_data["guided"] = {"step": 0, "answers": {},
                               "chat_id": q.message.chat_id}
    await _guided_show(update, ctx, edit=True)


async def guided_set(update, ctx):
    """Button answer for the current step: guided:set:<step>:<value>."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    _, _, step, value = q.data.split(":", 3)
    if step != GUIDED_STEPS[gd["step"]]:
        return  # stale button
    answers = gd["answers"]
    # sub-prompts needing a free-text follow-up
    if value == "5plus" and step in ("bedrooms", "bathrooms"):
        gd["awaiting_free"] = step
        label = "phòng ngủ" if step == "bedrooms" else "phòng tắm"
        await q.edit_message_text(
            f"Cụ thể mấy {label} ạ?",
            reply_markup=_guided_back_kb())
        return
    if step == "availability" and value == "date":
        gd["awaiting_free"] = step
        await q.edit_message_text(
            "Ngày nào ạ? (vd: 01/11)",
            reply_markup=_guided_back_kb())
        return
    if step == "district":
        d = _district_by_code(value)
        if not d:
            return
        answers["district_code"] = value
        answers["district"] = d["name"]
    elif step == "area_loc":
        d = _district_by_code(answers.get("district_code"))
        try:
            area = d["areas"][int(value)]
        except (TypeError, IndexError, ValueError, KeyError):
            return  # stale button
        answers["area_loc"] = area["name"]
    elif step == "street":
        if value == "custom":
            gd["awaiting_free"] = step
            await q.edit_message_text(
                "Đường nào ạ? (gõ tên đường giúp em)",
                reply_markup=_guided_back_kb())
            return
        d = _district_by_code(answers.get("district_code"))
        area_name = answers.get("area_loc")
        streets = []
        if d:
            for a in d["areas"]:
                if a["name"] == area_name:
                    streets = a["streets"]
                    break
        try:
            answers["street"] = streets[int(value)]
        except (IndexError, ValueError):
            return  # stale button
    elif step == "landmark":
        if value == "custom":
            gd["awaiting_free"] = step
            await q.edit_message_text(
                "Gần landmark nào ạ? (gõ tên giúp em)",
                reply_markup=_guided_back_kb())
            return
        opts = gd.get("landmark_options") or []
        try:
            answers["landmark"] = opts[int(value)]
        except (IndexError, ValueError):
            return  # stale button
    else:
        answers[step] = value
    _guided_advance(gd)
    if GUIDED_STEPS[gd["step"]] == "photos":
        await _guided_arm_photos(update, q.from_user.id, ctx,
                                 chat_id=q.message.chat_id, edit=True)
        return
    await _guided_show(update, ctx, edit=True)


async def guided_back(update, ctx):
    """Go back one step (or to the mode choice from step 0)."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    uid = q.from_user.id
    # leaving a free-text sub-prompt (5+, date) -> back to the step itself
    if gd.pop("awaiting_free", None):
        await _guided_show(update, ctx, edit=True)
        return
    if GUIDED_STEPS[gd["step"]] == "photos":
        # stash any collected photos before leaving the photo step
        buf = _buffers.pop(uid, None)
        if buf and buf.get("photos"):
            gd["answers"]["photos"] = buf["photos"]
    if gd["step"] == 0:
        ctx.user_data.pop("guided", None)
        await q.edit_message_text(
            "Anh đã có tin viết sẵn chưa ạ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Rồi, em gửi luôn",
                                      callback_data="guided:mode:free")],
                [InlineKeyboardButton("❌ Chưa, em giúp em viết",
                                      callback_data="guided:mode:guided")],
            ]))
        return
    gd["step"] -= 1
    if GUIDED_STEPS[gd["step"]] == "photos":
        await _guided_arm_photos(update, uid, ctx,
                                 chat_id=q.message.chat_id, edit=True)
        return
    await _guided_show(update, ctx, edit=True)


async def guided_skip(update, ctx):
    """Skip an optional step: area, floor, availability, description."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    step = GUIDED_STEPS[gd["step"]]
    if step == "description":
        await _guided_finish(q.from_user.id, ctx, q.message.chat_id, gd, q)
        return
    # area / floor / availability skipped = leave empty
    _guided_advance(gd)
    if GUIDED_STEPS[gd["step"]] == "photos":
        await _guided_arm_photos(update, q.from_user.id, ctx,
                                 chat_id=q.message.chat_id, edit=True)
        return
    await _guided_show(update, ctx, edit=True)


async def guided_amen(update, ctx):
    """Toggle an amenity (guided:amen:<code>) or finish (guided:amen:done)."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd or GUIDED_STEPS[gd["step"]] != "amenities":
        return
    code = q.data.rsplit(":", 1)[-1]
    answers = gd["answers"]
    if code == "done":
        _guided_advance(gd)  # -> photos
        await _guided_arm_photos(update, q.from_user.id, ctx,
                                 chat_id=q.message.chat_id, edit=True)
        return
    chosen = answers.setdefault("amenities", [])
    if code in chosen:
        chosen.remove(code)
    else:
        chosen.append(code)
    await _guided_show(update, ctx, edit=True)


async def _guided_arm_photos(update, uid, ctx, chat_id, edit=False):
    """Enter the photo step: arm a guided collection buffer."""
    gd = ctx.user_data.get("guided")
    existing = (gd.get("answers", {}).get("photos") or []) if gd else []
    _buffers[uid] = {"texts": [], "photos": list(existing),
                     "deadline": time.time() + COLLECT_WINDOW,
                     "chat_id": chat_id, "guided": True}
    text, kb = _guided_step_content(gd)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await ctx.bot.send_message(chat_id, text, reply_markup=kb)
    asyncio.create_task(_flush_after(uid, ctx))


async def _guided_cancel(uid, ctx, chat_id):
    ctx.user_data.pop("guided", None)
    _buffers.pop(uid, None)
    await ctx.bot.send_message(chat_id, "Đã hủy, không lưu tin nào nhé.",
                               reply_markup=MENU_KB)


async def handle_guided_text(update, ctx, gd, text):
    """Route free-text answers during guided intake.

    Returns True if the text was consumed, False to fall through
    (photos step — text goes to the collection buffer).
    """
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    t = (text or "").strip()
    tl = t.lower()
    if tl in _GUIDED_CANCEL_WORDS:
        await _guided_cancel(uid, ctx, chat_id)
        return True

    step = GUIDED_STEPS[gd["step"]]
    answers = gd["answers"]

    if step == "photos":
        return False  # let normal buffer routing handle it

    # free-text follow-up for 5+ / specific date sub-prompts
    awaiting = gd.pop("awaiting_free", None)
    if awaiting == "bedrooms" or awaiting == "bathrooms":
        m = re.search(r"(\d+)", t)
        if not m or int(m.group(1)) < 5:
            label = "phòng ngủ" if awaiting == "bedrooms" else "phòng tắm"
            await update.message.reply_text(
                f"Anh gõ số {label} giúp em nhé (từ 5 trở lên) 🤔")
            gd["awaiting_free"] = awaiting  # keep waiting
            return True
        answers[awaiting] = m.group(1)
        _guided_advance(gd)
        await _guided_show(update, ctx, edit=False)
        return True
    if awaiting == "availability":
        if not t or tl in _GUIDED_SKIP_WORDS:
            await update.message.reply_text("Ngày nào ạ? (vd: 01/11)")
            gd["awaiting_free"] = awaiting
            return True
        answers["availability"] = t
        _guided_advance(gd)
        if GUIDED_STEPS[gd["step"]] == "photos":
            await _guided_arm_photos(update, uid, ctx, chat_id, edit=False)
            return True
        await _guided_show(update, ctx, edit=False)
        return True
    if awaiting in ("street", "landmark"):
        if not t:
            await update.message.reply_text(
                "Anh gõ lại giúp em nhé 🤔")
            gd["awaiting_free"] = awaiting
            return True
        answers[awaiting] = t
        _guided_advance(gd)
        await _guided_show(update, ctx, edit=False)
        return True

    if step in ("bedrooms", "bathrooms", "ptype", "district", "area_loc",
                "street", "landmark", "furnishing", "pet", "amenities",
                "pay_schedule"):
        await update.message.reply_text("Anh bấm nút giúp em nhé 👆")
        return True

    if step == "price":
        price, _ = listing_parser.parse_price(t)
        if price is None:
            await update.message.reply_text(
                "Em chưa hiểu giá, anh gõ lại giúp em nhé (vd: 12tr) 🤔")
            return True
        answers["price_vnd"] = price
    elif step == "area":
        if tl in _GUIDED_SKIP_WORDS:
            pass
        else:
            m = re.search(r"(\d+(?:[.,]\d+)?)", t)
            if not m:
                await update.message.reply_text(
                    "Diện tích bao nhiêu m² ạ? (vd: 65 — hoặc bấm Bỏ qua)")
                return True
            answers["area"] = float(m.group(1).replace(",", "."))
    elif step == "building_detail":
        if tl in _GUIDED_SKIP_WORDS:
            pass
        else:
            answers["building_detail"] = t
    elif step == "floor":
        if tl in _GUIDED_SKIP_WORDS:
            pass
        else:
            m = re.search(r"(\d+)", t)
            if not m:
                await update.message.reply_text(
                    "Tầng mấy ạ? (vd: 5 — hoặc bấm Bỏ qua)")
                return True
            answers["floor"] = int(m.group(1))
    elif step == "availability":
        if tl in _GUIDED_SKIP_WORDS:
            pass
        else:
            answers["availability"] = t
    elif step in ("lease_min", "deposit"):
        m = re.search(r"(\d+)", t)
        if not m:
            label = ("hợp đồng tối thiểu" if step == "lease_min"
                     else "đặt cọc")
            await update.message.reply_text(
                f"{label.capitalize()} mấy tháng ạ? (gõ số giúp em)")
            return True
        answers[step] = m.group(1)
    elif step == "description":
        if tl in _GUIDED_SKIP_WORDS or tl in {"xong", "ok"}:
            await _guided_finish(uid, ctx, chat_id, gd, None)
            return True
        answers["description"] = t
    else:
        return True

    _guided_advance(gd)
    if GUIDED_STEPS[gd["step"]] == "photos":
        await _guided_arm_photos(update, uid, ctx, chat_id, edit=False)
        return True
    await _guided_show(update, ctx, edit=False)
    return True


def _guided_to_raw(a):
    """Synthesize listing text from guided answers for the parser."""
    parts = []
    br = a.get("bedrooms")
    ptype = a.get("ptype")
    if br == "0" or ptype == "studio":
        parts.append("Studio")
    elif br:
        parts.append(f"{br}PN")
    if a.get("bathrooms"):
        parts.append(f"{a['bathrooms']}WC")
    if a.get("price_vnd"):
        parts.append(f"giá {a['price_vnd'] / 1_000_000:g}tr/tháng")
    if a.get("area"):
        parts.append(f"{a['area']:g}m2")
    # hierarchical location: building -> landmark -> street -> area -> district
    loc = []
    if a.get("building_detail"):
        loc.append(a["building_detail"])
    if a.get("landmark"):
        loc.append(f"gần {a['landmark']}")
    if a.get("street"):
        loc.append(f"đường {a['street']}")
    if a.get("area_loc"):
        loc.append(a["area_loc"])
    if a.get("district"):
        loc.append(a["district"])
    if loc:
        parts.append(", ".join(loc))
    if a.get("floor"):
        parts.append(f"tầng {a['floor']}")
    ptxt = _PTYPE_TEXT.get(ptype)
    if ptxt and ptype != "studio":
        parts.append(ptxt)
    furn = {"full": "full nội thất", "basic": "nội thất cơ bản",
            "empty": "nhà trống"}.get(a.get("furnishing"))
    if furn:
        parts.append(furn)
    pet = a.get("pet")
    if pet == "yes":
        parts.append("cho nuôi pet")
    elif pet == "no":
        parts.append("không cho nuôi pet")
    elif pet == "neg":
        parts.append("pet thương lượng được")
    if a.get("availability") == "now":
        parts.append("còn trống")
    lease = a.get("lease_min")
    if lease:
        parts.append(f"hđ {lease} tháng")
    dep = a.get("deposit")
    if dep:
        parts.append(f"cọc {dep} tháng")
    pay = {"monthly": "trả hàng tháng", "quarterly": "trả 3 tháng/lần",
           "semiannual": "trả 6 tháng/lần",
           "yearly": "trả 1 năm/lần"}.get(a.get("pay_schedule"))
    if pay:
        parts.append(pay)
    amens = [_AMENITY_TEXT[c] for c in (a.get("amenities") or [])
             if c in _AMENITY_TEXT]
    if amens:
        parts.append("Tiện ích: " + ", ".join(amens))
    if a.get("description"):
        parts.append(a["description"])
    return ", ".join(parts)


async def _guided_finish(uid, ctx, chat_id, gd, q):
    """All steps done — synthesize text and run the normal intake path."""
    answers = gd["answers"]
    raw = _guided_to_raw(answers)
    overrides = {}
    avail = answers.get("availability")
    if avail and avail != "now":
        overrides["availability_note"] = f"trống từ {avail}"
    if answers.get("ptype") in ("penthouse", "shophouse"):
        overrides["property_type"] = answers["ptype"]
    buf = {"texts": [raw],
           "photos": answers.get("photos") or [],
           "chat_id": chat_id}
    ctx.user_data.pop("guided", None)
    if q is not None:
        await q.edit_message_text("Xong! Để em tổng hợp lại nhé ⏳")
    else:
        await ctx.bot.send_message(chat_id, "Xong! Để em tổng hợp lại nhé ⏳")
    await _process_buffer(uid, buf, ctx,
                          field_overrides=overrides or None)
