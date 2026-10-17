"""Telegram commands for linking a broker's Zalo account to their Telegram.

Flow:
  1. Broker sends /linkzalo on Telegram -> gets a one-time code (15 min expiry).
  2. Broker sends the code as a Zalo DM to our receiver account.
  3. The Zalo bridge validates the code and stores zalo_id -> telegram_id.
"""
from telegram import Update
from telegram.ext import ContextTypes

import db as dbm


async def cmd_linkzalo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = dbm.create_pairing_code(user.id)
    await update.message.reply_text(
        "🔗 <b>Liên kết Zalo</b>\n\n"
        f"Mã của bạn: <code>{code}</code>\n"
        f"Hiệu lực {dbm.PAIRING_TTL_SEC // 60} phút, dùng 1 lần.\n\n"
        "Gửi mã này qua Zalo cho tài khoản nhận tin của TrueNest, "
        "từ đó tin bạn forward trên Zalo sẽ tự về Telegram này.",
        parse_mode="HTML",
    )


async def cmd_unlinkzalo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Note: unlink is by zalo_id; the bridge handles it. Here we just guide.
    await update.message.reply_text(
        "Để hủy liên kết Zalo, gửi <code>HUY LINK</code> cho tài khoản Zalo nhận tin.",
        parse_mode="HTML",
    )
