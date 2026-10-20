#!/usr/bin/env python3
"""WhatsApp -> Telegram bridge (WAHA inbound).

Pattern mirrors the Zalo bridge:
  - WAHA (Docker) keeps the WhatsApp session and POSTs incoming messages
    to this bridge's /waha-webhook endpoint.
  - This bridge listens to 1:1 DMs ONLY (ignores groups and own messages),
    looks up phone -> telegram_id in the db package, and forwards listing
    messages to the broker's Telegram via the bot API.

Setup: see README.md.

Env:
  WAHA_API_URL   default http://localhost:3000
  WAHA_API_KEY   optional (X-Api-Key for WAHA)
  WAHA_SESSION   default "default"
  BRIDGE_HOST    default 127.0.0.1
  BRIDGE_PORT    default 8090
  BOT_DB_PATH    respected by the db package

Stdlib only.
"""
import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from db import whatsapp as wam  # noqa: E402

# ---------------------------------------------------------------- config

WAHA_API_URL = os.environ.get("WAHA_API_URL", "http://localhost:3000").rstrip("/")
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")
WAHA_SESSION = os.environ.get("WAHA_SESSION", "default")
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8090"))


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


def wa_send(chat_id: str, text: str):
    """Reply to a WhatsApp chat via WAHA."""
    url = f"{WAHA_API_URL}/api/sendText"
    headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}
    status, body = http_post(
        url,
        {"session": WAHA_SESSION, "chatId": chat_id, "text": text},
        headers,
    )
    if status != 201 and status != 200:
        print(f"[wa] sendText failed {status}: {body[:200]}", flush=True)


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

def handle_message(chat_id: str, raw_from: str, body: str, sender_name: str,
                   has_media: bool):
    phone = wam.normalize_phone(raw_from)
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
            wa_send(chat_id,
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
            wa_send(chat_id,
                    f"❌ {err}. Lấy mã mới bằng lệnh /linkwhatsapp trên Telegram rồi gửi lại.")
        return

    # 2. unlink
    if text.upper() == "HUY LINK":
        ok = wam.unlink_whatsapp(phone)
        wa_send(chat_id,
                "✅ Đã hủy liên kết WhatsApp này." if ok
                else "Số này chưa liên kết với Telegram nào.")
        print(f"[unlink] {phone} -> {ok}", flush=True)
        return

    # 3. lookup
    tg_id = wam.get_telegram_id_by_phone(phone)
    if not tg_id:
        if guide_throttled(phone):
            return
        wa_send(chat_id,
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

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/waha-webhook":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            event = json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

        try:
            if event.get("event") != "message":
                return
            p = event.get("payload") or {}
            if p.get("fromMe"):
                return
            chat_id = p.get("from") or ""
            # 1:1 DMs only — ignore groups (@g.us), channels, status
            if not chat_id.endswith("@c.us"):
                return
            handle_message(
                chat_id=chat_id,
                raw_from=chat_id,
                body=p.get("body") or "",
                sender_name=p.get("notifyName") or p.get("pushName") or "",
                has_media=bool(p.get("hasMedia")),
            )
        except Exception as e:  # noqa: BLE001 - bridge must never crash
            print(f"[err] {e}", flush=True)


def main():
    if not BOT_TOKEN:
        print("[warn] token.txt not found — Telegram forwarding disabled", flush=True)
    server = HTTPServer((BRIDGE_HOST, BRIDGE_PORT), Handler)
    print(f"[wa-bridge] listening on {BRIDGE_HOST}:{BRIDGE_PORT}/waha-webhook", flush=True)
    print(f"[wa-bridge] WAHA at {WAHA_API_URL} session={WAHA_SESSION}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
