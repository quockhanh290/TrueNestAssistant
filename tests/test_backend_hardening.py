"""Back end hardening before the new mini app talks to the API (17/10/2026).

Six behaviours, each pinned through the path production actually runs:

1. Any exception in a webapp handler answers JSON 500 (no traceback to the
   client); a body that is not a JSON object answers 400. Over real HTTP.
2. Bot and webapp started with pythonw (sys.stderr/stdout = None) write a
   rotating log file in logs/, including tracebacks nobody caught.
3. One ownership layer for every route that takes an id (listing, client,
   viewing, deal, share page): broker B using broker A's id gets 404 and the
   DB does not change. The matrix is generated from the server's ROUTES list,
   so a route added later is checked without editing this file.
4. The db layer checks/coerces numbers, times, lists, statuses and booleans;
   SQLite triggers refuse non-numeric values in time/number columns.
5. A trial use is consumed by one conditional UPDATE: 12 parallel calls ->
   exactly 3 succeed.
6. "Confirmed available" (confirmed_at) is separate from "row changed"
   (updated_at); every freshness reader uses confirmed_at.

Every test runs on a fresh temp DB. No network, no real Telegram.
Run:  python -m pytest tests/test_backend_hardening.py -q
"""
import asyncio
import http.client
import json
import io
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, ROOT)
sys.path.insert(0, WEBAPP)

# config reads BOT_DB_PATH once at import; let test_flows pick it, as the other suites do,
# so a whole-suite run shares one temp DB that every suite's setUp resets.
import test_flows  # noqa: E402,F401  (sets BOT_DB_PATH, imports bot)

import config  # noqa: E402
import db  # noqa: E402
import server  # noqa: E402  (webapp/server.py)
import api  # noqa: E402  (webapp/api.py)

A, B = 111001, 222002
DAY = 86400
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")


# ---------------------------------------------------------------- harness
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def snapshot(path):
    """Every row of every table — "the DB did not change" means this is
    equal before and after."""
    c = sqlite3.connect(path)
    try:
        out = {}
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"
                              " AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            out[t] = c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
        return out
    finally:
        c.close()


class DBCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_hard_")
        self.path = os.path.join(self.tmp, "t.db")
        self._p_db = patch.object(config, "DB_PATH", self.path)
        self._p_db.start()
        db.init_db()

    def tearDown(self):
        self._p_db.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self):
        return sqlite3.connect(self.path)

    def world(self):
        """Broker A and broker B, each owning one of every id kind."""
        ids = {}
        for uid in (A, B):
            db.get_or_create_broker(uid, f"u{uid}", f"Broker {uid}")
            lid = db.create_listing(
                uid, raw_text="2PN", status="submitted",
                parsed={"price_vnd": 10_000_000, "bedrooms": 2,
                        "district": "Sơn Trà"})
            cid = db.create_client(uid, name="Khach",
                                   requirements={"max_price": 12_000_000})
            vid = db.create_viewing(uid, client_id=cid, listing_ids=[lid],
                                    scheduled_at=time.time() + 3600)
            did = db.create_deal(uid, client_id=cid, listing_id=lid,
                                 commission_vnd=5_000_000)
            tok = db.create_share_page(uid, [lid], client_id=cid)
            ids[uid] = {"listing": lid, "client": cid, "viewing": vid,
                        "deal": did, "share": tok}
        return ids


