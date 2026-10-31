# WhatsApp Intake Bridge v2 (Official Cloud API)

Brokers forward listings to the business WhatsApp number; the bridge
groups each forward into a batch, asks with native reply buttons, then
saves into the broker's inventory through the shared backend
(`bridge_save.py` — the same path as the Telegram bot's forwards).
Spec: `BRIDGE_V2.md`.

## Flow

```
broker forwards (text + photos, any order)
  -> webhook -> Batcher (batch.py) -> batch closes
     (2nd different listing text | LUU keyword | 15s silence | 180s cap)
  -> ✅ reaction + quoted summary + [💾 Lưu vào kho] [🗑 Bỏ qua]
  -> tap Lưu -> download photos -> bridge_save -> DRAFT listing
Photo-only batch <=5 min after a save -> supplement question
  [📎 Gộp vào căn vừa rồi] [🆕 Căn mới]; 10 min no answer = saved separately.
```

- Every bridge message quotes the broker's anchor message.
- A save is only reported after it really succeeded; failures retry
  via an outbox (60s/300s/900s) before the broker hears anything failed.
- Open batches persist in the bot DB (`wa_bridge_state`) — restarts
  lose nothing.
- Only images are saved; video/files are counted and reported as skipped.
- Duplicates are created as new listings; a hash-suspected duplicate is
  flagged in the receipt for the broker to review.

## Files

| File | Role |
|---|---|
| `bridge.py` | webhook server, action executor, tick loop (1s) |
| `batch.py` | channel-agnostic batching engine (shared spec with Zalo port) |
| `state.py` | SQLite persistence: engine snapshots, pendings, outbox |
| `simulate.py` | 49-check behavior suite for the engine |
| `test_v2.py` | end-to-end test with stubbed Graph API (`BOT_DB_PATH=/tmp/wa_v2.db python3 test_v2.py`) |
| `../bridge_save.py` | shared backend save path (repo root) |

## Run

```bash
export WA_ACCESS_TOKEN=...        # Meta app, whatsapp_business_messaging
export WA_PHONE_NUMBER_ID=...     # test number works for the pilot
export WA_VERIFY_TOKEN=...        # any secret string, mirrored in Meta dashboard
python3 bridge.py                 # 127.0.0.1:8090/wa-webhook
# expose for Meta: cloudflared tunnel --url http://localhost:8090
```

Meta dashboard: set the webhook URL to `https://<tunnel>/wa-webhook`,
the verify token to `WA_VERIFY_TOKEN`, subscribe to `messages`.

## One-time bot wiring (Khanh, in bot.py after pulling this branch)

```python
import feat_whatsapp
app.add_handler(CommandHandler("linkwhatsapp", feat_whatsapp.cmd_linkwhatsapp))
app.add_handler(CommandHandler("unlinkwhatsapp", feat_whatsapp.cmd_unlinkwhatsapp))
```

Brokers then run `/linkwhatsapp` in the bot and send the `WA-XXXXXX`
code to the business number once.
