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
import feat_premium
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
    get_forward_source, strip_forward_noise, content_hash_for_listing,
)

log = logging.getLogger("linh")

async def on_new_listing_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User tapped 📝 Gửi tin mới — ask whether they have a listing ready
    or want guided step-by-step help."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    # enterprise volume gate: >300 active listings requires Enterprise tier
    if db.requires_enterprise_tier(uid):
        await feat_premium.send_gate(q, "enterprise_volume", uid, edit=True)
        return
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
        "Anh muốn nhập căn mới kiểu nào ạ?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Nhập từ đầu (em hỏi từng bước)",
                                  callback_data="guided:mode:guided")],
            [InlineKeyboardButton("📋 Nhập từ tin có sẵn (forward/paste bài FB)",
                                  callback_data="guided:mode:free")],
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
    listing = db.get_listing(listing_id)
    if not listing:
        await q.edit_message_text("Tin này không còn nữa 😅")
        return
    photos = (listing.get("photo_file_ids") or []) + [file_id]
    db.update_listing(listing_id, photo_file_ids=photos)
    await q.edit_message_text(
        f"Đã thêm ảnh vào tin rồi anh ✓ 📸 (tổng {len(photos)} ảnh)")


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

async def handle_forward_text(update, ctx, uid, text, fwd_source):
    """Forwarded text message: complete content → parse and create a draft
    IMMEDIATELY (no 5s collection wait). Replies to the forwarded message.
    Each forward = its own listing; manual buffers are untouched.
    """
    msg = update.message
    clean = strip_forward_noise(text)
    if not clean:
        await msg.reply_text(
            "Tin forward này trống, anh kiểm tra lại giúp em nhé 😅",
            reply_to_message_id=msg.message_id)
        return
    buf = {
        "texts": [clean],
        "photos": [],
        "deadline": time.time(),
        "chat_id": msg.chat.id,
        "forward_source": fwd_source,
    }
    await _process_buffer(uid, buf, ctx,
                          reply_to_message_id=msg.message_id)


async def _process_buffer(uid, buf, ctx, field_overrides=None,
                          reply_to_message_id=None):
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
    chash = content_hash_for_listing(buf["texts"], photos)
    listing_id = db.create_listing(
        uid, raw_text=raw, photo_file_ids=photos,
        parsed=result["fields"], missing_fields=result["missing"],
        status="draft", content_hash=chash,
    )
    pn = get_pronoun(uid)
    phone_note = f" (SĐT của {pn})" if phone_autofilled else ""
    fwd_source = buf.get("forward_source") or ""
    confirming_data = {"listing_id": listing_id,
                       "phone_note": phone_note,
                       "forward_source": fwd_source,
                       "awaiting_highlights": True,
                       "reply_to_message_id": reply_to_message_id}
    if ctx.user_data.get("confirming"):
        # Another draft is awaiting confirmation (e.g. back-to-back
        # forwards) — queue this one instead of overwriting.
        ctx.user_data.setdefault("confirming_queue", []).append(
            confirming_data)
        send_kw = {}
        if reply_to_message_id:
            send_kw["reply_to_message_id"] = reply_to_message_id
        await ctx.bot.send_message(
            chat_id,
            "Em đã lưu nháp tin này rồi 📝"
            " Anh xác nhận tin trước xong, em hiện tin này tiếp nhé!",
            **send_kw)
        return
    ctx.user_data["confirming"] = confirming_data
    l = db.get_listing(listing_id)
    text, kb = _confirm_summary(l, pn, phone_note, fwd_source, hl_stage=True)
    send_kw = {"reply_markup": kb}
    if reply_to_message_id:
        send_kw["reply_to_message_id"] = reply_to_message_id
    await ctx.bot.send_message(chat_id, text, **send_kw)


async def _promote_next_confirming(ctx, chat_id, uid):
    """Show the next queued draft confirmation, if any.

    Called after the current draft is fully submitted/linked.
    Returns True if another draft was promoted.
    """
    q = ctx.user_data.get("confirming_queue") or []
    while q:
        nxt = q.pop(0)
        l = db.get_listing(nxt["listing_id"])
        if not l:
            continue  # draft was deleted — try the next one
        if not q:
            ctx.user_data.pop("confirming_queue", None)
        ctx.user_data["confirming"] = nxt
        pn = get_pronoun(uid)
        text, kb = _confirm_summary(
            l, pn, nxt.get("phone_note", ""),
            nxt.get("forward_source", ""),
            hl_stage=nxt.get("awaiting_highlights", False))
        await ctx.bot.send_message(chat_id, text, reply_markup=kb)
        return True
    ctx.user_data.pop("confirming_queue", None)
    return False