class HTTPCase(DBCase):
    def setUp(self):
        super().setUp()
        self._p_dev = patch.object(server, "DEV_MODE", True)
        self._p_dev.start()
        self.srv = server.Server(("127.0.0.1", 0), server.Handler)
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._p_dev.stop()
        super().tearDown()

    def req(self, method, path, body=None, broker=A, raw=None, auth=True):
        """(status, parsed JSON or text). status 'CLOSED' when the server
        dropped the connection without answering."""
        if auth:
            path += ("&" if "?" in path else "?") + f"demo=1&broker_id={broker}"
        data = raw if raw is not None else (
            None if body is None else json.dumps(body).encode())
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(method, path, body=data,
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            txt = r.read().decode("utf-8", "replace")
        except (http.client.RemoteDisconnected, ConnectionError) as e:
            return "CLOSED", type(e).__name__
        finally:
            conn.close()
        try:
            return r.status, json.loads(txt)
        except ValueError:
            return r.status, txt


# ================================================== 1. JSON 500 / 400 bodies
class TestHttpErrorsAreJson(HTTPCase):
    def test_handler_exception_answers_json_500_without_traceback(self):
        with patch.object(api, "get_today",
                          side_effect=RuntimeError("boom-secret-detail")):
            with self.assertLogs("webapp", level="ERROR") as logs:
                status, body = self.req("GET", "/api/today")
        self.assertEqual(status, 500, body)
        self.assertEqual(body, {"error": "server_error"})
        self.assertNotIn("boom-secret-detail", json.dumps(body))
        joined = "\n".join(logs.output)
        self.assertIn("boom-secret-detail", joined, "traceback goes to the log")
        self.assertIn("/api/today", joined)
        self.assertNotIn("broker_id=", joined, "query string is not logged")

    def test_exception_in_a_write_route_also_answers_500(self):
        with patch.object(server.api2, "create_client_api",
                          side_effect=KeyError("x")):
            with self.assertLogs("webapp", level="ERROR"):
                status, body = self.req("POST", "/api/clients", {"name": "a"})
        self.assertEqual((status, body), (500, {"error": "server_error"}))

    def test_array_body_answers_400(self):
        for method, path, body in (("PUT", "/api/profile", []),
                                   ("POST", "/api/viewings", [1, 2]),
                                   ("PUT", "/api/client/cli:x", [])):
            status, data = self.req(method, path, body)
            self.assertEqual(status, 400, (method, path, data))
            self.assertEqual(data.get("error"), "body_must_be_object")

    def test_body_that_is_not_json_answers_400(self):
        status, data = self.req("PUT", "/api/profile", raw=b"not json{")
        self.assertEqual((status, data.get("error") if isinstance(data, dict)
                          else data), (400, "bad_json"))

    def test_fields_must_be_an_object(self):
        ids = self.world()
        status, data = self.req("PUT", f"/api/listing/{ids[A]['listing']}",
                                {"fields": "x"})
        self.assertEqual(status, 400, data)
        self.assertEqual(data.get("error"), "bad_field")
        self.assertEqual(data.get("field"), "fields")

    def test_public_share_booking_with_array_body_answers_400(self):
        ids = self.world()
        status, data = self.req("POST", f"/s/{ids[A]['share']}/book", [],
                                auth=False)
        self.assertEqual(status, 400, data)

    def test_empty_body_is_still_an_empty_object(self):
        status, data = self.req("POST", "/api/trial/send2client/use")
        self.assertEqual(status, 200, data)


# ================================================== 2. file logging
def _logsetup_module():
    from db import logsetup
    return logsetup


class _LogCase(unittest.TestCase):
    """Saves and restores what logsetup.setup() changes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_log_")
        self.saved = (sys.stdout, sys.stderr, sys.excepthook,
                      threading.excepthook)
        import logging
        self.root = logging.getLogger()
        self.saved_handlers = list(self.root.handlers)

    def tearDown(self):
        import logging
        (sys.stdout, sys.stderr, sys.excepthook,
         threading.excepthook) = self.saved
        for h in list(self.root.handlers):
            if h not in self.saved_handlers:
                self.root.removeHandler(h)
                h.close()
        logging.getLogger().setLevel(logging.WARNING)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestLogSetupInProcess(_LogCase):
    """The helper itself, driven in-process so it can be mutated."""

    def _run(self):
        ls = _logsetup_module()
        sys.stdout = sys.stderr = None          # what pythonw gives us
        path = ls.setup("probe", log_dir=self.tmp)
        try:
            raise ValueError("never-caught-123")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        print("printed-under-pythonw")
        for h in self.root.handlers:
            h.flush()
        with open(path, encoding="utf-8") as f:
            return path, f.read()

    def test_uncaught_traceback_and_prints_reach_the_file(self):
        path, text = self._run()
        self.assertTrue(path.startswith(self.tmp))
        self.assertIn("never-caught-123", text)
        self.assertIn("Traceback", text)
        self.assertIn("printed-under-pythonw", text)

    def test_uncaught_traceback_reaches_the_file_from_a_console_too(self):
        # python bot.py in a terminal: stderr is real, so it is not routed to
        # the log; only the installed excepthook puts the crash in the file
        ls = _logsetup_module()
        sys.stdout = sys.stderr = io.StringIO()
        path = ls.setup("console", log_dir=self.tmp)
        try:
            raise ValueError("console-crash-456")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        t = threading.Thread(target=lambda: 1 / 0, name="worker-x")
        t.start()
        t.join()
        for h in self.root.handlers:
            h.flush()
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("console-crash-456", text)
        self.assertIn("ZeroDivisionError", text)

    def test_file_rotates_by_size(self):
        import logging.handlers
        ls = _logsetup_module()
        ls.setup("rot", log_dir=self.tmp)
        fh = [h for h in self.root.handlers
              if isinstance(h, logging.handlers.RotatingFileHandler)]
        self.assertTrue(fh, "a rotating file handler is installed")
        self.assertGreater(fh[0].maxBytes, 0)
        self.assertGreater(fh[0].backupCount, 0)


FAKE_TOKEN = "123456789:AAFakeToken_for-tests_0123456789abcd"
OTHER_TOKEN = "987654321:BBanother-fake_Token_xyz"


class TestLogFileHidesBotToken(_LogCase):
    """httpx logs every Bot API URL at INFO, and the URL holds the bot token
    (https://api.telegram.org/bot<TOKEN>/getUpdates). Once logs go to a file
    the token would sit on disk. Fake tokens only; token.txt is never read."""

    def _logged_text(self, name):
        import logging
        ls = _logsetup_module()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}):
            sys.stdout = sys.stderr = None
            path = ls.setup(name, log_dir=self.tmp)
            # what bot.py does right after: a no-op once handlers exist
            logging.basicConfig(level=logging.INFO)
            url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"
            logging.getLogger("httpx").info('HTTP Request: POST %s "200"', url)
            logging.getLogger("httpx").warning("HTTP Request: POST %s", url)
            logging.getLogger("telegram.ext").error(
                "network error on https://api.telegram.org/bot%s/sendMessage",
                OTHER_TOKEN)
            logging.getLogger("probe").warning("raw value %s", FAKE_TOKEN)
            try:
                raise RuntimeError(f"connect failed: {url}")
            except RuntimeError:
                logging.getLogger("probe").exception("call failed")
        for h in self.root.handlers:
            h.flush()
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_token_never_reaches_the_log_file(self):
        text = self._logged_text("tok")
        self.assertIn("call failed", text, "the records were written")
        self.assertIn("network error", text)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertNotIn(OTHER_TOKEN, text)
        self.assertNotIn("AAFakeToken", text)
        self.assertIn("***", text)

    def test_httpx_and_httpcore_are_quiet(self):
        import logging
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.NOTSET)
        self._logged_text("quiet")
        for name in ("httpx", "httpcore"):
            self.assertGreaterEqual(logging.getLogger(name).getEffectiveLevel(),
                                    logging.WARNING, name)


def _spawn_pythonw(args, env, cwd=ROOT, timeout=40):
    p = subprocess.Popen([PYTHONW] + args, env=env, cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


@unittest.skipUnless(os.path.exists(PYTHONW), "pythonw.exe not available")
class TestEntryPointsLogUnderPythonw(unittest.TestCase):
    """Call sites: the real bot.py and webapp/server.py, started the way
    start-all.ps1 starts them (pythonw, no console)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_pyw_")
        self.logs = os.path.join(self.tmp, "logs")
        self.env = dict(os.environ, TRUENEST_LOG_DIR=self.logs,
                        PYTHONIOENCODING="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self, name, needle, timeout=30):
        path = os.path.join(self.logs, name)
        end = time.time() + timeout
        text = ""
        while time.time() < end:
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if needle in text:
                    return text
            time.sleep(0.3)
        self.fail(f"{needle!r} not in {path}: {text[-800:]!r}")

    def test_bot_startup_crash_is_in_bot_log(self):
        env = dict(self.env, TELEGRAM_BOT_TOKEN="123:fake",
                   BOT_LOCK_PORT=str(free_port()),
                   BOT_DB_PATH=self.tmp)     # a directory: init_db must fail
        p = _spawn_pythonw([os.path.join(ROOT, "bot.py")], env)
        try:
            p.wait(60)
        finally:
            if p.poll() is None:
                p.kill()
        text = self._read("bot.log", "Traceback")
        self.assertIn("OperationalError", text)

    def test_webapp_handler_traceback_is_in_webapp_log(self):
        dbp = os.path.join(self.tmp, "w.db")
        with patch.object(config, "DB_PATH", dbp):
            db.init_db()
            db.get_or_create_broker(A, "a", "A")
            lid = db.create_listing(A, status="submitted",
                                    parsed={"price_vnd": 1})
        c = sqlite3.connect(dbp)
        # the 17/10 case: a script wrote text into a time column, bypassing
        # the db layer and (here) the trigger
        for (name,) in c.execute("SELECT name FROM sqlite_master"
                                 " WHERE type='trigger'").fetchall():
            c.execute(f'DROP TRIGGER "{name}"')
        c.execute("UPDATE tg_listings SET confirmed_at='2026-10-17 07:57:09',"
                  " updated_at='2026-10-17 07:57:09' WHERE id=?", (lid,))
        c.commit()
        c.close()
        port = free_port()
        env = dict(self.env, BOT_DB_PATH=dbp, WEBAPP_DEV="1",
                   WEBAPP_PORT=str(port), TELEGRAM_BOT_TOKEN="")
        p = _spawn_pythonw([os.path.join(WEBAPP, "server.py")], env)
        try:
            status = None
            end = time.time() + 30
            while time.time() < end and status is None:
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port,
                                                      timeout=5)
                    conn.request("GET", f"/api/today?demo=1&broker_id={A}")
                    r = conn.getresponse()
                    status, body = r.status, r.read()
                except OSError:
                    time.sleep(0.3)
            self.assertEqual(status, 500, "server answered")
            self.assertEqual(json.loads(body), {"error": "server_error"})
            text = self._read("webapp.log", "TypeError")
            self.assertIn("Traceback", text)
            self.assertIn("/api/today", text)
            self.assertNotIn("broker_id=", text)
        finally:
            p.kill()
            p.wait(10)


# ================================================== 3. ownership matrix
class TestOwnershipMatrix(HTTPCase):
    # values for route parameters that are not owned by a broker
    SAMPLE = {"feature": "send2client", "request": "mr:none"}

    def _path(self, route, owned_ids):
        parts = []
        for seg in route.pattern.strip("/").split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                kind = seg[1:-1]
                if kind in server.OWNED_KINDS:
                    parts.append(owned_ids[kind])
                elif kind in server.UNOWNED_PARAMS:
                    parts.append(self.SAMPLE[kind])
                else:
                    self.fail(f"{route.method} {route.pattern}: parameter"
                              f" {{{kind}}} is neither owned nor declared"
                              " unowned in server.py")
            else:
                parts.append(seg)
        return "/" + "/".join(parts)

    def _body_value(self, key, ids):
        kind = server.OWNED_BODY_KEYS[key]
        return [ids[kind]] if key.endswith("_ids") else ids[kind]

    def test_every_unowned_param_has_a_sample(self):
        self.assertTrue(set(server.UNOWNED_PARAMS) <= set(self.SAMPLE),
                        "add a sample value for the new parameter kind")

    def test_b_with_a_ids_in_the_path_gets_404_and_nothing_changes(self):
        ids = self.world()
        routes = [r for r in server.ROUTES
                  if not r.public and set(r.params) & set(server.OWNED_KINDS)]
        self.assertGreaterEqual(len(routes), 8, "matrix must not be empty")
        checked = 0
        for r in routes:
            # mixed: owned parameters with A's ids
            path = self._path(r, ids[A])
            before = snapshot(self.path)
            status, body = self.req(r.method, path, {}, broker=B)
            self.assertEqual(status, 404, f"{r.method} {r.pattern}: {body}")
            self.assertEqual(snapshot(self.path), before,
                             f"{r.method} {r.pattern} changed the DB")
            checked += 1
        self.assertEqual(checked, len(routes))

    def test_a_with_own_ids_in_the_path_is_not_404(self):
        """Positive control: the 404 above comes from ownership, not from
        routes that never match."""
        ids = self.world()
        for r in server.ROUTES:
            if r.public or not set(r.params) & set(server.OWNED_KINDS):
                continue
            status, body = self.req(r.method, self._path(r, ids[A]), {},
                                    broker=A)
            self.assertNotEqual(status, 404, f"{r.method} {r.pattern}: {body}")
            self.assertNotEqual(status, 500, f"{r.method} {r.pattern}: {body}")

    def test_b_with_a_ids_in_the_body_gets_404_and_nothing_changes(self):
        ids = self.world()
        writes = [r for r in server.ROUTES
                  if not r.public and r.method in ("POST", "PUT", "DELETE")]
        self.assertGreaterEqual(len(writes), 10)
        self.assertTrue({"client_id", "listing_id", "listing_ids"}
                        <= set(server.OWNED_BODY_KEYS))
        for r in writes:
            path = self._path(r, ids[B])      # B's own path ids pass
            for key in server.OWNED_BODY_KEYS:
                before = snapshot(self.path)
                body = {key: self._body_value(key, ids[A])}
                status, data = self.req(r.method, path, body, broker=B)
                self.assertEqual(status, 404,
                                 f"{r.method} {r.pattern} {key}: {data}")
                self.assertEqual(snapshot(self.path), before,
                                 f"{r.method} {r.pattern} {key} changed DB")

    def test_made_up_ids_in_the_body_get_404(self):
        self.world()
        before = snapshot(self.path)
        status, data = self.req("POST", "/api/share",
                                {"listing_ids": [], "client_id": "cli:bia"},
                                broker=A)
        self.assertEqual(status, 404, data)
        self.assertEqual(snapshot(self.path), before)

    def test_reported_cases_viewing_and_deal_for_another_brokers_client(self):
        """The two writes measured on 17/10: B booked a viewing and recorded
        a commission on A's client, both answered 200."""
        ids = self.world()
        before = snapshot(self.path)
        s1, _ = self.req("POST", "/api/viewings",
                         {"client_id": ids[A]["client"],
                          "scheduled_at": time.time() + 7200}, broker=B)
        s2, _ = self.req("POST", "/api/deals",
                         {"client_id": ids[A]["client"],
                          "commission_amount": 1_000_000}, broker=B)
        self.assertEqual((s1, s2), (404, 404))
        self.assertEqual(snapshot(self.path), before)

    def test_a_with_own_ids_in_the_body_is_not_404(self):
        ids = self.world()
        s, d = self.req("POST", "/api/viewings",
                        {"client_id": ids[A]["client"],
                         "listing_ids": [ids[A]["listing"]],
                         "scheduled_at": time.time() + 7200}, broker=A)
        self.assertEqual(s, 200, d)
        s, d = self.req("POST", "/api/deals",
                        {"client_id": ids[A]["client"],
                         "listing_id": ids[A]["listing"],
                         "commission_amount": "15tr"}, broker=A)
        self.assertEqual(s, 200, d)


# ================================================== 4. types at the db layer
class TestTypesThroughHttp(HTTPCase):
    def test_client_budget_text_is_read_as_money_and_bedrooms_text_is_400(self):
        ids = self.world()
        cid = ids[A]["client"]
        s, d = self.req("PUT", f"/api/client/{cid}",
                        {"fields": {"budget_max": "15tr"}})
        self.assertEqual(s, 200, d)
        c = self.raw()
        self.assertEqual(c.execute("SELECT typeof(budget_max), budget_max"
                                   " FROM clients WHERE id=?", (cid,)
                                   ).fetchone(), ("real", 15_000_000.0))
        before = snapshot(self.path)
        s, d = self.req("PUT", f"/api/client/{cid}",
                        {"fields": {"bedrooms": "2PN"}})
        self.assertEqual((s, d.get("error"), d.get("field")),
                         (400, "bad_field", "bedrooms"))
        self.assertEqual(snapshot(self.path), before)
        s, d = self.req("GET", "/api/clients")
        self.assertEqual(s, 200)

    def test_viewing_time_as_text_is_400(self):
        ids = self.world()
        before = snapshot(self.path)
        s, d = self.req("POST", "/api/viewings",
                        {"client_id": ids[A]["client"],
                         "scheduled_at": "2026-10-18 15:00"})
        self.assertEqual((s, d.get("field")), (400, "scheduled_at"), d)
        self.assertEqual(snapshot(self.path), before)

    def test_viewing_without_time_is_400(self):
        before = snapshot(self.path)
        s, d = self.req("POST", "/api/viewings", {})
        self.assertEqual(s, 400, d)
        self.assertEqual(snapshot(self.path), before)

    def test_viewing_listing_ids_as_a_string_is_400(self):
        ids = self.world()
        before = snapshot(self.path)
        s, d = self.req("POST", "/api/viewings",
                        {"scheduled_at": time.time() + 3600,
                         "listing_ids": "tg:abc"})
        self.assertEqual((s, d.get("field")), (400, "listing_ids"), d)
        self.assertEqual(snapshot(self.path), before)
        self.assertTrue(ids)

    def test_listing_status_outside_the_list_is_400(self):
        ids = self.world()
        lid = ids[A]["listing"]
        s, d = self.req("PUT", f"/api/listing/{lid}/status", {"status": "bogus"})
        self.assertEqual(s, 400, d)
        self.assertEqual(db.get_listing(lid)["status"], "submitted")

    def test_listing_number_as_garbage_is_400_not_silent_200(self):
        ids = self.world()
        lid = ids[A]["listing"]
        s, d = self.req("PUT", f"/api/listing/{lid}",
                        {"fields": {"price_vnd": "abc"}})
        self.assertEqual((s, d.get("field")), (400, "price_vnd"), d)
        s, d = self.req("PUT", f"/api/listing/{lid}",
                        {"fields": {"price_vnd": "12tr", "pet_friendly": "false",
                                    "deposit": "2"}})
        self.assertEqual(s, 200, d)
        p = db.get_listing(lid)["parsed"]
        self.assertEqual(p["price_vnd"], 12_000_000)
        self.assertIs(p["pet_friendly"], False)
        self.assertEqual(p["deposit"], 2.0)

    def test_notify_switch_false_as_text_turns_it_off(self):
        db.get_or_create_broker(A, "a", "A")
        s, d = self.req("PUT", "/api/notify/prefs",
                        {"pref": "notify_match", "enabled": "false"})
        self.assertEqual(s, 200, d)
        self.assertIs(db.get_notify_prefs(A)["notify_match"], False)
        s, d = self.req("PUT", "/api/notify/prefs",
                        {"pref": "notify_match", "enabled": "maybe"})
        self.assertEqual(s, 400, d)


class TestTypesInTheDbLayer(DBCase):
    def test_viewing_listing_ids_string_is_refused(self):
        with self.assertRaises(db.FieldError) as e:
            db.create_viewing(A, listing_ids="tg:abc",
                              scheduled_at=time.time())
        self.assertEqual(e.exception.field, "listing_ids")

    def test_update_viewing_time_text_is_refused(self):
        vid = db.create_viewing(A, scheduled_at=time.time())
        with self.assertRaises(db.FieldError):
            db.update_viewing(vid, scheduled_at="mai 3h")

    def test_deal_commission_text_goes_through_money_reader(self):
        did = db.create_deal(A, commission_vnd="15tr5")
        self.assertEqual(db.get_deal(did)["commission_vnd"], 15_500_000)
        with self.assertRaises(db.FieldError):
            db.create_deal(A, commission_vnd="nhieu")

    def test_bool_strings(self):
        from db import validate
        for v, want in (("false", False), ("0", False), ("off", False),
                        (False, False), (0, False), ("true", True),
                        ("1", True), (True, True), (1, True)):
            self.assertIs(validate.to_bool(v, "x"), want, v)
        for bad in ("maybe", 2, None, [], "đúng"):
            with self.assertRaises(db.FieldError):
                validate.to_bool(bad, "x")


class TestTypeTriggers(DBCase):
    def _assert_blocked(self):
        db.get_or_create_broker(A, "a", "A")
        lid = db.create_listing(A, status="submitted")
        c = self.raw()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE tg_listings SET updated_at = datetime('now')")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE viewings SET scheduled_at = '2026-10-18'")
                c.execute("INSERT INTO viewings (id, broker_id, scheduled_at,"
                          " status, created_at, updated_at) VALUES"
                          " ('vw:t', 1, 'mai', 'scheduled', 1, 1)")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO clients (id, broker_id, budget_max,"
                          " created_at, updated_at) VALUES"
                          " ('cli:t', 1, '15tr', 1, 1)")
            # numbers still pass
            c.execute("UPDATE tg_listings SET updated_at = ?, confirmed_at = ?"
                      " WHERE id = ?", (time.time(), time.time(), lid))
            c.execute("UPDATE tg_listings SET updated_at = '1760000000'"
                      " WHERE id = ?", (lid,))   # affinity makes it a number
            c.rollback()
        finally:
            c.close()

    def test_text_into_time_and_number_columns_is_refused(self):
        self._assert_blocked()

    def test_migration_is_idempotent(self):
        db.init_db()
        db.init_db()
        c = self.raw()
        names = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")]
        c.close()
        self.assertEqual(len(names), len(set(names)))
        self.assertGreater(len(names), 20)
        self._assert_blocked()

    def test_scan_finds_a_wrong_type_row(self):
        from db import migrate
        db.get_or_create_broker(A, "a", "A")
        lid = db.create_listing(A, status="submitted")
        c = self.raw()
        self.assertEqual(migrate.scan_types(c), [])
        for (name,) in c.execute("SELECT name FROM sqlite_master"
                                 " WHERE type='trigger'").fetchall():
            c.execute(f'DROP TRIGGER "{name}"')
        c.execute("UPDATE tg_listings SET updated_at = datetime('now')"
                  " WHERE id = ?", (lid,))
        bad = migrate.scan_types(c)
        c.close()
        self.assertEqual([(t, col) for t, col, _n in bad],
                         [("tg_listings", "updated_at")])


# ================================================== 5. trial consumption
class TestTrialIsAtomic(DBCase):
    def _parallel(self, fn, n=12):
        res, barrier = [], threading.Barrier(n)

        def run():
            barrier.wait()
            res.append(fn())
        ts = [threading.Thread(target=run) for _ in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return res

    def test_twelve_parallel_uses_give_exactly_three(self):
        db.get_or_create_broker(A, "a", "A")
        codes = self._parallel(lambda: api.use_trial(A, "send2client")[1])
        self.assertEqual(sorted(codes), [200] * 3 + [402] * 9)
        self.assertEqual(db.get_trial_usage(A, "send2client"), 3)

    def test_sequential_uses(self):
        db.get_or_create_broker(A, "a", "A")
        got = [api.use_trial(A, "send2client") for _ in range(5)]
        self.assertEqual([c for _, c in got], [200, 200, 200, 402, 402])
        self.assertEqual([d.get("remaining") for d, _ in got[:3]], [2, 1, 0])

    def test_twelve_parallel_shares_create_three_pages(self):
        db.get_or_create_broker(A, "a", "A")
        lid = db.create_listing(A, status="submitted")
        codes = self._parallel(lambda: api.create_share(A, [lid])[1])
        self.assertEqual(sorted(codes), [200] * 3 + [402] * 9)
        self.assertEqual(len(db.list_share_pages(A)), 3)
        self.assertEqual(db.get_trial_usage(A, "send2client"), 3)


class TestTrialIsAtomicOverHttp(HTTPCase):
    def test_twelve_parallel_requests_give_exactly_three(self):
        db.get_or_create_broker(A, "a", "A")
        res, barrier = [], threading.Barrier(12)

        def run():
            barrier.wait()
            res.append(self.req("POST", "/api/trial/send2client/use", {})[0])
        ts = [threading.Thread(target=run) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(res), [200] * 3 + [402] * 9)
        self.assertEqual(db.get_trial_usage(A, "send2client"), 3)


# ================================================== 6. confirmed_at
class ConfirmedCase(DBCase):
    def listing(self, confirmed_days_ago, updated_days_ago=0, uid=A,
                status="submitted"):
        db.get_or_create_broker(uid, "a", "A")
        lid = db.create_listing(uid, status=status,
                                parsed={"price_vnd": 9_000_000,
                                        "bedrooms": 2, "district": "Hải Châu"})
        now = time.time()
        c = self.raw()
        c.execute("UPDATE tg_listings SET confirmed_at = ?, updated_at = ?,"
                  " created_at = ? WHERE id = ?",
                  (now - confirmed_days_ago * DAY, now - updated_days_ago * DAY,
                   now - max(confirmed_days_ago, updated_days_ago) * DAY, lid))
        c.commit()
        c.close()
        return lid

    def confirmed(self, lid):
        c = self.raw()
        try:
            return c.execute("SELECT confirmed_at FROM tg_listings WHERE id=?",
                             (lid,)).fetchone()[0]
        finally:
            c.close()


class TestConfirmedAtWriters(ConfirmedCase):
    def test_new_listing_is_confirmed_at_creation(self):
        db.get_or_create_broker(A, "a", "A")
        lid = db.create_listing(A, status="submitted")
        row = db.get_listing(lid)
        self.assertEqual(row["confirmed_at"], row["created_at"])

    def test_edits_photos_posts_and_status_do_not_confirm(self):
        lid = self.listing(confirmed_days_ago=20)
        before = self.confirmed(lid)
        db.update_listing_field(lid, "price_vnd", 8_000_000)
        db.update_listing_field(lid, "description", "mô tả mới")
        db.add_photo_url(lid, "https://r2/x.jpg")
        db.save_post(lid, "bài đăng", lang="en")
        db.update_listing(lid, photo_file_ids=["a", "b"])
        db.set_listing_status(lid, "negotiating")
        self.assertEqual(self.confirmed(lid), before)
        self.assertGreater(db.get_listing(lid)["updated_at"], before,
                           "updated_at still records the edits")

    def test_webapp_refresh_available_confirms(self):
        lid = self.listing(confirmed_days_ago=20)
        data, code = api.refresh_listing(A, lid, "available")
        self.assertEqual(code, 200, data)
        self.assertAlmostEqual(self.confirmed(lid), time.time(), delta=5)

    def test_webapp_refresh_rented_does_not_confirm(self):
        lid = self.listing(confirmed_days_ago=20)
        before = self.confirmed(lid)
        api.refresh_listing(A, lid, "rented")
        self.assertEqual(self.confirmed(lid), before)

    def test_bot_refresh_confirms(self):
        lid = self.listing(confirmed_days_ago=40)
        db.touch_listing(lid)
        self.assertAlmostEqual(self.confirmed(lid), time.time(), delta=5)

    def test_backfill_from_updated_at(self):
        # a DB from before the column existed
        tmp = os.path.join(self.tmp, "old.db")
        src = sqlite3.connect(self.path)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        src.close()
        for (name,) in dst.execute("SELECT name FROM sqlite_master"
                                   " WHERE type='trigger'").fetchall():
            dst.execute(f'DROP TRIGGER "{name}"')
        dst.execute("ALTER TABLE tg_listings DROP COLUMN confirmed_at")
        dst.execute("INSERT INTO brokers (user_id, created_at, updated_at)"
                    " VALUES (5, 1, 1)")
        dst.execute("INSERT INTO tg_listings (id, broker_id, created_at,"
                    " updated_at) VALUES ('tg:old', 5, 1700000000, 1790000000)")
        dst.commit()
        dst.close()
        db.init_db(tmp)
        c = sqlite3.connect(tmp)
        self.assertEqual(c.execute("SELECT confirmed_at FROM tg_listings"
                                   " WHERE id='tg:old'").fetchone()[0],
                         1790000000)
        c.close()


class TestConfirmedAtReaders(ConfirmedCase):
    """Each freshness reader: confirmed 40 days ago, edited today -> old."""

    def test_propose_freshness(self):
        lid = self.listing(confirmed_days_ago=40)
        age, _e, label, mult, tier = api.freshness_info(db.get_listing(lid))
        self.assertGreater(age, 39)
        self.assertEqual(mult, 0.5)

    def test_today_stale_count(self):
        # two old-but-edited-today, one confirmed-but-not-edited: reading
        # updated_at would give 1, confirmed_at gives 2
        self.listing(confirmed_days_ago=40, updated_days_ago=0)
        self.listing(confirmed_days_ago=40, updated_days_ago=0)
        self.listing(confirmed_days_ago=1, updated_days_ago=30)
        data, _ = api.get_today(A)
        self.assertEqual(data["stale_listings"]["count"], 2)

    def test_profile_score_freshness(self):
        import utils
        self.listing(confirmed_days_ago=40)
        self.assertEqual(utils.broker_profile_score(A)["fresh_listings"], 0)

    def test_stale_listings_query(self):
        old = self.listing(confirmed_days_ago=40)
        new = self.listing(confirmed_days_ago=1, updated_days_ago=30)
        ids = [l["id"] for l in db.stale_listings(older_than_days=7)]
        self.assertIn(old, ids)
        self.assertNotIn(new, ids)

    def test_stale_batch_line_days(self):
        import feat_stale
        lid = self.listing(confirmed_days_ago=40)
        self.assertIn("40 ngày", feat_stale._listing_brief(db.get_listing(lid)))

    def test_weekly_sweep(self):
        import feat_notify
        self.listing(confirmed_days_ago=40, updated_days_ago=0)
        self.listing(confirmed_days_ago=40, updated_days_ago=0)
        self.listing(confirmed_days_ago=1, updated_days_ago=30)
        sent = []

        async def capture(ctx, broker_id, stale):
            sent.append((broker_id, len(stale)))
        with patch.object(feat_notify, "notify_stale_listings", capture):
            asyncio.run(feat_notify.sweep_stale_listings(None))
        self.assertEqual(sent, [(A, 2)])

    def test_listing_line_badge(self):
        import utils
        lid = self.listing(confirmed_days_ago=40)
        self.assertIn("🔴", utils.listing_line(db.get_listing(lid)))

    def test_detail_refresh_prompt(self):
        import feat_listings
        old = self.listing(confirmed_days_ago=40, updated_days_ago=0)
        text, _kb = feat_listings._detail_content(db.get_listing(old), 0, "all")
        self.assertIn("làm mới", text)
        new = self.listing(confirmed_days_ago=1, updated_days_ago=0)
        c = self.raw()
        c.execute("UPDATE tg_listings SET created_at = ? WHERE id = ?",
                  (time.time() - 50 * DAY, new))
        c.commit()
        c.close()
        text, _kb = feat_listings._detail_content(db.get_listing(new), 0, "all")
        self.assertNotIn("làm mới", text)

    def test_listing_api_exposes_confirmed_at(self):
        lid = self.listing(confirmed_days_ago=3)
        data, _ = api.get_listing(A, lid)
        self.assertAlmostEqual(data["confirmed_at"], time.time() - 3 * DAY,
                               delta=5)


if __name__ == "__main__":
    unittest.main()
