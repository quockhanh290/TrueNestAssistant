"""Owner-approved client and listing status rules.

Every test uses a temporary database.  HTTP requests exercise the real
``webapp.server`` routing and error translation.
"""
import http.client
import json
import os
import shutil
import sqlite3
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

import test_flows  # noqa: E402,F401  (sets the test DB before bot imports)

import config  # noqa: E402
import db  # noqa: E402
from db.validate import FieldError  # noqa: E402
import server  # noqa: E402
import utils  # noqa: E402


BROKER = 73001


class DBCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_status_")
        self.path = os.path.join(self.tmp, "test.db")
        self._db_patch = patch.object(config, "DB_PATH", self.path)
        self._db_patch.start()
        db.init_db()
        db.get_or_create_broker(BROKER, "status_tester", "Status Tester")

    def tearDown(self):
        self._db_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_confirmed_at(self, listing_id, value):
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE tg_listings SET confirmed_at = ? WHERE id = ?",
                (value, listing_id),
            )
            conn.commit()
        finally:
            conn.close()


class HTTPCase(DBCase):
    def setUp(self):
        super().setUp()
        self._dev_patch = patch.object(server, "DEV_MODE", True)
        self._dev_patch.start()
        self.srv = server.Server(("127.0.0.1", 0), server.Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(
            target=self.srv.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._dev_patch.stop()
        super().tearDown()

    def req(self, method, path, body=None):
        path += ("&" if "?" in path else "?") + (
            f"demo=1&broker_id={BROKER}"
        )
        data = None if body is None else json.dumps(body).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(
                method,
                path,
                body=data,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            conn.close()


class TestClientStatusRules(HTTPCase):
    def test_every_client_status_uses_the_shared_vietnamese_label(self):
        statuses = db.CLIENT_STATUSES
        self.assertTrue(statuses, "CLIENT_STATUSES must not be empty")
        client_id = db.create_client(BROKER, name="Khach")

        for client_status in statuses:
            with self.subTest(status=client_status):
                db.update_client(client_id, status=client_status)
                status, body = self.req("GET", f"/api/client/{client_id}")
                self.assertEqual(status, 200, body)
                self.assertTrue(body["status_vi"])
                self.assertEqual(
                    body["status_vi"], utils.CLIENT_STATUS_LABEL[client_status]
                )

    def test_invalid_client_status_is_refused_by_http_and_db(self):
        client_id = db.create_client(BROKER, name="Khach")

        for invalid in ("closed", "bogus"):
            with self.subTest(path="http", status=invalid):
                status, body = self.req(
                    "PUT",
                    f"/api/client/{client_id}",
                    {"fields": {"status": invalid}},
                )
                self.assertEqual(status, 400, body)
                self.assertEqual(body.get("error"), "bad_field")
                self.assertEqual(db.get_client(client_id)["status"], "new")

            with self.subTest(path="db", status=invalid):
                with self.assertRaises(FieldError):
                    db.update_client(client_id, status=invalid)
                self.assertEqual(db.get_client(client_id)["status"], "new")

            with self.subTest(path="db-create", status=invalid):
                with self.assertRaises(FieldError):
                    db.create_client(BROKER, name="Khach 2", status=invalid)

    def test_invalid_client_status_filter_is_bad_field(self):
        status, body = self.req("GET", "/api/clients?status=bogus")
        self.assertEqual(status, 400, body)
        self.assertEqual(body.get("error"), "bad_field")


class TestListingSubmissionConfirmation(DBCase):
    def test_only_publish_transitions_refresh_confirmed_at(self):
        old = time.time() - 86400
        cases = (
            ("draft", "submitted", True),
            ("rented", "submitted", True),
            ("negotiating", "submitted", False),
            ("submitted", "rented", False),
        )

        for old_status, new_status, should_refresh in cases:
            with self.subTest(old=old_status, new=new_status):
                listing_id = db.create_listing(
                    BROKER, raw_text="2PN", status=old_status
                )
                self.set_confirmed_at(listing_id, old)
                before = time.time()
                self.assertTrue(db.set_listing_status(listing_id, new_status))
                after = time.time()
                confirmed = db.get_listing(listing_id)["confirmed_at"]
                if should_refresh:
                    self.assertLessEqual(abs(confirmed - before), 5)
                    self.assertLessEqual(confirmed, after)
                else:
                    self.assertEqual(confirmed, old)


if __name__ == "__main__":
    unittest.main()