async def hl_done_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broker tapped [Bỏ qua, tiếp tục] on the highlights prompt —
    move to the normal [Đúng rồi]/[Sửa] confirmation."""
    q = update.callback_query
    await q.answer()
    lid = q.data.split(":", 2)[2]  # "cfm:hl_done:<listing_id>"
    confirming = ctx.user_data.get("confirming")
    l = db.get_listing(lid)
    if not l:
        ctx.user_data.pop("confirming", None)
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return
    if confirming and confirming.get("listing_id") == lid:
        confirming["awaiting_highlights"] = False
        phone_note = confirming.get("phone_note", "")
        fwd_source = confirming.get("forward_source", "")
    else:
        phone_note, fwd_source = "", ""
    pn = get_pronoun(q.from_user.id)
    t, kb = _confirm_summary(l, pn, phone_note, fwd_source, hl_stage=False)
    await q.edit_message_text(t, reply_markup=kb)


async def _try_final_submit(update_or_q, ctx, uid, listing_id, chat_id, pn,
                            via_callback, reply_to_message_id=None):
    """Shared final-submit path: enterprise gate -> dedup check -> submit.

    Returns True if submitted, False if blocked (gate shown) or deferred
    (dup prompt shown).
    """
    async def _say(text, kb=None):
        if via_callback:
            await update_or_q.edit_message_text(text, reply_markup=kb)
        else:
            await update_or_q.message.reply_text(text, reply_markup=kb)

    l = db.get_listing(listing_id)
    if not l:
        await _say("Tin này không còn nữa.", MENU_KB)
        return False
    # enterprise volume gate
    if db.requires_enterprise_tier(uid):
        await feat_premium.send_gate(update_or_q, "enterprise_volume", uid,
                                     edit=via_callback)
        return False
    p = l["parsed"]
    # duplicate suggestion before final submit — suggest only, never
    # auto-merge or block. Broker chooses; timeout defaults to new listing.
    if not ctx.user_data.pop("dup_confirmed", None):
        dup_old = None
        chash = l.get("content_hash")
        if chash:
            dup_old = db.find_exact_duplicate_by_hash(
                uid, chash, exclude_id=listing_id)
        if not dup_old:
            dups = db.find_potential_duplicates(uid, p, exclude_id=listing_id)
            dup_old = dups[0] if dups else None
        if dup_old:
            await _ask_duplicate_confirm(_say, ctx, listing_id, dup_old, pn,
                                         chat_id, uid,
                                         reply_to_message_id)
            return False
    db.set_listing_status(listing_id, "submitted", changed_by="bot")
    # Referral auto-check: if this broker was invited and now qualifies,
    # run fraud checks and credit the inviter (Khanh 2026-10-16).
    try:
        from feat_referral import on_listing_submitted  # lazy: avoid cycle
        await on_listing_submitted(ctx, uid)
    except Exception:
        log.warning("referral auto-check failed", exc_info=True)
    # auto-generate Vietnamese FB post and save with the listing.
    # Silent — broker sees it in the ✍️ write menu. Other languages
    # are generated on demand from there.
    from feat_write import generate_post  # lazy: avoid cycle
    try:
        post_vi = generate_post(l, "vi")
        if post_vi and post_vi.strip():
            db.save_post(listing_id, post_vi.strip(), "vi")
    except Exception:
        log.warning("auto-generate vi post failed for %s", listing_id,
                    exc_info=True)
    # Upload photos to R2 in the background so the web app can display
    # them. Non-blocking — the bot responds immediately; failures are
    # logged and the listing still works via Telegram file_id.
    # After upload, dhash image-duplicate check runs; matches from the
    # broker's other listings trigger a suggestion (never auto-merge).
    try:
        import photos as _photos  # lazy: avoid cycle
        _fids = list(l.get("photo_file_ids") or [])
        _token = getattr(config, "BOT_TOKEN", "")
        if _fids and _token:
            asyncio.create_task(_upload_photos_and_check_dups(
                _photos, listing_id, _fids, _token, chat_id, uid, ctx, pn))
    except Exception:
        log.warning("R2 photo upload task failed to start for %s",
                    listing_id, exc_info=True)
    from feat_write import _maybe_write_post_finish  # lazy: avoid cycle
    if await _maybe_write_post_finish(chat_id, uid, listing_id, ctx):
        await _promote_next_confirming(ctx, chat_id, uid)
        return True
    # Batch import flow: track saved IDs, offer to continue or finish.
    # "Xong" shows summary + web app deep link filtered to this batch.
    from utils import webapp_url  # lazy: avoid cycle
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    batch = ctx.user_data.setdefault("batch_import", [])
    if listing_id not in batch:
        batch.append(listing_id)
    title = listing_line(l).split("\n")[0] if listing_line else listing_id
    batch_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Nhập tiếp", callback_data="batch:more")],
        [InlineKeyboardButton("✅ Xong", callback_data="batch:done")],
    ])
    await _say(f"Đã lưu ✅ ({title})\n\nNhập tiếp căn nữa không?", batch_kb)
    # proactive tip: 1st and 5th listing milestones (exact count only).
    # Sent as a new message via bot (not _say, which would edit).
    try:
        import hints as _hints  # lazy: avoid cycle
        n = db.count_broker_listings(uid)
        tip = _hints.tip_after_listing(n)
        if tip and ctx.bot:
            await ctx.bot.send_message(
                chat_id=chat_id, text=tip,
                reply_markup=MENU_KB, parse_mode="HTML")
    except Exception:
        log.warning("proactive listing tip failed", exc_info=True)
    await _promote_next_confirming(ctx, chat_id, uid)
    return True


async def _finalize_after_confirm(update_or_q, ctx, uid, listing_id, chat_id,
                                via_callback):
    """Broker confirmed the summary ([Đúng rồi] button or typed 'đúng rồi'):
    ask missing critical fields (max 2) or finish the save."""
    confirming = ctx.user_data.pop("confirming", None)
    reply_to = (confirming or {}).get("reply_to_message_id")
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
        await _try_final_submit(update_or_q, ctx, uid, listing_id, chat_id,
                                pn, via_callback,
                                reply_to_message_id=reply_to)


async def batch_more_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broker wants to import another listing — clear state, ready for next."""
    q = update.callback_query
    await q.answer()
    # Clear any in-progress intake state but keep the batch_import list.
    for key in ("confirming", "awaiting", "guided", "dup_check"):
        ctx.user_data.pop(key, None)
    await q.edit_message_text(
        "Ok! Anh forward hoặc paste tin tiếp theo nhé 📋",
        reply_markup=None,
    )


