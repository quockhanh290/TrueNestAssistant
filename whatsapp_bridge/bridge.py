#!/usr/bin/env python3
"""WhatsApp -> Telegram bridge (official WhatsApp Cloud API).

Pattern:
  - Meta POSTs incoming messages to this bridge's /wa-webhook endpoint.
  - This bridge listens to 1:1 DMs ONLY (ignores groups and own messages),
    looks up phone -> telegram_id in the db package, and forwards listing
    messages to the broker's Telegram via the bot API.

Setup: see README.md.

Env:
  WA_ACCESS_TOKEN      Meta Graph API token (long-lived)
  WA_PHONE_NUMBER_ID   the Cloud API phone number id
  WA_VERIFY_TOKEN      our own secret for webhook verification
  BRIDGE_HOST          default 127.0.0.1
  BRIDGE_PORT          default 8090
  BOT_DB_PATH          respected by the db package

Stdlib only.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from db import whatsapp as wam  # noqa: E402

# ---------------------------------------------------------------- config

WA_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
WA_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8090"))
GRAPH = "https://graph.facebook.com/v22.0"


def _read_token() -> str:
    for p in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "token.txt"),
        "token.txt",
    ):
        if os.path.exists(p):
            with open(p) as f:
                t = f.read().strip()
            if t:
                return t
    return ""


BOT_TOKEN = _read_token()

# ---------------------------------------------------------------- helpers

_rate = {}        # phone -> list of timestamps (msg rate limit)
_last_guide = {}  # phone -> ts of last pairing-guide reply (1/hour)
_lock = threading.Lock()


def rate_limited(phone: str, max_per_min: int = 20) -> bool:
    now = time.time()
    with _lock:
        ts = [t for t in _rate.get(phone, []) if now - t < 60]
        if len(ts) >= max_per_min:
            return True
        ts.append(now)
        _rate[phone] = ts
        return False


def guide_throttled(phone: str) -> bool:
    """True if we already sent the pairing guide within the last hour."""
    now = time.time()
    with _lock:
        last = _last_guide.get(phone, 0)
        if now - last < 3600:
            return True
        _last_guide[phone] = now
        return False


def http_post(url: str, data: dict, headers: dict | None = None, timeout: int = 20):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()[:2000]
    except Exception as e:  # noqa: BLE001 - bridge must not die on send errors
        return 0, str(e)[:200]


def wa_send(phone: str, text: str):
    """Reply to a WhatsApp user via the official Cloud API."""
    if not (WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID):
        print("[wa] no Cloud API credentials, skip", flush=True)
        return
    status, body = http_post(
        f"{GRAPH}/{WA_PHONE_NUMBER_ID}/messages",
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        },
        {"Authorization": f"Bearer {WA_ACCESS_TOKEN}"},
    )
    if status != 200:
        print(f"[wa] send failed {status}: {body[:200]}", flush=True)


def tg_send(telegram_id: int, text: str):
    if not BOT_TOKEN:
        print("[tg] no token, skip", flush=True)
        return
    status, body = http_post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        {"chat_id": telegram_id, "text": text, "parse_mode": "HTML"},
    )
    if status != 200:
        print(f"[tg] sendMessage failed {status}: {body[:200]}", flush=True)


# ---------------------------------------------------------------- listing parse (mirrors zalo bridge)

PRICE_RE = re.compile(
    r"(\d[\d.,\s]*)\s*(tỷ|ty|tr|triệu|trieu|million|k)\b", re.IGNORECASE
)
BED_RE = re.compile(r"(\d+)\s*(pn|phòng ngủ|phong ngu|bedrooms?|br)\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(0\d{9})(?!\d)")
DISTRICTS = [
    "Sơn Trà", "Hải Châu", "Ngũ Hành Sơn", "Cẩm Lệ", "Thanh Khê",
    "Liên Chiểu", "An Thượng", "Mỹ Khê", "Non Nước", "Hội An",
]


def parse_listing(text: str) -> dict:
    out = {}
    m = PRICE_RE.search(text or "")
    if m:
        num = float(m.group(1).replace(",", ".").replace(" ", ""))
        unit = m.group(2).lower()
        mult = {"tỷ": 1e9, "ty": 1e9, "tr": 1e6, "triệu": 1e6,
                "trieu": 1e6, "million": 1e6, "k": 1e3}.get(unit, 1)
        out["price_vnd"] = int(num * mult)
    m = BED_RE.search(text or "")
    if m:
        out["bedrooms"] = int(m.group(1))
    m = PHONE_RE.search(text or "")
    if m:
        out["phone_in_text"] = m.group(1)
    for d in DISTRICTS:
        if re.search(re.escape(d), text or "", re.IGNORECASE):
            out["district"] = d
            break
    return out


def is_pairing_code(text: str) -> bool:
    return bool(re.fullmatch(r"WA-[A-Z2-9]{6}", (text or "").strip().upper()))


# ---------------------------------------------------------------- message handling

def handle_message(phone: str, body: str, sender_name: str, has_media: bool):
    phone = wam.normalize_phone(phone)
    if not phone:
        return
    if rate_limited(phone):
        return  # silent drop

    text = (body or "").strip()

    # 1. pairing code redeem
    if is_pairing_code(text):
        res = wam.redeem_wa_pairing_code(text, phone, sender_name)
        if res.get("ok"):
            tg_id = res["telegram_id"]
            wa_send(phone,
                    "✅ Đã liên kết WhatsApp này với Telegram của bạn. "
                    "Từ giờ tin bạn forward sẽ tự về bot Linh.")
            tg_send(tg_id,
                    "✅ <b>WhatsApp đã liên kết</b>\n"
                    f"Số <code>{phone}</code> đã nối với tài khoản này.")
            print(f"[link] {phone} -> tg:{tg_id}", flush=True)
        else:
            err = {"not_found": "mã không đúng",
                   "used": "mã đã dùng rồi",
                   "expired": "mã đã hết hạn (15 phút)"}.get(res.get("error"), "lỗi")
            wa_send(phone,
                    f"❌ {err}. Lấy mã mới bằng lệnh /linkwhatsapp trên Telegram rồi gửi lại.")
        return

    # 2. unlink
    if text.upper() == "HUY LINK":
        ok = wam.unlink_whatsapp(phone)
        wa_send(phone,
                "✅ Đã hủy liên kết WhatsApp này." if ok
                else "Số này chưa liên kết với Telegram nào.")
        print(f"[unlink] {phone} -> {ok}", flush=True)
        return

    # 3. lookup
    tg_id = wam.get_telegram_id_by_phone(phone)
    if not tg_id:
        if guide_throttled(phone):
            return
        wa_send(phone,
                "👋 Đây là số nhận tin của TrueNest.\n\n"
                "Để tin forward tự về Telegram của bạn:\n"
                "1. Mở bot Linh trên Telegram, gửi /linkwhatsapp\n"
                "2. Gửi mã nhận được vào đây\n\n"
                "Sau đó bạn chỉ cần forward tin vào đây là xong.")
        return

    # 4. listing-like message -> parse + forward
    parsed = parse_listing(text)
    lines = [f"📩 <b>Tin từ WhatsApp</b> ({phone})"]
    if parsed.get("price_vnd"):
        lines.append(f"💰 Giá: {parsed['price_vnd']:,}đ".replace(",", "."))
    if parsed.get("bedrooms"):
        lines.append(f"🛏️ {parsed['bedrooms']}PN")
    if parsed.get("district"):
        lines.append(f"📍 {parsed['district']}")
    if parsed.get("phone_in_text"):
        lines.append(f"☎️ Trong tin: {parsed['phone_in_text']}")
    if has_media:
        lines.append("📷 Có ảnh kèm (v1 chưa forward ảnh)")
    preview = text[:300] + ("…" if len(text) > 300 else "")
    lines.append("")
    lines.append(preview)
    tg_send(tg_id, "\n".join(lines))
    print(f"[fwd] {phone} -> tg:{tg_id} ({len(text)} chars)", flush=True)


# ---------------------------------------------------------------- HTTP server

def build_interactive_payload(to_phone: str, body: str, buttons: list) -> dict:
    """Build a WhatsApp Cloud API interactive message payload.

    buttons: list of (button_id, title). Cloud API allows at most 3 reply
    buttons per message; titles are truncated to 20 chars per the spec.
    """
    items = []
    for bid, title in buttons[:3]:
        items.append({
            "type": "reply",
            "reply": {"id": str(bid)[:256], "title": str(title)[:20]},
        })
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": items},
        },
    }


def parse_button_reply(msg: dict) -> str | None:
    """Extract the button id from an inbound interactive webhook message."""
    if (msg or {}).get("type") != "interactive":
        return None
    return (((msg.get("interactive") or {}).get("button_reply") or {})
            .get("id"))


def _extract_messages(event: dict):
    """Yield (phone, body, sender_name, has_media) for inbound user messages."""
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                        for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                # `messages` only carries inbound user messages; our own
                # outbound echoes arrive under `statuses`, never here.
                mtype = msg.get("type", "")
                if mtype == "text":
                    body = (msg.get("text") or {}).get("body", "")
                elif mtype in ("image", "video", "document"):
                    body = (msg.get(mtype) or {}).get("caption", "")
                else:
                    continue  # statuses, reactions, etc.
                phone = msg.get("from", "")
                yield phone, body, contacts.get(phone, ""), mtype != "text"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _reply(self, code: int, body: bytes = b"", ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        # Meta webhook verification
        if self.path.startswith("/wa-webhook"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if (qs.get("hub.mode", [""])[0] == "subscribe"
                    and qs.get("hub.verify_token", [""])[0] == WA_VERIFY_TOKEN
                    and WA_VERIFY_TOKEN):
                self._reply(200, qs["hub.challenge"][0].encode(), "text/plain")
                return
            self._reply(403)
            return
        if self.path == "/health":
            self._reply(200, b'{"ok":true}')
            return
        self._reply(404)

    def do_POST(self):
        if not self.path.startswith("/wa-webhook"):
            self._reply(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            event = json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            self._reply(400)
            return
        self._reply(200, b"ok")
        try:
            for phone, body, name, has_media in _extract_messages(event):
                handle_message(phone, body, name, has_media)
        except Exception as e:  # noqa: BLE001 - bridge must never crash
            print(f"[err] {e}", flush=True)


def main():
    if not BOT_TOKEN:
        print("[warn] token.txt not found — Telegram forwarding disabled", flush=True)
    if not (WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID and WA_VERIFY_TOKEN):
        print("[warn] WA_* env not set — Cloud API disabled (tests still work)", flush=True)
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), Handler)
    print(f"[wa-bridge] listening on {BRIDGE_HOST}:{BRIDGE_PORT}/wa-webhook", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
