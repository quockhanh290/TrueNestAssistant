"""Telegram Web App server for TrueNest broker bot.

Stdlib only — no pip dependencies. Serves the static frontend and a
small JSON API backed by the bot's SQLite database.

Run:
    python webapp/server.py

Env:
    WEBAPP_PORT  — port to listen on (default 8080)
    WEBAPP_HOST  — interface to bind (default 127.0.0.1; cloudflared
                   reaches it via localhost, so the LAN never needs it)
    WEBAPP_URL   — public URL (used by the bot's web_app button)
    BOT_DB_PATH  — SQLite path (default broker_bot.db next to bot.py)
    TELEGRAM_BOT_TOKEN — Telegram bot token, for initData validation
                   (same var as bot.py; BOT_TOKEN accepted as fallback)
    WEBAPP_DEV   — "1" enables ?demo=1&broker_id=X (local testing only)
    INIT_DATA_MAX_AGE — seconds an initData stays valid (default 86400)
    TRUENEST_LOG_DIR — log folder (default <repo>/logs), see db/logsetup.py

Error contract (17/10/2026, for every /api and /s route):
    400 {"error": "bad_json"}              body is not JSON
    400 {"error": "body_must_be_object"}   body is JSON but not an object
    400 {"error": "bad_field", "field": f, "reason": r}
                                           a value cannot be stored (db layer)
    404 {"error": "not_found"}             an id in the path or body belongs to
                                           another broker or does not exist
    500 {"error": "server_error"}          anything else; traceback -> log only
"""
import hashlib
import hmac
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC_DIR = os.path.realpath(os.path.join(HERE, "static"))

sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(1, ROOT)

if __name__ == "__main__":
    # first, before the heavier imports: under pythonw a failing import is
    # otherwise invisible
    from db import logsetup as _logsetup
    _logsetup.setup("webapp")

import logging  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import parse_qsl, urlparse  # noqa: E402

import api  # noqa: E402
import api_clients_deals as api2  # noqa: E402
import share  # noqa: E402
import db  # noqa: E402

log = logging.getLogger("webapp")

PORT = int(os.environ.get("WEBAPP_PORT", "8080"))
HOST = os.environ.get("WEBAPP_HOST", "127.0.0.1")
# start-all.ps1 and bot.py use TELEGRAM_BOT_TOKEN. Reading only BOT_TOKEN
# here left the token empty, so every real initData failed validation.
BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN")
             or os.environ.get("BOT_TOKEN", ""))
