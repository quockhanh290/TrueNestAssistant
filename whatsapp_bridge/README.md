# WhatsApp → Telegram bridge (official Cloud API)

Receiver-only bridge, mirrors `../zalo_bridge/`. Brokers **forward**
listing messages to our WhatsApp Business number; the bridge looks up
`phone → telegram_id` and forwards the listing to their Telegram via
bot Linh.

## Architecture

```
broker's WhatsApp --forward--> our WhatsApp Business number (Meta Cloud API)
        |
   Meta webhook POST --> bridge.py (this folder, :8090/wa-webhook)
        |
   db/whatsapp.py (wa_links + wa_pairing_codes)
        |
   Telegram Bot API --> broker's chat with Linh
```

The bridge never touches `db/__init__.py` — it imports `db.whatsapp`
directly.

## Setup (Windows)

1. Pull this branch.
2. **Meta setup** (one-time, ~30 phút):
   - Tạo app tại developers.facebook.com → thêm sản phẩm **WhatsApp**.
   - Trong WhatsApp → API Setup: dùng **số test** của Meta để thử ngay,
     hoặc **Add phone number** để đăng ký số thật (nhận OTP 1 lần).
   - Tạo **permanent access token** (System User) với quyền
     `whatsapp_business_messaging`.
   - Ghi lại: `Access Token`, `Phone number ID`.
3. Expose bridge ra internet (Meta cần HTTPS công khai). Dùng tunnel
   cậu đã có:

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8090
```

4. Start the bridge:

```powershell
cd D:\TrueNest\TrueNestAssistant
$env:WA_ACCESS_TOKEN="<token>"
$env:WA_PHONE_NUMBER_ID="<phone number id>"
$env:WA_VERIFY_TOKEN="<tự đặt chuỗi bí mật>"
python whatsapp_bridge\bridge.py
```

5. Trong Meta dashboard → WhatsApp → Configuration → Webhook:
   - Callback URL: `https://<tunnel-của-cậu>/wa-webhook`
   - Verify token: chuỗi ở bước 4 (Meta gọi GET để xác thực 1 lần).
   - Subscribe field **messages**.

6. Register the bot commands (same caveat as Zalo: `bot.py` is too big
   for the push API, so add these 3 lines after pulling):
   - `import feat_whatsapp` after `import feat_sendclient`
   - `app.add_handler(CommandHandler("linkwhatsapp", feat_whatsapp.cmd_linkwhatsapp))`
   - `app.add_handler(CommandHandler("unlinkwhatsapp", feat_whatsapp.cmd_unlinkwhatsapp))`

7. Test: on Telegram `/linkwhatsapp` → send the `WA-XXXXXX` code to the
   Business number → forward a test listing → it should arrive in the
   bot chat.

## Notes

- **Chính thức, không lo ban.** Nhận tin free; rep trong 24h ~
  150đ/tin sau 1.000 tin free/tháng (ước tính ~150k/tháng ở 200 broker).
- Volume của mình (< 250 conversations/24h) không cần business
  verification.
- Rate limit 20 msgs/min/sender (silent drop); pairing-guide reply at
  most 1/hour per unknown number.
- v1 counts photos but does NOT forward them yet (same as Zalo bridge v1).
- Luồng này phục vụ mảng expat — khách/broker nước ngoài dùng
  WhatsApp là chính.
