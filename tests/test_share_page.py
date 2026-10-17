"""Regression tests for the public share page and booking notification."""
import html
import http.client
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urljoin, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, ROOT)
sys.path.insert(0, WEBAPP)

# config reads BOT_DB_PATH at import time.  Keep the same import ordering as
# the other integration suites so no test can accidentally use the real DB.
import test_flows  # noqa: E402,F401

import config  # noqa: E402
import db  # noqa: E402
import feat_notify  # noqa: E402
import server  # noqa: E402


BROKER = 991001


class SharePageHTTPCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_share_")
        self.path = os.path.join(self.tmp, "test.db")
        self.db_patch = patch.object(config, "DB_PATH", self.path)
        self.db_patch.start()
        db.init_db()

        db.get_or_create_broker(BROKER, "broker", "Broker Test")
        self.listing_id = db.create_listing(
            BROKER,
            raw_text="2PN",
            status="submitted",
            parsed={"bedrooms": 2, "building_name": "Azura",
                    "price_vnd": 15_000_000},
        )
        self.token = db.create_share_page(BROKER, [self.listing_id])

        self.srv = server.Server(("127.0.0.1", 0), server.Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.db_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        try:
            conn.request(method, path, body=payload,
                         headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            text = response.read().decode("utf-8")
            return response.status, text
        finally:
            conn.close()

    @staticmethod
    def fetch_targets(page_html, link_url):
        """Resolve the page's small fetch expressions as a browser would."""
        token_match = re.search(r'<div class="wrap"[^>]*data-token="([^"]*)"',
                                page_html)
        if not token_match:
            raise AssertionError("share page has no data-token")
        token = html.unescape(token_match.group(1))
        share_path = "/s/" + quote(token, safe="")
        expressions = re.findall(r"fetch\(([^,]+),", page_html)
        targets = []
        for expression in expressions:
            expression = expression.strip()
            absolute = re.fullmatch(r"sharePath\s*\+\s*['\"](/[^'\"]+)['\"]",
                                    expression)
            literal = re.fullmatch(r"['\"]([^'\"]+)['\"]", expression)
            if absolute:
                target = share_path + absolute.group(1)
            elif literal:
                target = urljoin(link_url, literal.group(1))
            else:
                raise AssertionError("unknown fetch expression: " + expression)
            targets.append(urlparse(target).path)
        return targets

    def test_rendered_fetch_targets_book_and_report_over_http(self):
        link = f"http://127.0.0.1:{self.port}/s/{self.token}"
        status, page_html = self.request("GET", f"/s/{self.token}")
        self.assertEqual(status, 200)
        targets = self.fetch_targets(page_html, link)
        self.assertEqual(targets, [f"/s/{self.token}/book",
                                   f"/s/{self.token}/report"])

        status, _ = self.request("POST", targets[0], {
            "listing_id": self.listing_id,
            "name": "Lan",
            "phone": "0901234567",
            "preferred_date": "2026-10-20",
            "note": "Buoi sang",
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(db.list_share_bookings(token=self.token)), 1)

        status, _ = self.request("POST", targets[1], {
            "listing_id": self.listing_id,
            "reason": "rented",
        })
        self.assertEqual(status, 200)

    def test_old_relative_target_resolves_to_missing_route(self):
        link = f"http://127.0.0.1:{self.port}/s/{self.token}"
        old_path = urlparse(urljoin(link, "book")).path
        self.assertEqual(old_path, "/s/book")
        status, _ = self.request("POST", old_path, {
            "listing_id": self.listing_id,
            "name": "Lan",
            "phone": "0901234567",
        })
        self.assertEqual(status, 404)
        self.assertEqual(db.list_share_bookings(token=self.token), [])

    def test_preferred_date_keeps_iso_date_and_drops_other_input(self):
        endpoint = f"/s/{self.token}/book"
        common = {"listing_id": self.listing_id, "name": "Lan",
                  "phone": "0901234567"}
        status, _ = self.request("POST", endpoint, {
            **common, "preferred_date": "2026-10-20"})
        self.assertEqual(status, 200)
        status, _ = self.request("POST", endpoint, {
            **common, "preferred_date": "<b>mai</b>"})
        self.assertEqual(status, 200)

        with sqlite3.connect(self.path) as conn:
            dates = [row[0] for row in conn.execute(
                "SELECT preferred_date FROM share_bookings ORDER BY created_at, rowid")]
        self.assertEqual(dates, ["2026-10-20", ""])


class TestBookingNotification(unittest.IsolatedAsyncioTestCase):
    async def test_client_values_are_html_escaped(self):
        ctx = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        booking = {
            "name": "<a href='x'>y</a> & <3",
            "phone": "<b>0901</b>",
            "listing_id": "tg:test",
            "preferred_date": "<i>mai</i>",
        }
        with patch.object(feat_notify.db, "get_notify_prefs",
                          return_value={"notify_booking": True}), \
                patch.object(feat_notify.db, "get_listing", return_value={
                    "parsed": {"building_name": "<u>Azura</u>"}}):
            await feat_notify.notify_new_booking(ctx, BROKER, booking)

        sent = ctx.bot.send_message.await_args.kwargs["text"]
        self.assertNotIn("<a", sent)
        self.assertNotIn("<b>0901", sent)
        self.assertNotIn("<i>mai", sent)
        self.assertNotIn("<u>Azura", sent)
        self.assertIn("&amp;", sent)
        self.assertIn("&lt;3", sent)


if __name__ == "__main__":
    unittest.main()