async def batch_done_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broker finished batch import — show summary + web app deep link."""
    q = update.callback_query
    await q.answer()
    from utils import webapp_url  # lazy: avoid cycle
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    batch = ctx.user_data.pop("batch_import", [])
    n = len(batch)
    if n == 0:
        await q.edit_message_text("Xong! Hẹn gặp lại anh nhé 👋",
                                  reply_markup=MENU_KB)
        return
    if n == 1:
        text = "Xong! Đã nhập 1 căn ✅"
    else:
        text = f"Xong! Đã nhập {n} căn ✅"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📱 Xem trong web app",
            web_app=WebAppInfo(url=webapp_url(
                view="batch", ids=",".join(batch))))],
        [InlineKeyboardButton("⬅️ Menu", callback_data="menu:back")],
    ])
    await q.edit_message_text(text, reply_markup=kb)


async def confirm_save_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lid = q.data.split(":", 2)[2]  # "cfm:save:<listing_id>" (ids contain ':')
    await _finalize_after_confirm(q, ctx, q.from_user.id, lid,
                                  q.message.chat_id, via_callback=True)


async def _ask_duplicate_confirm(say, ctx, draft_id, old, pn, chat_id, uid,
                                 reply_to_message_id=None):
    """Suggest a potential duplicate. Never auto-merge, auto-skip, or block.

    Broker chooses: view old / create new / link as duplicate.
    No response within 60s → default to creating a new listing.
    Replies to the original forwarded message when available.
    """
    from utils import listing_line
    op = old.get("parsed") or {}
    br = op.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = op.get("building_name") or op.get("district") or "?"
    price = op.get("price_vnd")
    price_s = f"{price / 1_000_000:g}tr/tháng" if price else "?/tháng"
    days = int((time.time() - old["created_at"]) / 86400)
    age = f"{days} ngày trước" if days > 0 else "hôm nay"
    ctx.user_data["dup_check"] = {"draft_id": draft_id, "old_id": old["id"]}
    text = (
        f"💡 Tin này có vẻ giống tin <b>{br_s} {loc}, {price_s}</b>"
        f" {pn} đã gửi {age}.\n\n"
        f"{pn.capitalize()} chọn giúp em nhé 👇")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Xem tin cũ",
                              callback_data="dup:view")],
        [InlineKeyboardButton("✅ Vẫn tạo tin mới",
                              callback_data="dup:save")],
        [InlineKeyboardButton("🔗 Gộp vào tin cũ",
                              callback_data="dup:skip")],
    ])
    if reply_to_message_id:
        await ctx.bot.send_message(
            chat_id, text, parse_mode="HTML", reply_markup=kb,
            reply_to_message_id=reply_to_message_id)
    else:
        await say(text, kb)
    asyncio.create_task(_dup_check_timeout(uid, draft_id, chat_id, ctx))


async def _dup_check_timeout(uid, draft_id, chat_id, ctx, delay=60):
    """No response to the duplicate suggestion → default to new listing."""
    await asyncio.sleep(delay)
    dc = ctx.user_data.get("dup_check")
    if not dc or dc.get("draft_id") != draft_id:
        return  # broker already decided
    ctx.user_data.pop("dup_check", None)
    ctx.user_data["dup_confirmed"] = True
    l = db.get_listing(draft_id)
    if not l:
        return
    pn = get_pronoun(uid)

    class _Shim:
        async def edit_message_text(self, text, reply_markup=None):
            await ctx.bot.send_message(chat_id, text,
                                       reply_markup=reply_markup)

    await ctx.bot.send_message(
        chat_id,
        "⏰ Anh không chọn nên em tạo tin mới bình thường nhé ✓")
    await _finalize_after_confirm(_Shim(), ctx, uid, draft_id, chat_id,
                                  via_callback=True)


async def dup_action_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle dup:* callbacks from the duplicate-confirm prompt."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pn = get_pronoun(uid)
    act = q.data.split(":", 1)[1] if ":" in q.data else ""
    dc = ctx.user_data.get("dup_check") or {}
    draft_id = dc.get("draft_id")
    old_id = dc.get("old_id")

    if act == "view" and old_id:
        from feat_listings import _detail_content
        old = db.get_listing(old_id)
        if not old or old["broker_id"] != uid:
            await q.edit_message_text("Tin cũ không còn nữa 😅",
                                      reply_markup=MENU_KB)
            return
        text, kb = _detail_content(old, page=0, filt="a")
        # keep a way back to the dup decision
        rows = kb.inline_keyboard if kb else []
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Quay lại quyết định",
                                   callback_data="dup:back")]] + rows)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if act == "back" and draft_id:
        old = db.get_listing(old_id) if old_id else None
        if old:
            async def _say(t, kb=None):
                await q.edit_message_text(t, reply_markup=kb)
            await _ask_duplicate_confirm(_say, ctx, draft_id, old, pn,
                                         q.message.chat_id, uid)
        return

    if not draft_id:
        await q.edit_message_text("Hết hạn rồi, anh gửi lại giúp em nhé 😅",
                                  reply_markup=MENU_KB)
        return
    l = db.get_listing(draft_id)
    if not l or l["broker_id"] != uid:
        ctx.user_data.pop("dup_check", None)
        await q.edit_message_text("Tin này không còn nữa.",
                                  reply_markup=MENU_KB)
        return

    if act == "save":
        # broker confirms it's a genuinely new listing — proceed
        ctx.user_data.pop("dup_check", None)
        ctx.user_data["dup_confirmed"] = True
        await _finalize_after_confirm(q, ctx, uid, draft_id,
                                      q.message.chat_id, via_callback=True)
    elif act == "skip":
        # confirmed duplicate — keep for reference, linked to the original.
        # Never auto-merge or auto-delete either side.
        ctx.user_data.pop("dup_check", None)
        if old_id:
            db.update_listing(draft_id, duplicate_of=old_id)
        await q.edit_message_text(
            "Ok ạ, em đã lưu tin này dạng trùng để tham khảo 🔗\n"
            "Tin gốc vẫn giữ nguyên, không gộp không xóa gì đâu ạ.",
            reply_markup=MENU_KB)
        await _promote_next_confirming(ctx, q.message.chat_id, uid)
    else:
        await q.answer("Anh chọn giúp em nhé 👆")


async def _upload_photos_and_check_dups(photos_mod, listing_id, file_ids,
                                        token, chat_id, uid, ctx, pn):
    """Background task: upload photos to R2, store hashes, suggest dups.

    1. Uploads each photo (url + dhash + phash), stores via db.add_photo_url
       and db.add_photo_hash.
    2. For each hashed photo, finds near-duplicate images in the broker's
       OTHER listings (dHash OR pHash hamming distance <= 5).
    3. If matches found, suggests the first one: broker chooses view /
       keep / link-as-duplicate. Never auto-merges.
    """
    def _store(lid, url, dhash, phash):
        db.add_photo_url(lid, url)
        db.add_photo_hash(lid, url, dhash, phash)

    try:
        done = await photos_mod.upload_listing_photos(
            listing_id, file_ids, token, _store)
    except Exception:
        log.warning("bg photo upload failed for %s", listing_id,
                    exc_info=True)
        return

    # Dedup check: collect first match per other listing.
    seen_old = {}
    for _url, dhash, phash in done:
        if not dhash and not phash:
            continue
        try:
            matches = db.find_photos_by_hash(
                dhash, max_distance=5, exclude_id=listing_id, phash=phash)
        except Exception:
            log.warning("find_photos_by_hash failed", exc_info=True)
            continue
        for old_id, _murl, _dist in matches:
            if old_id in seen_old:
                continue
            old = db.get_listing(old_id)
            if not old or old.get("broker_id") != uid:
                continue
            seen_old[old_id] = old
    if not seen_old:
        return
    old_id, old = next(iter(seen_old.items()))
    try:
        await _ask_image_dup_confirm(ctx, chat_id, uid, pn,
                                     listing_id, old)
    except Exception:
        log.warning("image dup notify failed for %s", listing_id,
                    exc_info=True)


async def _ask_image_dup_confirm(ctx, chat_id, uid, pn, new_id, old):
    """Suggest an image-hash duplicate. Never auto-merge or block.

    Reuses the duplicate-suggestion UX pattern: broker chooses view old /
    keep new / link as duplicate. No timeout auto-action — the listing is
    already submitted, so silence means "keep".
    """
    op = old.get("parsed") or {}
    br = op.get("bedrooms")
    br_s = "Studio" if br == 0.0 else (f"{int(br)}PN" if br else "?PN")
    loc = op.get("building_name") or op.get("district") or "?"
    price = op.get("price_vnd")
    price_s = f"{price / 1_000_000:g}tr/tháng" if price else "?/tháng"
    ctx.user_data["imgdup_check"] = {"new_id": new_id, "old_id": old["id"]}
    text = (
        f"⚠️ Ảnh trong tin mới giống với ảnh trong tin"
        f" <b>{br_s} {loc}, {price_s}</b> của {pn}.\n\n"
        f"Có phải cùng một căn không {pn} 👇")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Xem tin cũ",
                              callback_data="imgdup:view")],
        [InlineKeyboardButton("✅ Vẫn giữ tin mới",
                              callback_data="imgdup:keep")],
        [InlineKeyboardButton("🔗 Gộp vào tin cũ",
                              callback_data="imgdup:merge")],
    ])
    await ctx.bot.send_message(chat_id, text, parse_mode="HTML",
                               reply_markup=kb)


async def imgdup_action_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle imgdup:* callbacks from the image-duplicate suggestion."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    act = q.data.split(":", 1)[1] if ":" in q.data else ""
    dc = ctx.user_data.get("imgdup_check") or {}
    new_id = dc.get("new_id")
    old_id = dc.get("old_id")

    if act == "view" and old_id:
        from feat_listings import _detail_content
        old = db.get_listing(old_id)
        if not old or old["broker_id"] != uid:
            await q.edit_message_text("Tin cũ không còn nữa 😅",
                                      reply_markup=MENU_KB)
            return
        text, kb = _detail_content(old, page=0, filt="a")
        rows = kb.inline_keyboard if kb else []
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Quay lại quyết định",
                                   callback_data="imgdup:back")]] + rows)
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if act == "back" and old_id and new_id:
        old = db.get_listing(old_id)
        if old:
            await _ask_image_dup_confirm(ctx, q.message.chat_id, uid,
                                         get_pronoun(uid), new_id, old)
            return
    ctx.user_data.pop("imgdup_check", None)
    if act == "merge":
        # link as duplicate — keep for reference, never delete either side.
        if old_id and new_id:
            db.update_listing(new_id, duplicate_of=old_id)
        await q.edit_message_text(
            "Ok ạ, em đã lưu tin này dạng trùng để tham khảo 🔗\n"
            "Tin gốc vẫn giữ nguyên, không gộp không xóa gì đâu ạ.",
            reply_markup=MENU_KB)
    else:
        # keep (or anything else) — listing stays as submitted.
        await q.edit_message_text("Vâng, em giữ tin mới như cũ nhé ✅",
                                  reply_markup=MENU_KB)


_CONFIRM_WORDS = {"đúng rồi", "dung roi", "đúng", "dung", "ok", "oke",
                  "okê", "chuẩn", "chuan", "ừ", "u", "ừm", "um"}


async def _handle_hl_stage_text(update, ctx, confirming, l, pn, text):
    """Text typed during the highlights (selling-points) stage.

    - Confirm words ("ok", "đúng rồi"...) → done, show normal confirmation.
    - Text with structured fields (giá, PN...) → correction, merge + re-show.
    - Anything else → split into selling points, append to highlights.
    """
    uid = update.effective_user.id
    listing_id = confirming["listing_id"]
    txt = text.strip()

    async def _reshow(stage_done=False):
        fresh = db.get_listing(listing_id)
        t, kb = _confirm_summary(
            fresh, pn, confirming.get("phone_note", ""),
            confirming.get("forward_source", ""),
            hl_stage=not stage_done)
        await natural_delay(update)
        return t, kb

    # 1. confirm word → finish highlights stage
    if txt.lower() in _CONFIRM_WORDS:
        confirming["awaiting_highlights"] = False
        t, kb = await _reshow(stage_done=True)
        await update.message.reply_text("Ok, tiếp tục nhé ✓\n\n" + t,
                                        reply_markup=kb)
        return

    # 2. structured fields → correction (merge, stay in hl stage)
    result = listing_parser.parse_listing(txt)
    fields = {k: v for k, v in result["fields"].items()
              if k not in ("photo_count", "description", "highlights")
              and v is not None}
    if fields:
        for k, v in fields.items():
            db.update_listing_field(listing_id, k, v, changed_by="broker")
        old_raw = l.get("raw_text") or ""
        db.update_listing(listing_id, raw_text=(old_raw + "\n" + txt).strip())
        t, kb = await _reshow()
        await update.message.reply_text("Em cập nhật rồi nhé ✓\n\n" + t,
                                        reply_markup=kb)
        return

    # 3. otherwise → selling points: split on commas/newlines, append
    parts = [p.strip(" •–—-") for p in re.split(r"[,;\n]+", txt)]
    parts = [p for p in parts if p]
    if not parts:
        t, kb = await _reshow()
        await update.message.reply_text(t, reply_markup=kb)
        return
    cur = (l["parsed"] or {}).get("highlights") or []
    seen_lower = {h.lower() for h in cur}
    added = 0
    for p in parts:
        if p.lower() not in seen_lower:
            cur.append(p)
            seen_lower.add(p.lower())
            added += 1
    if added:
        db.update_listing_field(listing_id, "highlights", cur,
                                changed_by="broker")
    t, kb = await _reshow()
    await update.message.reply_text(
        f"Đã thêm {added} điểm nổi bật ✨\n\n" + t, reply_markup=kb)


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

    # ---- highlights stage: typed text = selling point (or "done")
    if confirming.get("awaiting_highlights"):
        await _handle_hl_stage_text(update, ctx, confirming, l, pn, text)
        return

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
        if k == "highlights":
            # merge with existing highlights instead of overwriting
            cur = (l["parsed"] or {}).get("highlights") or []
            seen = {h.lower() for h in cur}
            for h in v:
                if h.lower() not in seen:
                    cur.append(h)
                    seen.add(h.lower())
            db.update_listing_field(listing_id, k, cur, changed_by="broker")
        else:
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
                if k == "highlights":
                    cur = (l["parsed"] or {}).get("highlights") or []
                    seen = {h.lower() for h in cur}
                    for h in v:
                        if h.lower() not in seen:
                            cur.append(h)
                            seen.add(h.lower())
                    db.update_listing_field(listing_id, k, cur,
                                            changed_by="broker")
                else:
                    db.update_listing_field(listing_id, k, v,
                                            changed_by="broker")
    db.update_listing(listing_id, photo_file_ids=photos, raw_text=raw)
    l = db.get_listing(listing_id)
    pn = get_pronoun(uid)
    t, kb = _confirm_summary(l, pn, confirming.get("phone_note", ""),
                             confirming.get("forward_source", ""),
                             hl_stage=confirming.get("awaiting_highlights",
                                                    False))
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
    """Debounced flush of one album.

    Forwarded album: complete content → parse and create draft IMMEDIATELY
    (no 5s wait), replying to the album's first message.
    Manual album: merge into the user's collection buffer as before
    (5s window still applies for manual input).
    """
    try:
        await asyncio.sleep(MEDIA_GROUP_WINDOW)
    except asyncio.CancelledError:
        return  # superseded by a newer message in the same album
    entry = _media_groups.pop(key, None)
    if not entry or not entry["photos"]:
        return
    uid = entry["uid"]
    if entry.get("is_forward"):
        buf = {
            "texts": [entry["caption"]] if entry["caption"] else [],
            "photos": list(entry["photos"]),
            "deadline": time.time(),
            "chat_id": entry["chat_id"],
            "forward_source": entry.get("forward_source"),
        }
        await _process_buffer(
            uid, buf, ctx,
            reply_to_message_id=entry.get("reply_to_message_id"))
        return
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
        # Referral auto-check (same as final-submit path).
        try:
            from feat_referral import on_listing_submitted  # lazy
            await on_listing_submitted(ctx, uid)
        except Exception:
            log.warning("referral auto-check failed", exc_info=True)
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
    uid = update.effective_user.id

    # anti-spam: muted or banned users are blocked entirely
    blocked, block_msg = db.is_muted_or_banned(uid)
    if blocked:
        await update.message.reply_text(block_msg, reply_markup=MENU_KB)
        return

    if ctx.user_data.get("onboarding") or ctx.user_data.get("editing_contact"):
        await update.message.reply_text(
            "Anh trả lời tin nhắn trên giúp em trước nhé? 😊")
        return
    msg = update.message
    file_id = msg.photo[-1].file_id  # largest size
    caption = (msg.caption or "").strip()
    mg_id = msg.media_group_id
    fwd_src = get_forward_source(msg)

    # F0. forwarded photo → always a NEW listing import, bypasses all
    # state routing (confirming/awaiting/guided). Each forward = 1 listing.
    if fwd_src:
        if mg_id:
            await _handle_album_photo(update, ctx, uid, msg, file_id,
                                      caption, mg_id, fwd_src)
        else:
            await _handle_single_photo(update, ctx, uid, msg, file_id,
                                       caption)
        return

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

    # 1c. receipt? broker has unpaid debt and sent a SINGLE photo
    # (albums go through the normal listing flow — a receipt is 1 photo).
    mg_id = msg.media_group_id
    if not mg_id and not ctx.user_data.get("receipt_pending") \
            and db.has_unpaid_debt(uid):
        import feat_payment  # lazy: avoid cycle
        await feat_payment.ask_is_receipt(update, ctx, uid, file_id)
        return

    # 2. part of a manual album? buffer by media_group_id, debounce,
    # then merge into the collection buffer.
    if mg_id:
        await _handle_album_photo(update, ctx, uid, msg, file_id,
                                  caption, mg_id, None)
        return

    # 3. single photo — caption goes through the same pipeline as text
    await _handle_single_photo(update, ctx, uid, msg, file_id, caption)


async def _handle_album_photo(update, ctx, uid, msg, file_id, caption,
                              mg_id, fwd_src):
    """Collect one photo of an album (media group), debounced.

    Forwarded albums are flagged is_forward → _flush_media_group processes
    them immediately as their own listing. Manual albums merge into the
    collection buffer as before.
    """
    key = f"{uid}:{mg_id}"
    entry = _media_groups.get(key)
    if entry and entry.get("task"):
        entry["task"].cancel()
    if entry is None:
        entry = {"photos": [], "caption": "", "uid": uid,
                 "chat_id": msg.chat.id, "task": None,
                 "forward_source": fwd_src,
                 "is_forward": bool(fwd_src),
                 "reply_to_message_id": msg.message_id}
        _media_groups[key] = entry
    entry["photos"].append(file_id)
    if caption and not entry["caption"]:
        entry["caption"] = strip_forward_noise(caption) if fwd_src else caption
    if not entry.get("forward_source") and fwd_src:
        entry["forward_source"] = fwd_src
    entry["task"] = asyncio.create_task(_flush_media_group(key, ctx))


async def _handle_single_photo(update, ctx, uid, msg, file_id, caption=""):
    """Step 3 of on_photo, extracted so the receipt flow can re-enter it.

    `msg` needs `.chat.id`; `update` needs `.message.reply_text`.
    """
    fwd_source = get_forward_source(msg)
    if fwd_source and caption:
        caption = strip_forward_noise(caption)
    if fwd_source:
        # Forwarded single photo: complete content → parse and create
        # draft IMMEDIATELY (no 5s wait), replying to the photo.
        # Each forward = its own listing; manual buffers are untouched.
        buf = {
            "texts": [caption] if caption else [],
            "photos": [file_id],
            "deadline": time.time(),
            "chat_id": msg.chat.id,
            "forward_source": fwd_source,
        }
        await _process_buffer(
            uid, buf, ctx, reply_to_message_id=msg.message_id)
        return
    buf = _buffers.get(uid)
    if buf:
        buf["photos"].append(file_id)
        if caption:
            buf["texts"].append(caption)
        buf["deadline"] = time.time() + COLLECT_WINDOW
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
        pn = get_pronoun(uid)
        await _try_final_submit(update, ctx, uid, listing_id, chat_id, pn,
                                via_callback=False)


# ---------------------------------------------------------------- advanced query



# ---------------------------------------------------------------- guided intake
# Step-by-step listing creation for brokers who don't have a listing written.

GUIDED_STEPS = ["bedrooms", "bathrooms", "ptype", "price", "area",
                "ward", "street", "landmark", "building_detail",
                "floor", "furnishing", "pet",
                "availability", "lease_min", "deposit", "pay_schedule",
                "amenities", "photos", "description"]

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
# Post-merger catalog: data/danang_locations.json via locations.py
# (94 admin units, 3682 streets, 925 buildings)

_LOC = None


def _loc():
    global _LOC
    if _LOC is None:
        import locations as _l
        _LOC = _l
    return _LOC


def _unaccent(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "d").lower()


def _landmark_suggestions(ward_name, limit=6):
    """Suggest catalog landmarks, preferring entries near the ward name."""
    try:
        import buildings as _bld
        entries = _bld.buildings_in_district(ward_name or "")
        if not entries:
            entries = _bld.load_catalog()[:limit]
        return [e["name"] for e in entries[:limit]]
    except Exception:
        return []


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

    if step == "ward":
        wards = _loc().get_wards()
        kb = []
        for i in range(0, len(wards), 2):
            row = [InlineKeyboardButton(
                w["name"], callback_data=f"guided:set:ward:{i + j}")
                for j, w in enumerate(wards[i:i + 2])]
            kb.append(row)
        kb.append([InlineKeyboardButton("🔍 Tìm xã/phường khác",
                                        callback_data="guided:set:ward:more")])
        kb.append([InlineKeyboardButton("Bỏ qua",
                                        callback_data="guided:skip")])
        return (f"Phường/xã nào ạ? (hoặc gõ tên để tìm) {tag}",
                _guided_back_kb(kb))

    if step == "street":
        kb = [[InlineKeyboardButton("Bỏ qua",
                                    callback_data="guided:skip")]]
        return (f"Đường nào ạ? (gõ vài chữ, vd: trần hưng đạo) {tag}",
                _guided_back_kb(kb))

    if step == "landmark":
        ward_name = gd["answers"].get("ward")
        opts = _landmark_suggestions(ward_name or "")
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
        "Anh forward tin nhắn hoặc paste bài đăng FB vào đây nhé 📋\n\n"
        "Em sẽ tự bóc tách: giá, diện tích, địa chỉ, tiện ích, mô tả...\n"
        "Thiếu gì em hỏi thêm, đủ rồi em lưu vào kho luôn 📥")
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
    if step == "ward":
        if value == "more":
            gd["awaiting_free"] = "ward"
            await q.edit_message_text(
                "Anh gõ tên xã/phường giúp em (vd: hòa tiến) 🔍",
                reply_markup=_guided_back_kb())
            return
        try:
            w = _loc().get_wards()[int(value)]
        except (IndexError, ValueError):
            return  # stale button
        answers["ward"] = w["name"]
        answers["district"] = w["name"]  # backward compat: parsed field
    elif step == "street":
        # street is now free-text search only; buttons come from ssearch
        return
    elif step == "landmark":
        if value == "custom":
            gd["awaiting_free"] = step
            await q.edit_message_text(
                "Gõ tên tòa nhà (3 chữ trở lên), em tìm trong danh sách giúp anh 🔍",
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


async def guided_bset(update, ctx):
    """Broker picked a building from catalog search results."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    try:
        idx = int(q.data.rsplit(":", 1)[-1])
        name = gd["bsearch"]["names"][idx]
    except (KeyError, IndexError, ValueError):
        await q.edit_message_text("Hết hạn rồi, anh gõ lại giúp em nhé 😅")
        return
    answers = gd["answers"]
    answers["landmark"] = name
    # bonus: auto-fill street/ward from the catalog entry
    try:
        import buildings as _bld
        entry = _bld.find_building(name)
        if entry:
            if not answers.get("street") and entry.get("street"):
                answers["street"] = entry["street"]
            if not answers.get("ward") and entry.get("district"):
                answers["ward"] = entry["district"]
                answers["district"] = entry["district"]
    except Exception:
        pass
    gd.pop("bsearch", None)
    _guided_advance(gd)
    await _guided_show(update, ctx, edit=True)