DEV_MODE = os.environ.get("WEBAPP_DEV") == "1"
INIT_DATA_MAX_AGE = int(os.environ.get("INIT_DATA_MAX_AGE", "86400"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ico": "image/x-icon",
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
        # Reject replayed initData: a leaked string must not work forever.
        auth_date = int(data.get("auth_date", "0"))
        if not auth_date or time.time() - auth_date > INIT_DATA_MAX_AGE:
            return None
        user = json.loads(data.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        return None


# ---------------------------------------------------------------- errors
class BadRequest(Exception):
    def __init__(self, payload):
        super().__init__(payload.get("error"))
        self.payload = payload


def _obj(body, key):
    """body[key] must be a JSON object (or absent -> {})."""
    v = body.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise db.FieldError(key, "not_an_object")
    return v


# ---------------------------------------------------------------- ownership
# Route parameter kinds that name a broker-owned row (db.owner_of).
OWNED_KINDS = tuple(db.OWNER_TABLES)          # listing, client, viewing, deal, share
# Route parameter kinds that are not owned by the caller (checked by the
# handler itself). A new kind must be added to one of the two lists, or the
# ownership matrix test fails.
UNOWNED_PARAMS = ("feature", "request")
# Body keys that carry an owned id. Every authenticated write is checked for
# all of them, whatever the route does with the body.
OWNED_BODY_KEYS = {
    "listing_id": "listing",
    "listing_ids": "listing",
    "client_id": "client",
    "viewing_id": "viewing",
    "deal_id": "deal",
    "share_token": "share",
}


def check_owned(broker_id, kind, ident):
    """True when `ident` exists and belongs to broker_id."""
    return db.owner_of(kind, ident) == broker_id


def _ownership_ok(route, broker_id, params, body):
    """False -> 404. Path parameters, then body ids."""
    for kind in route.params:
        if kind in OWNED_KINDS and not check_owned(broker_id, kind,
                                                   params[kind]):
            return False
    for key, kind in OWNED_BODY_KEYS.items():
        v = body.get(key)
        if v is None or v == "" or v == []:
            continue
        if key.endswith("_ids"):
            if not isinstance(v, list):
                raise db.FieldError(key, "not_a_list")
            items = v
        else:
            items = [v]
        for ident in items:
            if not isinstance(ident, str):
                raise db.FieldError(key, "not_an_id")
            if not check_owned(broker_id, kind, ident):
                return False
    return True


# ---------------------------------------------------------------- routes
class Route:
    """METHOD + "/api/listing/{listing}" -> fn(req) returning (data, code).

    public=True: no Telegram auth and no ownership layer (share pages for
    clients, health). Everything else is authenticated and every owned id
    (path parameter or body key) is checked before fn runs.
    """

    def __init__(self, method, pattern, fn, public=False, html=False):
        self.method, self.pattern, self.fn = method, pattern, fn
        self.public, self.html = public, html
        self.segs = pattern.strip("/").split("/")
        self.params = [s[1:-1] for s in self.segs if s.startswith("{")]

    def match(self, method, path):
        if method != self.method:
            return None
        parts = path[1:].split("/") if path.startswith("/") else None
        if parts is None or len(parts) != len(self.segs):
            return None
        out = {}
        for seg, part in zip(self.segs, parts):
            if seg.startswith("{"):
                if not part:
                    return None
                out[seg[1:-1]] = part
            elif seg != part:
                return None
        return out

    def __repr__(self):
        return f"<Route {self.method} {self.pattern}>"


class Req:
    def __init__(self, broker, params, query, body):
        self.broker, self.p, self.q, self.body = broker, params, query, body


def _get_listings(r):
    q = r.q
    try:
        limit = min(int(q.get("limit", "50")), 100)
        offset = int(q.get("offset", "0"))
    except ValueError:
        limit, offset = 50, 0

    def _f(name):
        try:
            v = q.get(name)
            return float(v) if v else None
        except ValueError:
            return None
    pf = q.get("pet_friendly")
    ids = [i.strip() for i in q.get("ids", "").split(",") if i.strip()] or None
    return api.get_listings(
        r.broker, q=q.get("q"), bedrooms=q.get("bedrooms"),
        status=q.get("status"), limit=limit, offset=offset,
        min_price=_f("min_price"), max_price=_f("max_price"),
        min_score=_f("min_score"), district=q.get("district"),
        furnishing=q.get("furnishing"),
        pet_friendly=(pf == "true" if pf else None),
        min_area=_f("min_area"),
        property_type=q.get("property_type"),
        ids=ids)


ROUTES = [
    # ---- public
    Route("GET", "/api/health", lambda r: ({"ok": True}, 200), public=True),
    Route("GET", "/s/{token}", lambda r: share.render_share_page(r.p["token"]),
          public=True, html=True),
    Route("POST", "/s/{token}/book",
          lambda r: share.handle_booking(r.p["token"], r.body), public=True),
    Route("POST", "/s/{token}/report",
          lambda r: share.handle_report(r.p["token"], r.body), public=True),
    # ---- listings
    Route("GET", "/api/listings", _get_listings),
    Route("GET", "/api/listing/{listing}",
          lambda r: api.get_listing(r.broker, r.p["listing"])),
    Route("PUT", "/api/listing/{listing}",
          lambda r: api.update_listing(r.broker, r.p["listing"],
                                       _obj(r.body, "fields"))),
    Route("PUT", "/api/listing/{listing}/status",
          lambda r: api.set_status(r.broker, r.p["listing"],
                                   r.body.get("status"))),
    Route("POST", "/api/listing/{listing}/refresh",
          lambda r: api.refresh_listing(r.broker, r.p["listing"],
                                        r.body.get("status"))),
    Route("GET", "/api/post/{listing}",
          lambda r: api.get_post(r.broker, r.p["listing"],
                                 lang=r.q.get("lang", "vi"))),
    Route("PUT", "/api/post/{listing}",
          lambda r: api.put_post(r.broker, r.p["listing"],
                                 r.body.get("lang", "vi"),
                                 r.body.get("text", ""))),
    # ---- trials, shares, propose
    Route("GET", "/api/trial/{feature}",
          lambda r: api.get_trial(r.broker, r.p["feature"])),
    Route("POST", "/api/trial/{feature}/use",
          lambda r: api.use_trial(r.broker, r.p["feature"])),
    Route("GET", "/api/shares", lambda r: api.list_shares(r.broker)),
    Route("POST", "/api/share",
          lambda r: api.create_share(r.broker, r.body.get("listing_ids"),
                                     title=r.body.get("title", ""),
                                     client_id=r.body.get("client_id"))),
    Route("GET", "/api/admin/reports",
          lambda r: api.admin_list_reports(r.broker)),
    Route("GET", "/api/propose/{request}",
          lambda r: api.get_propose(r.broker, r.p["request"])),
    Route("POST", "/api/propose/{request}",
          lambda r: api.submit_propose(r.broker, r.p["request"],
                                       r.body.get("listing_ids"))),
    Route("GET", "/api/xbroker", lambda r: api.get_xbroker_requests(r.broker)),
    Route("GET", "/api/today", lambda r: api.get_today(r.broker)),
    # ---- clients, viewings, deals, profile
    Route("GET", "/api/clients",
          lambda r: api2.list_clients_api(r.broker, status=r.q.get("status"))),
    Route("POST", "/api/clients",
          lambda r: api2.create_client_api(r.broker, r.body)),
    Route("GET", "/api/client/{client}",
          lambda r: api2.get_client_api(r.broker, r.p["client"])),
    Route("PUT", "/api/client/{client}",
          lambda r: api2.update_client_api(r.broker, r.p["client"],
                                           _obj(r.body, "fields"))),
    Route("POST", "/api/client/{client}/notes",
          lambda r: api2.add_client_note_api(r.broker, r.p["client"],
                                             r.body.get("note"))),
    Route("GET", "/api/viewings", lambda r: api2.list_viewings_api(r.broker)),
    Route("POST", "/api/viewings",
          lambda r: api2.create_viewing_api(r.broker, r.body)),
    Route("GET", "/api/deals",
          lambda r: api2.list_deals_api(r.broker, month=r.q.get("month"))),
    Route("POST", "/api/deals", lambda r: api2.create_deal_api(r.broker, r.body)),
    Route("GET", "/api/profile", lambda r: api2.get_profile_api(r.broker)),
    Route("PUT", "/api/profile",
          lambda r: api2.update_profile_api(r.broker, _obj(r.body, "fields"))),
    Route("GET", "/api/notify/prefs",
          lambda r: api2.get_notify_prefs_api(r.broker)),
    Route("PUT", "/api/notify/prefs",
          lambda r: api2.set_notify_pref_api(r.broker, r.body.get("pref"),
                                             r.body.get("enabled"))),
    Route("GET", "/api/referral", lambda r: api2.get_referral_api(r.broker)),
    Route("POST", "/api/premium/request",
          lambda r: api2.request_premium_api(r.broker, r.body.get("tier"))),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "TrueNestWebApp/0.1"

    # -- helpers ------------------------------------------------------
    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self._headers_sent = True
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
        """The request body as a dict. Empty body -> {}. Not JSON, or JSON
        that is not an object -> BadRequest (400). Before 17/10 a bad body
        became {} silently and an array crashed the handler."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            raise BadRequest({"error": "bad_json"}) from None
        if not isinstance(data, dict):
            raise BadRequest({"error": "body_must_be_object"})
        return data

    def _auth(self, query):
        """Return broker_id or None. Demo mode (WEBAPP_DEV=1 only) bypasses
        Telegram auth; otherwise a valid signed initData is required."""
        if DEV_MODE and query.get("demo") == "1":
            try:
                return int(query.get("broker_id", "0")) or None
            except ValueError:
                return None
        # Accept init_data from query param (base64, Mini App) or header (legacy)
        init_data = ""
        b64 = query.get("init_data_b64", "")
        if b64:
            try:
                import base64
                # base64url -> standard base64
                b64 = b64.replace("-", "+").replace("_", "/")
                b64 += "=" * (-len(b64) % 4)
                init_data = base64.b64decode(b64).decode("utf-8", "replace")
            except Exception:
                pass
        if not init_data:
            init_data = query.get("init_data", "") or self.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(init_data, BOT_TOKEN)
        if user:
            return user["id"]
        return None

    # -- routing ------------------------------------------------------
    def do_OPTIONS(self):
        self._send(200, b"")

    def do_GET(self):
        self._guarded("GET")

    def do_PUT(self):
        self._guarded("PUT")

    def do_POST(self):
        self._guarded("POST")

    def _guarded(self, method):
        """Every request goes through here: one place turns an exception
        into JSON 500 (traceback to the log, never to the client)."""
        self._headers_sent = False
        try:
            self._handle(method)
        except BadRequest as e:
            self._json(400, e.payload)
        except db.FieldError as e:
            self._json(400, {"error": "bad_field", "field": e.field,
                             "reason": e.reason})
        except Exception:
            log.exception("%s %s failed", method, urlparse(self.path).path)
            if not self._headers_sent:
                try:
                    self._json(500, {"error": "server_error"})
                except Exception:
                    pass

    def _handle(self, method):
        parsed = urlparse(self.path)
        query = dict(parse_qsl(parsed.query))
        path = parsed.path

        if method == "GET":
            if path == "/":
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            # V2 Stitch UI (Khanh 2026-10-16) — new design system
            # Every /v2/... path serves the SPA entry page (client-side
            # router), unless it names a real file under static/v2/.
            if path == "/v2" or path.startswith("/v2/"):
                return self._v2(path[len("/v2"):])

        for route in ROUTES:
            params = route.match(method, path)
            if params is None:
                continue
            body = self._body() if method in ("PUT", "POST") else {}
            if route.public:
                broker_id = None
            else:
                broker_id = self._auth(query)
                if not broker_id:
                    return self._json(401, {"error": "unauthorized"})
                if not _ownership_ok(route, broker_id, params, body):
                    return self._json(404, {"error": "not_found"})
            data, code = route.fn(Req(broker_id, params, query, body))
            if route.html:
                return self._send(code, data, "text/html; charset=utf-8")
            return self._json(code, data)

        if path.startswith("/api/"):
            # unknown API path: auth first, as before (401 beats 404)
            if not self._auth(query):
                return self._json(401, {"error": "unauthorized"})
        return self._json(404, {"error": "not_found"})

    # -- static -------------------------------------------------------
    @staticmethod
    def _resolve(name):
        """(full_path, inside_static). Resolve AFTER joining: normpath on the
        bare name kept a leading "..", and the joined "static/../.." string
        still passed the prefix check, serving token.txt and broker_bot.db."""
        full = os.path.realpath(os.path.join(STATIC_DIR, name.lstrip("/\\")))
        try:
            inside = os.path.commonpath([full, STATIC_DIR]) == STATIC_DIR
        except ValueError:  # another drive, e.g. "C:/..."
            inside = False
        return full, inside

    def _v2(self, rest):
        full, inside = self._resolve("v2/" + rest.lstrip("/"))
        if not inside:
            return self._json(404, {"error": "not_found"})
        if os.path.isfile(full):
            return self._static("v2/" + rest.lstrip("/"))
        return self._static("v2/index.html")

    def _static(self, name):
        full, inside = self._resolve(name)
        if not inside or not os.path.isfile(full):
            return self._json(404, {"error": "not_found"})
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    # -- access log: path only. The query string can carry initData.
    def log_request(self, code="-", size="-"):
        logging.getLogger("webapp.access").info(
            "%s %s %s", self.command, urlparse(self.path).path, code)

    def log_message(self, fmt, *args):
        logging.getLogger("webapp.access").warning(
            "%s - %s", self.address_string(), fmt % args)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port, which
    # is how two webapp copies ended up sharing 8080. Without it the second
    # copy fails to bind, so only one instance can run.
    allow_reuse_address = os.name != "nt"

    def handle_error(self, request, client_address):
        # socketserver would print to sys.stderr (None under pythonw)
        log.exception("request from %s failed outside the handler",
                      client_address[0])


def main():
    if not BOT_TOKEN and not DEV_MODE:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (or WEBAPP_DEV=1 for local "
                         "demo) — without it no Telegram login can validate.")
    srv = Server((HOST, PORT), Handler)
    log.info("TrueNest webapp on http://localhost:%s%s", PORT,
             "  (dev: demo mode on)" if DEV_MODE else "")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        _logsetup.log_system_exit("webapp", e)
        raise
