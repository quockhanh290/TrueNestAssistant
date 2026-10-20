"""Telegram commands for linking a broker's WhatsApp number to their Telegram.

Flow:
  1. Broker sends /linkwhatsapp on Telegram -> gets a one-time code (15 min expiry).
  2. Broker sends the code as a WhatsApp DM to our receiver number.
  3. The WhatsApp bridge validates the code and stores phone -> telegram_id.

Because a WhatsApp sender id IS the phone number, the bridge can also
auto-recognize senders whose phone is already registered — but v1 always
requires the pairing code for the first link (no accidental linking).
"""
from telegram import Update
from telegram.ext import ContextTypes

from db import whatsapp as wam


async def cmd_linkwhatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = wam.create_wa_pairing_code(user.id)
    await update.message.reply_text(
        "🔗 <b>Liên kết WhatsApp</b>\n\n"
        f"Mã của bạn: <code>{code}</code>\n"
        f"Hiệu lực {wam.WA_PAIRING_TTL_SEC // 60} phút, dùng 1 lần.\n\n"
        "Gửi mã này qua WhatsApp cho số nhận tin của TrueNest, "
        "từ đó tin bạn forward trên WhatsApp sẽ tự về Telegram này.",
        parse_mode="HTML",
    )


async def cmd_unlinkwhatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Note: unlink is by phone; the bridge handles it. Here we just guide.
    await update.message.reply_text(
        "Để hủy liên kết WhatsApp, gửi <code>HUY LINK</code> cho số WhatsApp nhận tin.",
        parse_mode="HTML",
    )