async def guided_sset(update, ctx):
    """Broker picked a street from catalog search results."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    try:
        idx = int(q.data.rsplit(":", 1)[-1])
        name = gd["ssearch"]["names"][idx]
    except (KeyError, IndexError, ValueError):
        await q.edit_message_text("Hết hạn rồi, anh gõ lại giúp em nhé 😅")
        return
    gd["answers"]["street"] = name
    gd.pop("ssearch", None)
    _guided_advance(gd)
    await _guided_show(update, ctx, edit=True)


async def guided_sset_custom(update, ctx):
    """Broker wants to use their typed street text as-is."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    query = ((gd.get("ssearch") or {}).get("query") or "").strip()
    if not query:
        await q.edit_message_text("Hết hạn rồi, anh gõ lại giúp em nhé 😅")
        return
    gd["answers"]["street"] = query
    gd.pop("ssearch", None)
    _guided_advance(gd)
    await _guided_show(update, ctx, edit=True)


async def guided_sback(update, ctx):
    """Back from street search results -> re-show the street step."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    gd.pop("ssearch", None)
    await _guided_show(update, ctx, edit=True)


async def guided_wset(update, ctx):
    """Broker picked a ward/commune from search results."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    try:
        idx = int(q.data.rsplit(":", 1)[-1])
        name = gd["wsearch"]["names"][idx]
    except (KeyError, IndexError, ValueError):
        await q.edit_message_text("Hết hạn rồi, anh gõ lại giúp em nhé 😅")
        return
    gd["answers"]["ward"] = name
    gd["answers"]["district"] = name  # backward compat: parsed field
    gd.pop("wsearch", None)
    _guided_advance(gd)
    await _guided_show(update, ctx, edit=True)


