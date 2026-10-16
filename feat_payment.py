"""Payment flows: premium upgrades + deal platform-fee collection.

=====================================================================
FLOW A — PREMIUM UPGRADE (bot)
=====================================================================
1. /premium -> feat_premium.cmd_premium (bot.py:1216 CommandHandler)
   shows plans + bank info + [Đăng ký Pro/Max] buttons
2. Click [Đăng ký Pro] -> callback "premium:want:pro"
   -> feat_premium.premium_want_cb (bot.py:876)
   stores wanted_tier in ctx.user_data, shows transfer instructions
3. Broker transfers -> clicks [Tôi đã chuyển khoản] -> "premium:paid"
   -> feat_premium.premium_paid_cb (bot.py:878)
   - db.create_premium_request(uid, tier)  [db/brokers.py]
   - DM to ADMIN_TELEGRAM_ID with "/approve <uid> <tier>" instructions
4. Khanh types /approve <id> <pro|max> -> feat_premium.cmd_approve
   (bot.py:1217 CommandHandler, admin-only check inside)
   - db.set_tier(target, tier, days=30)    [db/brokers.py]
   - db.decide_premium_request(req_id, True)
   - DM to broker: "Gói Pro đã được kích hoạt!"

=====================================================================
FLOW B — PREMIUM UPGRADE (web app)
=====================================================================
1. Upgrade view -> [Nâng cấp] -> POST /api/premium/request {tier}
   -> webapp/server.py:332 routes to api_clients_deals.request_premium_api
2. request_premium_api:
   - db.create_premium_request(broker_id, tier)
   - db.queue_notification("premium_request", ...)  [db/notify.py]
     (FIX 2026-10-16: previously silent — Khanh never knew)
3. Bot poller -> feat_match.process_outbox_notifications (bot.py:1235)
   handles ntype="premium_request": DM to ADMIN_TELEGRAM_ID with
   "/approve <id> <tier>" instructions
4. Same /approve path as Flow A step 4.

=====================================================================
FLOW C — DEAL PLATFORM FEE (20% commission)
=====================================================================
1. Deal recorded -> feat_payment.payment_instructions_text()
   bot sends bank details + fee amount + deal short_id
2. Broker uploads receipt photo (has unpaid deals)
   -> feat_intake.py:1133 calls feat_payment.ask_is_receipt()
   bot asks: "Ảnh này có phải bill chuyển khoản không?"
3a. [Đúng là bill] -> "pay:receipt_yes" -> receipt_yes_cb (bot.py:1013)
    -> forward_receipt_to_admin(): photo + [Đã nhận tiền]/[Chưa thấy]
       buttons to ADMIN_TELEGRAM_ID
3b. [Không, ảnh tin đăng] -> "pay:receipt_no" -> receipt_no_cb (bot.py:1015)
    -> re-runs normal single-photo listing flow
4a. Khanh taps [Đã nhận tiền] -> "pay:confirm:<deal_id>"
    -> pay_confirm_cb (bot.py:1017, admin-only)
    -> db.mark_deal_paid(deal_id) [db/deals.py]
    -> DM to broker: "Đã xác nhận thanh toán"
4b. Khanh taps [Chưa thấy] -> "pay:reject:<deal_id>"
    -> pay_reject_cb (bot.py:1019, admin-only)
    -> DM to broker: "kiểm tra lại giúp em"

All callbacks registered in bot.py on_callback_query router.
All DB functions verified in db/ package (brokers.py, deals.py, notify.py).
"""
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import db
from utils import MENU_KB, fmt_price, get_pronoun

log = logging.getLogger("linh")


def platform_fee_for(commission_vnd):
    """Platform's cut of a deal's commission (20%)."""
    if not commission_vnd or commission_vnd <= 0:
        return 0
    return round(commission_vnd * config.PLATFORM_FEE_RATE)


