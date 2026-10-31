#!/usr/bin/env python3
"""WhatsApp intake bridge v2 — Cloud API webhook -> Batcher -> backend.

Flow (spec: BRIDGE_V2.md in this folder):
  webhook event -> normalized batch.Event -> per-sender Batcher
  -> actions -> quoted confirm card with native reply buttons
  -> broker taps [Lưu vào kho] -> photos download -> bridge_save
  (draft listing, same backend path as the Telegram bot's forwards).

Every bridge message QUOTES the broker's anchor message; a ✅ reaction
marks receipt of a closed batch. Open batches persist across restarts
(state.py); failed saves retry via an outbox before the broker is told
anything failed. Supplement batches (photos only, <=5 min after a save)
ask [Gộp vào căn vừa rồi] [Căn mới]; no answer in 10 min = saved as a
separate listing. Stdlib only.

Env: WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, WA_VERIFY_TOKEN.
Bot token is read from ../token.txt (pairing notifications).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from db import whatsapp as wam          # noqa: E402
from batch import Batcher, Event, batch_to_dict, batch_from_dict, parse_listing  # noqa: E402
import state as st                       # noqa: E402
import bridge_save                       # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa_bridge2")

GRAPH = "https://graph.facebook.com/v22.0"
ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "8090"))

SUPP_TIMEOUT_SEC = 600        # supplement unanswered -> save separately
REMIND_AFTER_SEC = 3600       # confirm card reminder
OUTBOX_BACKOFF = [60, 300, 900]

BOT_TOKEN = ""
try:
    with open(os.path.join(ROOT, "token.txt")) as f:
        BOT_TOKEN = f.read().strip()
except OSError:
    log.warning("token.txt not found; Telegram notifications disabled")

# ------------------------------------------------------------------ send

def _graph_post(payload: dict) -> bool:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        log.warning("WA creds missing; cannot send: %s", str(payload)[:120])
        return False
    req = urllib.request.Request(
        f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        log.warning("graph send failed", exc_info=True)
        return False


def wa_send_text(to: str, body: str, quote_msg_id: str = "") -> bool:
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
               "to": to, "type": "text", "text": {"body": body}}
    if quote_msg_id:
        payload["context"] = {"message_id": quote_msg_id}
    return _graph_post(payload)


def wa_send_reaction(to: str, msg_id: str, emoji: str = "✅") -> bool:
    return _graph_post({
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "reaction",
        "reaction": {"message_id": msg_id, "emoji": emoji}})


def build_interactive_payload(to_phone: str, body: str, buttons: list) -> dict:
    """Cloud API interactive reply-button payload (max 3, title <= 20)."""
    items = [{"type": "reply",
              "reply": {"id": str(bid)[:256], "title": str(title)[:20]}}
             for bid, title in buttons[:3]]
    return {"messaging_product": "whatsapp", "recipient_type": "individual",
            "to": to_phone, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": body},
                            "action": {"buttons": items}}}


def parse_button_reply(msg: dict) -> str | None:
    if (msg or {}).get("type") != "interactive":
        return None
    return (((msg.get("interactive") or {}).get("button_reply") or {})
            .get("id"))


def tg_send(telegram_id: int, text: str):
    if not BOT_TOKEN:
        return
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": telegram_id, "text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        log.warning("telegram notify failed", exc_info=True)


def download_media(media_id: str) -> bytes | None:
    """Two-step Cloud API media download: id -> temp URL -> bytes."""
    if not ACCESS_TOKEN:
        return None
    try:
        req = urllib.request.Request(
            f"{GRAPH}/{media_id}",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            url = json.loads(resp.read())["url"]
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        log.warning("media download failed for %s", media_id, exc_info=True)
        return None

# ------------------------------------------------------------------ engine

_engines: dict[str, Batcher] = {}
_engines_lock = threading.Lock()
_guide_sent: dict[str, float] = {}
_rate: dict[str, list] = {}
RATE_LIMIT = 20          # events per minute per sender
GUIDE_INTERVAL = 3600


def get_engine(sender: str) -> Batcher:
    with _engines_lock:
        eng = _engines.get(sender)
        if eng is None:
            snap = st.load_snapshot(sender)
            eng = Batcher.restore(snap) if snap else Batcher()
            _engines[sender] = eng
        return eng


def persist(sender: str):
    eng = _engines.get(sender)
    if eng is not None:
        st.save_snapshot(sender, eng.snapshot(), time.time())


def _summary_from_parsed(p: dict, n_photos: int, n_other: int) -> str:
    bits = []
    if p.get("bedrooms"):
        bits.append(f"{p['bedrooms']:g}PN" if isinstance(p["bedrooms"], float)
                    else f"{p['bedrooms']}PN")
    if p.get("district"):
        bits.append(p["district"])
    if p.get("price_vnd"):
        v = p["price_vnd"]
        bits.append(f"{v / 1e6:g}tr" if v >= 1_000_000 else f"{v:,}đ")
    head = " ".join(bits) if bits else "Tin mới"
    tail = f" + {n_photos} ảnh" if n_photos else " (chưa có ảnh)"
    if n_other:
        tail += f" (bỏ qua {n_other} file/video — em chỉ nhận ảnh)"
    return head + tail


def batch_summary(b) -> str:
    return _summary_from_parsed(b.parsed, len(b.photos), len(b.others))


def _rate_ok(sender: str) -> bool:
    now = time.time()
    hits = [t for t in _rate.get(sender, []) if now - t < 60]
    if len(hits) >= RATE_LIMIT:
        _rate[sender] = hits
        return False
    hits.append(now)
    _rate[sender] = hits
    return True

# ------------------------------------------------------------------ actions

def _download_batch_photos(b) -> tuple[list, int]:
    """Returns (photo_bytes_list, failed_count)."""
    datas, failed = [], 0
    for mid in b.photos:
        data = download_media(mid)
        if data:
            datas.append(data)
        else:
            failed += 1
    return datas, failed


def _receipt_saved(sender: str, anchor: str, result: dict, summary: str,
                   dl_failed: int):
    lines = [f"✅ Đã lưu vào kho: {summary}"]
    total_photos = result.get("photos_ok", 0) + result.get("photos_failed", 0)
    if result.get("photos_failed") or dl_failed:
        bad = result.get("photos_failed", 0) + dl_failed
        lines.append(f"⚠️ {bad}/{total_photos + dl_failed} ảnh lỗi, chưa lưu được.")
    if result.get("dup_suspect"):
        lines.append(f"ℹ️ Tin này có vẻ trùng với: {result['dup_suspect']}"
                     " — anh/chị vào kho kiểm tra giúp em nhé.")
    if result.get("missing"):
        lines.append("ℹ️ Tin đang ở dạng nháp trong kho, vào bot bổ sung"
                     " thêm thông tin giúp em nhé.")
    wa_send_text(sender, "\n".join(lines), quote_msg_id=anchor)


def do_save(sender: str, tg_id: int, b, via_outbox_row: int = None) -> bool:
    """Download photos + create the draft listing. True = fully handled
    (saved or terminally failed with the broker informed)."""
    datas, dl_failed = _download_batch_photos(b)
    try:
        result = bridge_save.save_bridge_listing(
            tg_id, b.combined_text, datas, photo_keys=list(b.photos),
            source="whatsapp")
    except Exception:
        log.warning("save failed for batch %s", b.batch_id, exc_info=True)
        result = None

    if result is not None and result.get("ok"):
        st.record_listing(sender, b.batch_id, result["listing_id"], time.time())
        if via_outbox_row is not None:
            st.delete_outbox(via_outbox_row)
        _receipt_saved(sender, b.anchor_msg_id, result, batch_summary(b),
                       dl_failed)
        return True

    if result is not None and result.get("error") == "limit":
        if via_outbox_row is not None:
            st.delete_outbox(via_outbox_row)
        wa_send_text(sender,
                     "⚠️ Kho của anh/chị đã đạt giới hạn số tin của gói hiện"
                     " tại. Nâng gói trong bot để lưu thêm nhé.",
                     quote_msg_id=b.anchor_msg_id)
        return True

    # transient failure -> outbox retry (or schedule next retry)
    payload = {"type": "save", "tg_id": tg_id, "batch": batch_to_dict(b)}
    if via_outbox_row is None:
        st.enqueue_outbox(sender, payload, time.time())
        wa_send_text(sender,
                     "⏳ Lưu đang gặp trục trặc, em sẽ tự thử lại và báo"
                     " anh/chị ngay khi xong.",
                     quote_msg_id=b.anchor_msg_id)
    return False


def do_append(sender: str, listing_id: str, b, summary_target: str,
              via_outbox_row: int = None) -> bool:
    datas, dl_failed = _download_batch_photos(b)
    try:
        result = bridge_save.append_photos_to_listing(listing_id, datas)
    except Exception:
        log.warning("append failed for batch %s", b.batch_id, exc_info=True)
        result = None
    if result is not None:
        if via_outbox_row is not None:
            st.delete_outbox(via_outbox_row)
        msg = f"✅ Đã gộp {result['photos_ok']} ảnh vào căn {summary_target}."
        if result["photos_failed"] or dl_failed:
            msg += (f" ({result['photos_failed'] + dl_failed} ảnh lỗi,"
                    " chưa gộp được)")
        wa_send_text(sender, msg, quote_msg_id=b.anchor_msg_id)
        return True
    if via_outbox_row is None:
        st.enqueue_outbox(sender, {"type": "append", "listing_id": listing_id,
                                   "batch": batch_to_dict(b),
                                   "summary_target": summary_target},
                          time.time())
    return False


def _flush_to_card(sender: str, tg_id: int, b):
    st.put_pending(b.batch_id, sender, "save",
                   {"batch": batch_to_dict(b), "tg_id": tg_id}, time.time())
    if b.anchor_msg_id:
        wa_send_reaction(sender, b.anchor_msg_id, "✅")
    wa_send_text(sender, f"Đã nhận: {batch_summary(b)}",
                 quote_msg_id=b.anchor_msg_id)
    _graph_post(build_interactive_payload(
        sender, "Lưu tin này vào kho nhé?",
        [(f"save:{b.batch_id}", "💾 Lưu vào kho"),
         (f"skip:{b.batch_id}", "🗑 Bỏ qua")]))


def handle_actions(sender: str, tg_id: int, actions: list):
    for act in actions:
        kind = act[0]
        if kind == "flush":
            b = act[1]
            if b.reason == "save_kw":      # broker typed LUU: save directly
                do_save(sender, tg_id, b)
            else:
                _flush_to_card(sender, tg_id, b)
        elif kind == "ask_supplement":
            b, prev_id = act[1], act[2]
            target = st.listing_for_batch(sender, prev_id)
            if not target:
                _flush_to_card(sender, tg_id, b)
                continue
            other = None
            try:
                import db as _db
                row = _db.get_listing(target)
                other = bridge_save._summary_of(row) if row else None
            except Exception:
                other = None
            st.put_pending(b.batch_id, sender, "supp",
                           {"batch": batch_to_dict(b), "tg_id": tg_id,
                            "target_listing": target,
                            "target_summary": other or "căn vừa rồi"},
                           time.time())
            wa_send_text(
                sender,
                f"Vừa nhận thêm {len(b.photos)} ảnh. Đây là ảnh của căn"
                f" {other or 'vừa rồi'} phải không ạ?",
                quote_msg_id=b.anchor_msg_id)
            _graph_post(build_interactive_payload(
                sender, "Đợt ảnh này thuộc về?",
                [(f"supp_merge:{b.batch_id}", "📎 Gộp vào căn trên"),
                 (f"supp_new:{b.batch_id}", "🆕 Căn mới")]))
        elif kind == "merge_into":
            b, target_batch = act[1], act[2]
            target = st.listing_for_batch(sender, target_batch)
            if target:
                do_append(sender, target, b, "căn vừa rồi")
            else:
                _flush_to_card(sender, tg_id, b)
        elif kind == "immediate":
            ev = act[1]
            body = (ev.body or "").strip()
            if ev.kind == "text":           # pairing code
                do_pairing(sender, body)
            elif ev.kind == "keyword" and body.upper() == "HUY LINK":
                do_unlink(sender, tg_id)
        # cancel / ignore / ignore_chat / duplicate / retracted: no reply
    persist(sender)

# ------------------------------------------------------------------ pairing

def do_pairing(phone: str, code: str):
    if wam.get_telegram_id_by_phone(phone):
        wa_send_text(phone, "Số này đã liên kết với tài khoản Telegram rồi"
                            " ạ. Anh/chị cứ forward tin vào đây nhé.")
        return
    res = wam.redeem_wa_pairing_code(code, phone)
    if res.get("ok"):
        tg_id = res["telegram_id"]
        wa_send_text(phone, "✅ Liên kết thành công! Từ giờ anh/chị forward"
                            " tin (text + ảnh) vào đây, em sẽ gom thành"
                            " từng đợt và hỏi trước khi lưu vào kho.")
        tg_send(tg_id, f"✅ Đã liên kết WhatsApp ({phone}) với tài khoản"
                       " của anh/chị. Forward tin vào số WhatsApp của"
                       " TrueNest là tin vào kho.")
    elif res.get("error") == "expired":
        wa_send_text(phone, "Mã đã hết hạn (mã chỉ sống 15 phút). Anh/chị"
                            " lấy mã mới trong bot bằng lệnh /linkwhatsapp nhé.")
    else:
        wa_send_text(phone, "Mã chưa đúng ạ. Anh/chị kiểm tra lại mã từ bot"
                            " Telegram (/linkwhatsapp) nhé.")


def do_unlink(phone: str, tg_id: int):
    if wam.unlink_whatsapp(phone):
        wa_send_text(phone, "Đã huỷ liên kết WhatsApp. Tin forward vào đây"
                            " sẽ không vào kho nữa. Muốn liên kết lại, lấy"
                            " mã mới trong bot bằng /linkwhatsapp nhé.")
        tg_send(tg_id, "Đã huỷ liên kết WhatsApp theo yêu cầu của anh/chị.")


def _send_guide(phone: str):
    now = time.time()
    if now - _guide_sent.get(phone, 0) < GUIDE_INTERVAL:
        return
    _guide_sent[phone] = now
    wa_send_text(phone, "Chào anh/chị 👋 Em là Linh, trợ lý TrueNest."
                        " Để forward tin vào kho qua WhatsApp, anh/chị"
                        " liên kết 1 lần trong bot Telegram: mở bot →"
                        " /linkwhatsapp → gửi mã WA-XXXXXX vào đây ạ.")

# ------------------------------------------------------------------ buttons

def handle_button(sender: str, button_id: str):
    phone = wam.normalize_phone(sender)
    tg_id = wam.get_telegram_id_by_phone(phone)
    if tg_id is None or ":" not in button_id:
        return
    action, _, bid = button_id.partition(":")
    try:
        batch_id = int(bid)
    except ValueError:
        return
    pend = st.pop_pending(batch_id)
    if not pend or pend["sender"] != phone:
        return
    payload = pend["payload"]
    b = batch_from_dict(payload["batch"])
    if action == "save" and pend["kind"] == "save":
        do_save(phone, payload["tg_id"], b)
    elif action == "skip" and pend["kind"] == "save":
        wa_send_text(phone, "Đã bỏ qua đợt này ạ.",
                     quote_msg_id=b.anchor_msg_id)
    elif action == "supp_merge" and pend["kind"] == "supp":
        eng = get_engine(phone)
        eng.resolve_supplement(phone, True)
        persist(phone)
        do_append(phone, payload["target_listing"], b,
                  payload.get("target_summary", "căn vừa rồi"))
    elif action == "supp_new" and pend["kind"] == "supp":
        eng = get_engine(phone)
        eng.resolve_supplement(phone, False)
        persist(phone)
        do_save(phone, payload["tg_id"], b)

# ------------------------------------------------------------------ routing

_KEYWORDS = ("HUY LINK", "LUU", "BO")


def route_event(sender_raw: str, ev: Event):
    phone = wam.normalize_phone(sender_raw)
    if not phone or not _rate_ok(phone):
        return
    tg_id = wam.get_telegram_id_by_phone(phone)
    if tg_id is None:
        from batch import is_pairing_code
        if ev.kind == "text" and is_pairing_code(ev.body or ""):
            do_pairing(phone, (ev.body or "").strip().upper())
        else:
            _send_guide(phone)
        return
    body = (ev.body or "").strip()
    if ev.kind == "text" and body.upper() in _KEYWORDS:
        ev = Event(sender=phone, kind="keyword", body=body.upper(),
                   msg_id=ev.msg_id)
    else:
        ev.sender = phone
    eng = get_engine(phone)
    actions = eng.on_event(ev)
    handle_actions(phone, tg_id, actions)


def _extract(event: dict):
    """Split a webhook payload into (intake events, button taps)."""
    events, buttons = [], []
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                sender = msg.get("from", "")
                mid = msg.get("id", "")
                mtype = msg.get("type")
                if mtype == "interactive":
                    bid = parse_button_reply(msg)
                    if bid:
                        buttons.append((sender, bid))
                elif mtype == "text":
                    events.append((sender, Event(
                        sender=sender, kind="text",
                        body=(msg.get("text") or {}).get("body", ""),
                        msg_id=mid)))
                elif mtype in ("image", "video", "audio", "document"):
                    media = msg.get(mtype) or {}
                    events.append((sender, Event(
                        sender=sender, kind=mtype,
                        photo_id=media.get("id", ""),
                        caption=media.get("caption", ""), msg_id=mid)))
                elif mtype == "location":
                    loc = msg.get("location") or {}
                    events.append((sender, Event(
                        sender=sender, kind="location", photo_id=mid,
                        msg_id=mid, meta={"lat": loc.get("latitude"),
                                          "lng": loc.get("longitude")})))
                elif mtype == "contacts":
                    events.append((sender, Event(
                        sender=sender, kind="contact", photo_id=mid,
                        msg_id=mid)))
                elif mtype in ("sticker", "reaction", "unsupported"):
                    events.append((sender, Event(
                        sender=sender, kind="reaction", msg_id=mid)))
    return events, buttons

# ------------------------------------------------------------------ tick

def _tick_once():
    now = time.time()
    for sender, eng in list(_engines.items()):
        tg_id = wam.get_telegram_id_by_phone(sender)
        if tg_id is None:
            continue
        acts = eng.tick()
        if acts:
            handle_actions(sender, tg_id, acts)
    for p in st.list_pending():
        age = now - p["created"]
        if p["kind"] == "supp" and age > SUPP_TIMEOUT_SEC:
            pend = st.pop_pending(p["batch_id"])
            if pend:
                b = batch_from_dict(pend["payload"]["batch"])
                eng = get_engine(p["sender"])
                eng.resolve_supplement(p["sender"], False)
                persist(p["sender"])
                do_save(p["sender"], pend["payload"]["tg_id"], b)
        elif p["kind"] == "save" and age > REMIND_AFTER_SEC \
                and not p["reminded"]:
            b = batch_from_dict(p["payload"]["batch"])
            wa_send_text(p["sender"],
                         "⏰ Tin này vẫn đang chờ anh/chị xác nhận lưu"
                         " vào kho ạ.",
                         quote_msg_id=b.anchor_msg_id)
            st.mark_reminded(p["batch_id"])
    for row in st.due_outbox(now):
        payload = row["payload"]
        b = batch_from_dict(payload["batch"])
        if payload["type"] == "save":
            ok = do_save(row["sender"], payload["tg_id"], b,
                         via_outbox_row=row["id"])
        else:
            ok = do_append(row["sender"], payload["listing_id"], b,
                           payload.get("summary_target", "căn vừa rồi"),
                           via_outbox_row=row["id"])
        if not ok:
            attempts = row["attempts"] + 1
            if attempts > len(OUTBOX_BACKOFF):
                st.delete_outbox(row["id"])
                wa_send_text(row["sender"],
                             "❌ Em không lưu được đợt này sau nhiều lần"
                             " thử. Anh/chị gửi lại giúp em nhé.",
                             quote_msg_id=b.anchor_msg_id)
            else:
                st.update_outbox(row["id"], attempts,
                                 now + OUTBOX_BACKOFF[attempts - 1])


def _tick_loop():
    while True:
        time.sleep(1)
        try:
            _tick_once()
        except Exception:
            log.warning("tick failed", exc_info=True)

# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        if (q.get("hub.mode", [""])[0] == "subscribe"
                and q.get("hub.verify_token", [""])[0] == VERIFY_TOKEN
                and VERIFY_TOKEN):
            body = q.get("hub.challenge", [""])[0].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(403)
            self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/wa-webhook"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            event = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        try:
            events, buttons = _extract(event)
            for sender, ev in events:
                route_event(sender, ev)
            for sender, bid in buttons:
                handle_button(sender, bid)
        except Exception:
            log.warning("webhook handling failed", exc_info=True)


def main():
    wam.init_whatsapp_tables()
    for sender in st.load_all_snapshots():
        get_engine(sender)      # preload open batches after a restart
    threading.Thread(target=_tick_loop, daemon=True).start()
    log.info("wa bridge v2 listening on %s:%d", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