async def guided_wback(update, ctx):
    """Back from ward search results -> re-show the ward step."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    gd.pop("wsearch", None)
    await _guided_show(update, ctx, edit=True)


async def guided_badd(update, ctx):
    """Broker's building isn't in the catalog — add it, then continue."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    bs = gd.get("bsearch") or {}
    query = (bs.get("query") or "").strip()
    if not query:
        await q.edit_message_text("Hết hạn rồi, anh gõ lại giúp em nhé 😅")
        return
    try:
        import buildings as _bld
        entry = _bld.add_building(query)
        name = entry["name"]
    except Exception:
        await q.edit_message_text(
            "Em chưa lưu được, anh thử lại giúp em nhé 😅")
        return
    gd["answers"]["landmark"] = name
    gd.pop("bsearch", None)
    await q.edit_message_text(f"Đã thêm \"{name}\" vào danh sách tòa nhà ✓")
    _guided_advance(gd)
    await _guided_show(update, ctx, edit=False)


async def guided_bback(update, ctx):
    """Back from building search results -> re-show the landmark step."""
    q = update.callback_query
    await q.answer()
    gd = ctx.user_data.get("guided")
    if not gd:
        return
    gd.pop("bsearch", None)
    # gd["step"] is still the landmark step (never advanced)
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
            "Anh muốn nhập căn mới kiểu nào ạ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️ Nhập từ đầu (em hỏi từng bước)",
                                      callback_data="guided:mode:guided")],
                [InlineKeyboardButton("📋 Nhập từ tin có sẵn (forward/paste bài FB)",
                                      callback_data="guided:mode:free")],
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
    if awaiting == "landmark":
        # typed building name -> fuzzy search the catalog
        if not t:
            await update.message.reply_text("Anh gõ lại giúp em nhé 🤔")
            gd["awaiting_free"] = awaiting
            return True
        if len(t) < 3:
            await update.message.reply_text(
                "Anh gõ thêm vài chữ nữa giúp em nhé (tối thiểu 3 chữ) 🔍")
            gd["awaiting_free"] = awaiting
            return True
        import buildings as _bld
        results = _bld.search_buildings(t, limit=5)
        gd["bsearch"] = {"query": t,
                         "names": [r["name"] for r in results]}
        rows = []
        for i, r in enumerate(results):
            rows.append([InlineKeyboardButton(
                r["name"][:40], callback_data=f"guided:bset:{i}")])
        rows.append([InlineKeyboardButton(
            f"➕ Thêm tòa mới: \"{t[:30]}\"", callback_data="guided:badd")])
        rows.append([InlineKeyboardButton("⬅️ Quay lại",
                                         callback_data="guided:bback")])
        if results:
            msg = f"Em tìm được {len(results)} tòa, phải cái này không anh?"
        else:
            msg = (f"Em không tìm thấy \"{t}\" trong danh sách 😅\n"
                   f"Anh thêm mới nhé?")
        await update.message.reply_text(msg,
                                        reply_markup=InlineKeyboardMarkup(rows))
        return True
    if awaiting == "street":
        # typed street -> search the 3682-street catalog
        if not t:
            await update.message.reply_text(
                "Anh gõ lại giúp em nhé 🤔")
            gd["awaiting_free"] = awaiting
            return True
        if len(t) < 2:
            await update.message.reply_text(
                "Anh gõ thêm vài chữ nữa giúp em nhé (tối thiểu 2 chữ) 🔍")
            gd["awaiting_free"] = awaiting
            return True
        results = _loc().search_streets(t, limit=5)
        gd["ssearch"] = {"query": t, "names": results}
        rows = []
        for i, name in enumerate(results):
            rows.append([InlineKeyboardButton(
                name[:40], callback_data=f"guided:sset:{i}")])
        rows.append([InlineKeyboardButton(
            f"➕ Dùng đúng chữ em gõ: \"{t[:30]}\"",
            callback_data="guided:sset:custom")])
        rows.append([InlineKeyboardButton("⬅️ Quay lại",
                                         callback_data="guided:sback")])
        if results:
            msg = f"Em tìm được {len(results)} đường, phải cái này không anh?"
        else:
            msg = (f"Em không tìm thấy \"{t}\" trong danh sách 😅\n"
                   f"Anh dùng đúng chữ đã gõ nhé?")
        await update.message.reply_text(msg,
                                        reply_markup=InlineKeyboardMarkup(rows))
        return True

    if awaiting == "ward":
        # typed ward/commune -> search all 94 units + legacy names
        if not t:
            await update.message.reply_text(
                "Anh gõ lại giúp em nhé 🤔")
            gd["awaiting_free"] = awaiting
            return True
        results = _loc().search_wards(t, limit=5)
        gd["wsearch"] = {"query": t,
                         "names": [r["name"] for r in results]}
        rows = []
        for i, r in enumerate(results):
            label = r["name"]
            if r.get("type") == "legacy_district":
                label += " (khu vực cũ)"
            rows.append([InlineKeyboardButton(
                label[:40], callback_data=f"guided:wset:{i}")])
        rows.append([InlineKeyboardButton("⬅️ Quay lại",
                                         callback_data="guided:wback")])
        if results:
            msg = f"Em tìm được {len(results)}, phải cái này không anh?"
        else:
            msg = (f"Em không tìm thấy \"{t}\" 😅\n"
                   f"Anh gõ lại hoặc bấm Quay lại chọn từ danh sách nhé.")
        await update.message.reply_text(msg,
                                        reply_markup=InlineKeyboardMarkup(rows))
        return True

    if step in ("bedrooms", "bathrooms", "ptype", "ward",
                "furnishing", "pet", "amenities",
                "pay_schedule"):
        await update.message.reply_text("Anh bấm nút giúp em nhé 👆")
        return True

    if step == "street":
        # broker typed a street name directly at the street step
        gd["awaiting_free"] = "street"
        return await handle_guided_text(update, ctx, gd, text)

    if step == "ward":
        # broker typed a ward name directly at the ward step
        gd["awaiting_free"] = "ward"
        return await handle_guided_text(update, ctx, gd, text)

    if step == "landmark":
        # broker typed again instead of tapping a search result -> new search
        if gd.get("bsearch"):
            gd["awaiting_free"] = "landmark"
            return await handle_guided_text(update, ctx, gd, text)
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
    # hierarchical location: building -> landmark -> street -> ward
    loc = []
    if a.get("building_detail"):
        loc.append(a["building_detail"])
    if a.get("landmark"):
        loc.append(f"gần {a['landmark']}")
    if a.get("street"):
        loc.append(f"đường {a['street']}")
    if a.get("ward"):
        loc.append(a["ward"])
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
