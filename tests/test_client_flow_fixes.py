"""Regression tests for the client-flow review findings A1-A5 and A8.

Import test_flows first: it selects the shared temporary database before the
application modules import config.
"""
import os
import sys
import time
from contextlib import closing
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_flows as tf  # noqa: E402,F401
from test_flows import LinhFlowTest  # noqa: E402

import bot  # noqa: E402
import db  # noqa: E402
import feat_clients  # noqa: E402
import feat_deals  # noqa: E402
import feat_match  # noqa: E402


MISSING_CLIENT = "Khách này không còn nữa."


class _TelegramHTMLParser(HTMLParser):
    """Small strict subset sufficient for the client message builders."""

    ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike",
               "del", "code", "pre", "a", "blockquote", "tg-spoiler"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED:
            raise AssertionError(f"Telegram HTML tag không hợp lệ: <{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise AssertionError(f"Telegram HTML đóng thẻ sai: </{tag}>")

    def finish(self, text):
        self.feed(text)
        self.close()
        if self.stack:
            raise AssertionError(f"Telegram HTML thiếu đóng thẻ: {self.stack}")


class TestClientFlowFixes(LinhFlowTest):
    async def test_a1_all_client_buttons_and_text_steps_enforce_owner(self):
        owner = self.broker(tier="pro")
        intruder = self.broker(tier="max")
        secret = "Hoa hồng <50%> & SĐT 0905123456"
        cid = db.create_client(owner, name="Khách Bí Mật",
                               phone="0905123456")
        db.add_note(cid, secret)
        listing = self.listing(intruder)

        callbacks = [
            f"client:{cid}:0:a:a",
            f"client:note:{cid}",
            f"client:status:{cid}",
            f"client:setstatus:{cid}:viewed",
            f"client:edit:{cid}",
            f"client:editfield:{cid}:phone",
            f"client:seturg:{cid}:urgent",
            f"client:match:{cid}",
            f"client:send:{cid}:{listing['id']}",
            f"client:delete:{cid}",
            f"client:delconfirm:{cid}",
            f"send2client:start:{cid}",
            f"send2client:followup:{cid}",
            f"vw:c:{cid}",
            f"deal:mc:{cid}",
            f"client:reqs:{cid}",
            f"client:broadcast:{cid}",
        ]
        for data in callbacks:
            with self.subTest(data=data):
                self.outbox.clear()
                await self.cb(intruder, data)
                rendered = "\n".join(self.texts())
                self.assertIn(MISSING_CLIENT, rendered)
                self.assertNotIn("0905123456", rendered)
                self.assertNotIn("Khách Bí Mật", rendered)
                self.assertNotIn("Hoa hồng", rendered)

        session_callbacks = [
            ("send2client:toggle:%s" % listing["id"], "send2client",
             {"client_id": cid, "selected": [],
              "cands": [listing["id"]]}),
            ("send2client:done", "send2client",
             {"client_id": cid, "selected": [listing["id"]]}),
            ("send2client:lang:vi", "send2client",
             {"client_id": cid, "selected": [listing["id"]]}),
            ("send2client:copy", "send2client",
             {"client_id": cid, "message": "secret"}),
            ("send2client:sent", "send2client",
             {"client_id": cid, "selected": [listing["id"]]}),
            ("send2client:nochoice", "send2client", {"client_id": cid}),
            ("send2client:chose:%s" % listing["id"], "send2client",
             {"client_id": cid, "followup": True}),
            ("vw:date:20261020", "scheduling",
             {"client_id": cid, "date": "20261020"}),
            ("vw:time:0900", "scheduling",
             {"client_id": cid, "date": "20261020"}),
            ("vw:lpick:toggle:%s" % listing["id"], "scheduling",
             {"client_id": cid, "date": "20261020", "time": "0900",
              "listing_ids": []}),
            ("vw:lpick:done", "scheduling",
             {"client_id": cid, "date": "20261020", "time": "0900",
              "listing_ids": [listing["id"]]}),
            ("vw:lpick:back", "scheduling",
             {"client_id": cid, "date": "20261020", "time": "0900",
              "listing_ids": [listing["id"]]}),
            ("vw:ok", "scheduling",
             {"client_id": cid, "date": "20261020", "time": "0900",
              "listing_ids": [listing["id"]]}),
            ("deal:ml:%s" % listing["id"], "deal_new",
             {"client_id": cid}),
            ("enrich:later", "enrich_ctx", {"client_id": cid}),
            (f"clients:extrareq:skip:{cid}", "client_extra_req",
             {"client_id": cid}),
        ]
        for data, state, value in session_callbacks:
            with self.subTest(session_callback=data):
                self.outbox.clear()
                self.ctx(intruder).user_data.clear()
                self.ctx(intruder).user_data[state] = value
                await self.cb(intruder, data)
                rendered = "\n".join(self.texts())
                self.assertIn(MISSING_CLIENT, rendered)
                self.assertNotIn("0905123456", rendered)

        original = db.get_client(cid)
        for state, value in (
            ("adding_note", {"client_id": cid}),
            ("editing_client", {"client_id": cid, "field": "name"}),
            ("client_extra_req", {"client_id": cid}),
            ("send2client", {"client_id": cid,
                             "awaiting_dt": listing["id"]}),
            ("adding_deal", {"client_id": cid,
                             "client_name": "Khách Bí Mật",
                             "listing_id": listing["id"]}),
        ):
            with self.subTest(text_step=state):
                self.outbox.clear()
                self.ctx(intruder).user_data[state] = value
                await self.text(intruder, "Nội dung tấn công <x> & y")
                self.assertIn(MISSING_CLIENT, self.last_text())
                self.assertNotIn(state, self.ctx(intruder).user_data)
                now = db.get_client(cid)
                self.assertEqual(now["name"], original["name"])
                self.assertEqual(now["notes"], original["notes"])
                self.assertEqual(now["requirements_raw"],
                                 original["requirements_raw"])

        # Missing and foreign ids deliberately share the same reply, while a
        # forged confirm-delete must not claim success or delete the row.
        self.outbox.clear()
        await self.cb(intruder, "client:delconfirm:cli:missing")
        missing_reply = self.last_text()
        self.outbox.clear()
        await self.cb(intruder, f"client:delconfirm:{cid}")
        self.assertEqual(self.last_text(), missing_reply)
        self.assertIsNotNone(db.get_client(cid))
        self.assertNotIn("đã xóa", self.last_text().lower())

    async def test_a2_foreign_client_viewing_is_rejected_and_feedback_is_safe(self):
        owner = self.broker(tier="pro")
        intruder = self.broker(tier="pro")
        cid = db.create_client(owner, name="Khách A", status="scheduled")
        listing = self.listing(intruder)

        self.assertIsNone(db.create_viewing(
            intruder, client_id=cid, client_name="Khách A",
            listing_ids=[listing["id"]], scheduled_at=time.time() - 3600))
        self.assertIsNone(db.create_deal(
            intruder, client_id=cid, client_name="Khách A",
            listing_id=listing["id"], commission_vnd=15_000_000))

        # Legacy/corrupt rows can still exist: feedback may finish the viewing,
        # but must not touch or start client feedback for another broker.
        from db.core import connect
        vid = "vw:foreignclient"
        now = time.time()
        with closing(connect()) as conn:
            conn.execute(
                "INSERT INTO viewings (id, broker_id, client_id, client_name,"
                " listing_id, listing_ids, scheduled_at, status, notes,"
                " feedback, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', '', '', ?, ?)",
                (vid, intruder, cid, "Khách A", listing["id"],
                 '["%s"]' % listing["id"], now - 3600, now, now))
            conn.commit()
        self.assertEqual(db.client_viewings(cid, broker_id=owner), [])
        await self.cb(intruder, f"vw:fb:{vid}")
        self.assertNotIn("viewing_feedback", self.ctx(intruder).user_data)
        self.assertEqual(db.get_client(cid)["status"], "scheduled")

    def test_a3_all_client_html_builders_escape_user_text(self):
        injected = "<x> & <b>không phải markup</b>"
        c = {
            "id": "cli:x", "name": f"Tom {injected}",
            "phone": f"0905 {injected}", "requirements_raw": injected,
            "notes": injected, "district": f"Sơn Trà {injected}",
            "property_type": f"căn hộ {injected}", "bedrooms": 0,
            "budget_min": None, "budget_max": 15_000_000,
            "urgency": "normal", "status": "new", "viewed_listings": [],
        }
        builders = {
            "client list row": feat_clients._client_line(c),
            "client card": feat_clients._client_detail_text(c, "anh"),
        }
        for name, message in builders.items():
            with self.subTest(builder=name):
                self.assertNotIn(injected, message)
                self.assertIn("&lt;x&gt; &amp;", message)
                _TelegramHTMLParser().finish(message)

    def test_a4_studio_is_a_real_matching_filter(self):
        studio_client = {"bedrooms": 0, "budget_max": 10_000_000,
                         "district": "Sơn Trà"}
        studio = {"id": "tg:studio", "status": "submitted",
                  "photo_file_ids": [], "parsed": {
                      "bedrooms": 0, "price_vnd": 10_000_000,
                      "district": "Sơn Trà"}}
        two_bed = {"id": "tg:2br", "status": "submitted",
                   "photo_file_ids": [], "parsed": {
                       "bedrooms": 2, "price_vnd": 10_000_000,
                       "district": "Sơn Trà"}}
        passed, failed = feat_match.filter_hard_criteria(
            [studio, two_bed], studio_client)
        self.assertEqual([row["id"] for row in passed], ["tg:studio"])
        self.assertIn(2.0, failed["bedrooms"]["have"])
        self.assertGreater(feat_match.score_match(studio, studio_client),
                           feat_match.score_match(two_bed, studio_client))
        uid = self.broker()
        cid = db.create_client(uid, name="Studio", requirements={
            "bedrooms": 0, "max_price": 10_000_000,
            "district": "Sơn Trà"})
        rid = db.create_match_request(uid, cid, "Studio Sơn Trà <10tr")
        self.assertEqual(db.get_propose_request(rid)["bedrooms"], 0)
        rows = db.list_open_xbroker_requests(exclude_broker_id=uid)
        self.assertEqual(rows[0]["bedrooms"], 0)

    async def test_a5_duplicate_deal_is_blocked_in_db_and_bot(self):
        uid = self.broker(tier="pro")
        cid = db.create_client(uid, name="Khách A")
        listing = self.listing(uid)
        first = db.create_deal(uid, client_id=cid, client_name="Khách A",
                               listing_id=listing["id"],
                               commission_vnd=15_000_000)
        second = db.create_deal(uid, client_id=cid, client_name="Khách A",
                                listing_id=listing["id"],
                                commission_vnd=15_000_000)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(db.list_deals(uid)), 1)

        self.ctx(uid).user_data["adding_deal"] = {
            "client_id": cid, "client_name": "Khách A",
            "listing_id": listing["id"],
        }
        await self.text(uid, "15tr")
        self.assertIn("đã được lưu", self.last_text().lower())
        self.assertEqual(len(db.list_deals(uid)), 1)

    def test_a5_same_deal_after_30_days_is_a_new_deal(self):
        uid = self.broker(tier="pro")
        cid = db.create_client(uid, name="Khách A")
        listing = self.listing(uid)
        first = db.create_deal(uid, client_id=cid, client_name="Khách A",
                               listing_id=listing["id"],
                               commission_vnd=15_000_000)
        conn = db.connect()
        conn.execute("UPDATE deals SET created_at = created_at - ? WHERE id = ?",
                     (31 * 86400, first))
        conn.commit()
        conn.close()
        renewal = db.create_deal(uid, client_id=cid, client_name="Khách A",
                                 listing_id=listing["id"],
                                 commission_vnd=15_000_000)
        self.assertIsNotNone(renewal)
        self.assertIsNone(db.create_deal(uid, client_id=cid,
                                         client_name="Khách A",
                                         listing_id=listing["id"],
                                         commission_vnd=15_000_000))
        self.assertEqual(len(db.list_deals(uid)), 2)

    def test_a8_no_unimplemented_reminder_promise(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        promises = ("nhắc trước 1 tiếng", "2 ngày nữa em sẽ nhắc")
        for filename in ("bot.py", "feat_sendclient.py", "feat_viewings.py"):
            with open(os.path.join(root, filename), encoding="utf-8") as fh:
                source = fh.read().lower()
            for promise in promises:
                with self.subTest(filename=filename, promise=promise):
                    self.assertNotIn(promise, source)