def payment_instructions_text(deal):
    """Bank details + amount message sent right after a deal is recorded."""
    fee = platform_fee_for(deal.get("commission_vnd"))
    short_id = (deal.get("id") or "")[-6:]
    return (
        f"💰 Anh chuyển phí platform ({int(config.PLATFORM_FEE_RATE * 100)}%"
        f" hoa hồng) giúp em nhé:\n\n"
        f"🏦 {config.PAYMENT_BANK}\n"
        f"📱 MoMo: {config.PAYMENT_MOMO}\n"
        f"💵 Số tiền: <b>{fmt_price(fee)}</b>\n"
        f"📝 Nội dung: <code>{short_id}</code>\n\n"
        f"Chuyển xong anh <b>up ảnh bill</b> lên đây giúp em 📸"
    )


def deal_label(deal):
    """Short label: 'Anh Tuấn - 2PN An Thượng'."""
    cname = deal.get("client_name") or "Khách"
    linfo = ""
    lid = deal.get("listing_id")
    if lid:
        try:
            l = db.get_listing(lid)
            if l:
                p = l.get("parsed") or {}
                br = p.get("bedrooms")
                br_s = ("Studio" if br == 0
                        else (f"{int(br)}PN" if br else "?PN"))
                loc = p.get("building_name") or p.get("district") or ""
                linfo = f" - {br_s} {loc}".strip()
        except Exception:
            pass
    return f"{cname}{linfo}"


async def ask_is_receipt(update, ctx, uid, file_id):
    """Broker has unpaid debt and sent a single photo — ask if it's a receipt."""
    ctx.user_data["receipt_pending"] = {"file_id": file_id}
    await update.message.reply_text(
        "Anh ơi, anh còn công nợ chưa thanh toán.\n"
        "Ảnh này có phải bill chuyển khoản không ạ?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Đúng là bill",
                                  callback_data="pay:receipt_yes")],
            [InlineKeyboardButton("❌ Không, ảnh tin đăng",
                                  callback_data="pay:receipt_no")],
        ]))


async def receipt_yes_cb(update, ctx):
    """Broker confirmed the photo is a transfer receipt -> forward to admin."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pend = ctx.user_data.pop("receipt_pending", None)
    if not pend:
        await q.edit_message_text("Hết hạn rồi, anh up lại ảnh giúp em nhé.")
        return
    debts = db.unpaid_deals(uid)
    if not debts:
        await q.edit_message_text(
            "Anh không còn công nợ nào. Ảnh này em bỏ qua nhé 😊",
            reply_markup=MENU_KB)
        return
    deal = debts[0]  # oldest unpaid deal
    await q.edit_message_text("Em đã gửi bill cho admin kiểm tra rồi nhé ⏳")
    await forward_receipt_to_admin(ctx, uid, deal, pend["file_id"])


async def receipt_no_cb(update, ctx):
    """Not a receipt — continue the normal single-photo listing flow."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    pend = ctx.user_data.pop("receipt_pending", None)
    if not pend:
        await q.edit_message_text("Ok ạ.", reply_markup=MENU_KB)
        return
    # Re-run the normal single-photo path with the stashed file_id.
    from feat_intake import _handle_single_photo  # lazy: avoid cycle
    fake_msg = q.message  # has .chat for chat_id
    await q.edit_message_text("Ok, em xử lý như ảnh tin đăng nhé 📸")
    await _handle_single_photo(update, ctx, uid, fake_msg,
                               pend["file_id"], caption="")


