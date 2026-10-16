"""Telegram Web App server for TrueNest broker bot.

Stdlib only — no pip dependencies. Serves the static frontend and a
small JSON API backed by the bot's SQLite database.

Run:
    python webapp/server.py

Env:
    WEBAPP_PORT  — port to listen on (default 8080)
    WEBAPP_URL   — public URL (used by the bot's web_app button)
    BOT_DB_PATH  — SQLite path (default broker_bot.db next to bot.py)
    BOT_TOKEN    — Telegram bot token, for initData validation
"""
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")

sys.path.insert(0, HERE)
import api  # noqa: E402
import api_clients_deals as api2  # noqa: E402
import share  # noqa: E402

PORT = int(os.environ.get("WEBAPP_PORT", "8080"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def validate_init_data(init_data, bot_token):
    """Validate Telegram WebApp initData. Returns user dict or None.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received = data.pop("hash", None)
        if not received:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(),
                          hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        user = json.loads(data.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TrueNestWebApp/0.1"

    # -- helpers ------------------------------------------------------
    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Telegram WebApp origins
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Telegram-Init-Data")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, obj)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    def _auth(self, query):
        """Return broker_id or None. Demo mode bypasses Telegram auth."""
        if query.get("demo") == "1":
            try:
                return int(query.get("broker_id", "0")) or None
            except ValueError:
                return None
        # Accept init_data from query param (Mini App) or header (legacy)
        init_data = query.get("init_data", "") or self.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(init_data, BOT_TOKEN)
        return user["id"] if user else None

    # -- routing ------------------------------------------------------
    def do_OPTIONS(self):
        self._send(200, b"")

    def do_GET(self):
        parsed = urlparse(self.path)
        query = dict(parse_qsl(parsed.query))
        path = parsed.path

        if path == "/":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        # V2 Stitch UI (Khanh 2026-10-16) — new design system
        if path == "/v2/" or path == "/v2":
            return self._static("v2/listings.html")
        if path == "/api/health":
            return self._json(200, {"ok": True})

        # Public share pages — no auth (client-facing, outside Telegram).
        if path.startswith("/s/"):
            token = path[len("/s/"):].split("/")[0]
            if token and path.rstrip("/") == f"/s/{token}":
                html_body, code = share.render_share_page(token)
                return self._send(code, html_body,
                                  "text/html; charset=utf-8")
            return self._json(404, {"error": "not_found"})

        if path.startswith("/api/"):
            broker_id = self._auth(query)
            if not broker_id:
                return self._json(401, {"error": "unauthorized"})
            return self._api_get(broker_id, path[len("/api/"):], query)

        return self._json(404, {"error": "not_found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        query = dict(parse_qsl(parsed.query))
        path = parsed.path
        if not path.startswith("/api/"):
            return self._json(404, {"error": "not_found"})
        broker_id = self._auth(query)
        if not broker_id:
            return self._json(401, {"error": "unauthorized"})
        body = self._body()
        return self._api_put(broker_id, path[len("/api/"):], query, body)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = dict(parse_qsl(parsed.query))
        path = parsed.path
        # Public share-page booking — no auth.
        if path.startswith("/s/"):
            rest = path[len("/s/"):]
            if "/" in rest:
                token, action = rest.split("/", 1)
                if token and action == "book":
                    data, code = share.handle_booking(token, self._body())
                    return self._json(code, data)
                if token and action == "report":
                    data, code = share.handle_report(token, self._body())
                    return self._json(code, data)
            return self._json(404, {"error": "not_found"})
        if not path.startswith("/api/"):
            return self._json(404, {"error": "not_found"})
        broker_id = self._auth(query)
        if not broker_id:
            return self._json(401, {"error": "unauthorized"})
        body = self._body()
        return self._api_post(broker_id, path[len("/api/"):], query, body)

    # -- static -------------------------------------------------------
    def _static(self, name):
        safe = os.path.normpath(name).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._json(404, {"error": "not_found"})
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    # -- api ----------------------------------------------------------
    def _api_get(self, broker_id, rest, query):
        parts = rest.split("/")
        if parts[0] == "listings" and len(parts) == 1:
            try:
                limit = min(int(query.get("limit", "50")), 100)
                offset = int(query.get("offset", "0"))
            except ValueError:
                limit, offset = 50, 0
            def _f(name):
                try:
                    v = query.get(name)
                    return float(v) if v else None
                except ValueError:
                    return None
            pf = query.get("pet_friendly")
            ids_raw = query.get("ids", "")
            ids = [i.strip() for i in ids_raw.split(",") if i.strip()] or None
            data, code = api.get_listings(
                broker_id, q=query.get("q"), bedrooms=query.get("bedrooms"),
                status=query.get("status"), limit=limit, offset=offset,
                min_price=_f("min_price"), max_price=_f("max_price"),
                min_score=_f("min_score"), district=query.get("district"),
                furnishing=query.get("furnishing"),
                pet_friendly=(pf == "true" if pf else None),
                min_area=_f("min_area"),
                property_type=query.get("property_type"),
                ids=ids)
            return self._json(code, data)
        if parts[0] == "listing" and len(parts) == 2:
            data, code = api.get_listing(broker_id, parts[1])
            return self._json(code, data)
        if parts[0] == "post" and len(parts) == 2:
            data, code = api.get_post(broker_id, parts[1],
                                      lang=query.get("lang", "vi"))
            return self._json(code, data)
        if parts[0] == "trial" and len(parts) == 2:
            data, code = api.get_trial(broker_id, parts[1])
            return self._json(code, data)
        if parts[0] == "shares" and len(parts) == 1:
            data, code = api.list_shares(broker_id)
            return self._json(code, data)
        if parts[0] == "admin" and len(parts) == 2 and parts[1] == "reports":
            data, code = api.admin_list_reports(broker_id)
            return self._json(code, data)
        if parts[0] == "propose" and len(parts) == 2:
            data, code = api.get_propose(broker_id, parts[1])
            return self._json(code, data)
        if parts[0] == "xbroker" and len(parts) == 1:
            data, code = api.get_xbroker_requests(broker_id)
            return self._json(code, data)
        # ---- clients / deals / profile (api_clients_deals) ----
        if parts[0] == "clients" and len(parts) == 1:
            data, code = api2.list_clients_api(
                broker_id, status=query.get("status"))
            return self._json(code, data)
        if parts[0] == "client" and len(parts) == 2:
            data, code = api2.get_client_api(broker_id, parts[1])
            return self._json(code, data)
        if parts[0] == "viewings" and len(parts) == 1:
            data, code = api2.list_viewings_api(broker_id)
            return self._json(code, data)
        if parts[0] == "deals" and len(parts) == 1:
            data, code = api2.list_deals_api(
                broker_id, month=query.get("month"))
            return self._json(code, data)
        if parts[0] == "profile" and len(parts) == 1:
            data, code = api2.get_profile_api(broker_id)
            return self._json(code, data)
        if parts[0] == "notify" and len(parts) == 2 and parts[1] == "prefs":
            data, code = api2.get_notify_prefs_api(broker_id)
            return self._json(code, data)
        if parts[0] == "referral" and len(parts) == 1:
            data, code = api2.get_referral_api(broker_id)
            return self._json(code, data)
        return self._json(404, {"error": "not_found"})

    def _api_put(self, broker_id, rest, query, body):
        parts = rest.split("/")
        if parts[0] == "listing" and len(parts) == 2:
            data, code = api.update_listing(broker_id, parts[1],
                                            body.get("fields"))
            return self._json(code, data)
        if parts[0] == "listing" and len(parts) == 3 and parts[2] == "status":
            data, code = api.set_status(broker_id, parts[1],
                                        body.get("status"))
            return self._json(code, data)
        if parts[0] == "post" and len(parts) == 2:
            data, code = api.put_post(broker_id, parts[1],
                                      body.get("lang", "vi"),
                                      body.get("text", ""))
            return self._json(code, data)
        if parts[0] == "client" and len(parts) == 2:
            data, code = api2.update_client_api(
                broker_id, parts[1], body.get("fields"))
            return self._json(code, data)
        if parts[0] == "profile" and len(parts) == 1:
            data, code = api2.update_profile_api(
                broker_id, body.get("fields"))
            return self._json(code, data)
        if parts[0] == "notify" and len(parts) == 2 and parts[1] == "prefs":
            data, code = api2.set_notify_pref_api(
                broker_id, body.get("pref"), body.get("enabled"))
            return self._json(code, data)
        return self._json(404, {"error": "not_found"})

    def _api_post(self, broker_id, rest, query, body):
        parts = rest.split("/")
        if parts[0] == "trial" and len(parts) == 3 and parts[2] == "use":
            data, code = api.use_trial(broker_id, parts[1])
            return self._json(code, data)
        if parts[0] == "share" and len(parts) == 1:
            data, code = api.create_share(
                broker_id,
                body.get("listing_ids"),
                title=body.get("title", ""),
                client_id=body.get("client_id"),
            )
            return self._json(code, data)
        if parts[0] == "propose" and len(parts) == 2:
            data, code = api.submit_propose(broker_id, parts[1],
                                            body.get("listing_ids"))
            return self._json(code, data)
        if parts[0] == "listing" and len(parts) == 3 and parts[2] == "refresh":
            data, code = api.refresh_listing(broker_id, parts[1],
                                             body.get("status"))
            return self._json(code, data)
        if parts[0] == "clients" and len(parts) == 1:
            data, code = api2.create_client_api(broker_id, body)
            return self._json(code, data)
        if parts[0] == "client" and len(parts) == 3 and parts[2] == "notes":
            data, code = api2.add_client_note_api(
                broker_id, parts[1], body.get("note"))
            return self._json(code, data)
        if parts[0] == "viewings" and len(parts) == 1:
            data, code = api2.create_viewing_api(broker_id, body)
            return self._json(code, data)
        if parts[0] == "deals" and len(parts) == 1:
            data, code = api2.create_deal_api(broker_id, body)
            return self._json(code, data)
        if parts[0] == "premium" and len(parts) == 2 and parts[1] == "request":
            data, code = api2.request_premium_api(
                broker_id, body.get("tier"))
            return self._json(code, data)
        return self._json(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"TrueNest webapp on http://localhost:{PORT}  (demo: ?demo=1&broker_id=<id>)",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
