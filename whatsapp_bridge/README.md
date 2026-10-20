# WhatsApp → Telegram bridge

Receiver-only bridge, mirrors `../zalo_bridge/`. Brokers **forward**
listing messages to our WhatsApp receiver number; the bridge looks up
`phone → telegram_id` and forwards the listing to their Telegram via
bot Linh.

## Architecture

```
broker's WhatsApp --forward--> our WhatsApp number (WAHA, Docker)
        |
   WAHA webhook POST --> bridge.py (this folder, :8090/waha-webhook)
        |
   db/whatsapp.py (wa_links + wa_pairing_codes)
        |
   Telegram Bot API --> broker's chat with Linh
```

The bridge never touches `db/__init__.py` — it imports `db.whatsapp`
directly.

## Setup (Windows)

1. Pull this branch.
2. Prepare a **secondary** WhatsApp number (never your main).
3. Run WAHA (Docker):

```powershell
docker run -d --name waha -p 3000:3000 `
  -e WAHA_API_KEY=choose-a-secret `
  devlikeapro/waha
```

4. Open `http://localhost:3000/dashboard` → scan QR with the secondary
   number. Set the session webhook to your bridge URL:

```powershell
# tell WAHA where to POST incoming messages
curl -X POST "http://localhost:3000/api/sessions/default" `
  -H "X-Api-Key: choose-a-secret" -H "Content-Type: application/json" `
  -d '{"config":{"webhooks":[{"url":"http://localhost:8090/waha-webhook","events":["message"]}]}}'
```

5. Start the bridge:

```powershell
cd D:\TrueNest\TrueNestAssistant
$env:WAHA_API_KEY="choose-a-secret"
python whatsapp_bridge\bridge.py
```

6. Register the bot commands (same caveat as Zalo: `bot.py` is too big
   for the push API, so add these 3 lines after pulling):
   - `import feat_whatsapp` after `import feat_sendclient`
   - `app.add_handler(CommandHandler("linkwhatsapp", feat_whatsapp.cmd_linkwhatsapp))`
   - `app.add_handler(CommandHandler("unlinkwhatsapp", feat_whatsapp.cmd_unlinkwhatsapp))`

7. Test: on Telegram `/linkwhatsapp` → send the `WA-XXXXXX` code to the
   receiver number → forward a test listing → it should arrive in the
   bot chat.

## Safety

- Secondary number ONLY. Receiver is inbound-passive, but never risk a
  main account.
- The bridge listens to **1:1 DMs only** (`@c.us`); groups ignored.
- Rate limit 20 msgs/min/sender (silent drop); pairing-guide reply at
  most 1/hour per unknown number.
- v1 counts photos but does NOT forward them yet (same as Zalo bridge v1).
- Upgrade path: swap the WAHA webhook inbound for the official
  WhatsApp Cloud API webhook later — `bridge.py`'s `handle_message`
  does not care where the message came from.
