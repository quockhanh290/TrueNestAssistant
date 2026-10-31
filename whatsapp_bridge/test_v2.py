#!/usr/bin/env python3
"""End-to-end test of whatsapp_bridge/bridge.py v2 with stubbed Graph API."""
import os
import sys
import time

os.environ["BOT_DB_PATH"] = "/tmp/wa_v2.db"
if os.path.exists("/tmp/wa_v2.db"):
    os.unlink("/tmp/wa_v2.db")

ROOT = os.path.expanduser("~/workspace/broker-bot")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "whatsapp_bridge"))

import db
db.init_db("/tmp/wa_v2.db")
from db.core import connect
from db import whatsapp as wam
wam.init_whatsapp_tables("/tmp/wa_v2.db")
with connect("/tmp/wa_v2.db") as c:
    c.execute("INSERT OR IGNORE INTO brokers (user_id, username)"
              " VALUES (111, 'testbroker')")
    c.commit()

import bridge
import bridge_save
import state as st
from batch import Event

# ---- stubs: record every outbound WA message; media + R2 faked
sent = []          # (kind, to, detail)
bridge.wa_send_text = lambda to, body, quote_msg_id="": sent.append(
    ("text", to, body, quote_msg_id)) or True
bridge.wa_send_reaction = lambda to, mid, emoji="✅": sent.append(
    ("reaction", to, mid)) or True
bridge._graph_post = lambda payload: sent.append(
    ("graph", payload.get("to"), payload)) or True
bridge.tg_send = lambda tg, text: sent.append(("telegram", tg, text))
bridge.download_media = lambda mid: b"\xff\xd8fakejpeg-" + mid.encode()
bridge_save.upload_photo_bytes = lambda data, ext=".jpg": (
    "https://r2.example/%d.jpg" % (abs(hash(data)) % 10**8),
    "0123456789abcdef", "fedcba9876543210")

PHONE = "84912345678"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def texts():
    return [s for s in sent if s[0] == "text"]


def buttons_sent():
    return [s[2] for s in sent
            if s[0] == "graph" and s[2].get("type") == "interactive"]


# 1) unlinked: pairing code links the number
code = wam.create_wa_pairing_code(111, path="/tmp/wa_v2.db")
bridge.route_event(PHONE, Event(sender=PHONE, kind="text", body=code, msg_id="w0"))
check("pairing links", wam.get_telegram_id_by_phone(PHONE) == 111)
check("pairing confirms on WA", any("Liên kết thành công" in t[2] for t in texts()))

# 2) forward block: caption text + 3 photos -> silence flush -> card
eng = bridge.get_engine(PHONE)
clock = [time.time()]
eng._now = lambda: clock[0]
bridge.route_event(PHONE, Event(sender=PHONE, kind="image", photo_id="m1",
                                caption="Cho thuê 2PN Sơn Trà 15tr/tháng, LH 0912345678",
                                msg_id="w1"))
for i in (2, 3):
    bridge.route_event(PHONE, Event(sender=PHONE, kind="image",
                                    photo_id=f"m{i}", msg_id=f"w{i}"))
check("no card before silence", len(buttons_sent()) == 0)
clock[0] += 16
acts = eng.tick()
bridge.handle_actions(PHONE, 111, acts)
check("flush sends confirm card", len(buttons_sent()) == 1
      and "save:" in buttons_sent()[0]["interactive"]["action"]["buttons"][0]["reply"]["id"])
check("receipt quotes anchor", any(t[3] == "w1" for t in texts()))
check("reaction on anchor", any(s[0] == "reaction" and s[2] == "w1" for s in sent))

# 3) tap Save -> listing created as draft with 3 photos
bid = buttons_sent()[0]["interactive"]["action"]["buttons"][0]["reply"]["id"]
bridge.handle_button(PHONE, bid)
pend = st.list_pending()
check("pending consumed", all(p["kind"] != "save" for p in pend))
with connect("/tmp/wa_v2.db") as c:
    rows = c.execute("SELECT id, status, parsed FROM tg_listings").fetchall()
check("listing saved as draft", len(rows) == 1 and rows[0][1] == "draft",
      f"rows={len(rows)}")
listing_id = rows[0][0]
lst = db.get_listing(listing_id)
check("photos attached", len(lst["photo_urls"]) == 3,
      f"urls={len(lst['photo_urls'])}")
check("saved receipt sent", any("Đã lưu vào kho" in t[2] for t in texts()))

# 4) supplement: 2 photos within 5 min -> question; tap merge -> appended
clock[0] += 60
sent.clear()
for i in (4, 5):
    bridge.route_event(PHONE, Event(sender=PHONE, kind="image",
                                    photo_id=f"m{i}", msg_id=f"w{i}"))
clock[0] += 16
acts = eng.tick()
bridge.handle_actions(PHONE, 111, acts)
supp_btns = buttons_sent()
check("supplement asks", len(supp_btns) == 1
      and supp_btns[0]["interactive"]["action"]["buttons"][0]["reply"]["id"].startswith("supp_merge:"))
mbid = supp_btns[0]["interactive"]["action"]["buttons"][0]["reply"]["id"]
bridge.handle_button(PHONE, mbid)
lst = db.get_listing(listing_id)
check("merge appended photos", len(lst["photo_urls"]) == 5,
      f"urls={len(lst['photo_urls'])}")
check("merge receipt", any("Đã gộp 2 ảnh" in t[2] for t in texts()))

# 5) restart persistence: new engine restores an open batch
bridge.route_event(PHONE, Event(sender=PHONE, kind="text",
                                body="Cho thuê 1PN An Thượng 9tr, LH 0987654321",
                                msg_id="w9"))
snap = st.load_snapshot(PHONE)
from batch import Batcher
eng2 = Batcher.restore(snap)
check("open batch survives restart",
      PHONE in eng2.batches and "An Thượng" in eng2.batches[PHONE].combined_text)

# 6) save failure -> outbox, broker NOT told it saved; retry succeeds later
real_save = bridge_save.save_bridge_listing
calls = {"n": 0}
def flaky(*a, **k):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("boom")
    return real_save(*a, **k)
bridge_save.save_bridge_listing = flaky
bridge.route_event(PHONE, Event(sender=PHONE, kind="text", body="LUU", msg_id="w10"))
# LUU typed -> keyword -> flush save_kw -> do_save raises -> outbox
# (previous open batch from step 5 is the one being saved)
out = st.due_outbox(time.time() + 61)   # first retry is due after 60s backoff
check("failure went to outbox", len(out) == 1, f"outbox={len(out)}")
check("no false saved receipt", not any("Đã lưu vào kho" in t[2] for t in texts()))
row = out[0]
st.update_outbox(row["id"], 1, time.time() - 1)   # make it due now
bridge._tick_once()
check("retry saved it", len(st.due_outbox(time.time())) == 0
      and calls["n"] == 2)
with connect("/tmp/wa_v2.db") as c:
    n = c.execute("SELECT COUNT(*) FROM tg_listings WHERE status='draft'").fetchone()[0]
check("second listing exists", n == 2, f"drafts={n}")
bridge_save.save_bridge_listing = real_save

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} pass")
sys.exit(1 if fails else 0)