async def forward_receipt_to_admin(ctx, broker_id, deal, file_id):
    """Send the receipt photo to Khanh with confirm/reject buttons."""
    admin_id = config.ADMIN_TELEGRAM_ID
    if not admin_id:
        log.warning("ADMIN_TELEGRAM_ID not set; cannot forward receipt")
        try:
            await ctx.bot.send_message(
                chat_id=broker_id,
                text="Em chưa gửi được bill cho admin (chưa cấu hình)."
                     " Anh liên hệ trực tiếp nhé.",
                reply_markup=MENU_KB)
        except Exception:
            pass
        return
    broker = db.get_broker(broker_id) or {}
    bname = (broker.get("display_name") or broker.get("username")
             or f"ID {broker_id}")
    fee = platform_fee_for(deal.get("commission_vnd"))
    closed = deal.get("closed_at")
    date_s = time.strftime("%d/%m/%Y", time.localtime(closed)) if closed else "?"
    caption = (
        f"💰 Broker <b>{bname}</b> vừa up bill chuyển khoản!\n\n"
        f"💵 Số tiền: <b>{fmt_price(fee)}</b>\n"
        f"📝 Deal: {deal_label(deal)}\n"
        f"📅 Ngày chốt: {date_s}\n\n"
        f"Anh check tài khoản giúp em nhé 👇"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Đã nhận tiền",
                              callback_data=f"pay:confirm:{deal['id']}")],
        [InlineKeyboardButton("❌ Chưa thấy",
                              callback_data=f"pay:reject:{deal['id']}")],
    ])
    try:
        await ctx.bot.send_photo(chat_id=admin_id, photo=file_id,
                                 caption=caption, parse_mode="HTML",
                                 reply_markup=kb)
    except Exception as e:
        log.warning("forward receipt to admin failed: %s", e)
        try:
            await ctx.bot.send_message(
                chat_id=broker_id,
                text="Em chưa gửi được bill. Anh thử up lại giúp em nhé.",
                reply_markup=MENU_KB)
        except Exception:
            pass


def _is_admin(uid):
    return bool(config.ADMIN_TELEGRAM_ID) and uid == config.ADMIN_TELEGRAM_ID


async def pay_confirm_cb(update, ctx):
    """Khanh tapped 'Đã nhận tiền' -> mark paid, notify broker."""
    q = update.callback_query
    await q.answer()
    if not _is_admin(q.from_user.id):
        await q.answer("Chỉ admin mới xác nhận được ạ.", show_alert=True)
        return
    deal_id = q.data.split(":", 2)[2] if q.data.count(":") >= 2 else ""
    deal = db.get_deal(deal_id) if deal_id else None
    if not deal:
        await q.edit_message_caption("Deal này không còn nữa.")
        return
    db.mark_deal_paid(deal_id)
    pn = get_pronoun(deal["broker_id"])
    await q.edit_message_caption(
        q.message.caption + "\n\n✅ <b>Đã xác nhận nhận tiền</b>",
        parse_mode="HTML")
    try:
        await ctx.bot.send_message(
            chat_id=deal["broker_id"],
            text=(f"✅ Đã xác nhận thanh toán, cảm ơn {pn}!\n"
                  f"Công nợ đã được xóa. Anh tiếp tục nhé 🎉"),
            reply_markup=MENU_KB)
    except Exception as e:
        log.warning("notify broker paid failed: %s", e)


async def pay_reject_cb(update, ctx):
    """Khanh tapped 'Chưa thấy' -> ask broker to re-check."""
    q = update.callback_query
    await q.answer()
    if not _is_admin(q.from_user.id):
        await q.answer("Chỉ admin mới xác nhận được ạ.", show_alert=True)
        return
    deal_id = q.data.split(":", 2)[2] if q.data.count(":") >= 2 else ""
    deal = db.get_deal(deal_id) if deal_id else None
    if not deal:
        await q.edit_message_caption("Deal này không còn nữa.")
        return
    pn = get_pronoun(deal["broker_id"])
    await q.edit_message_caption(
        q.message.caption + "\n\n❌ <b>Chưa thấy tiền về</b>",
        parse_mode="HTML")
    try:
        await ctx.bot.send_message(
            chat_id=deal["broker_id"],
            text=(f"{pn.capitalize()} kiểm tra lại giúp em nhé,"
                  f" em chưa thấy tiền về 😅\n"
                  f"Anh up lại bill giúp em 📸"),
            reply_markup=MENU_KB)
    except Exception as e:
        log.warning("notify broker reject failed: %s", e)
