"""Integration test harness for TrueNest Assistant (Linh) Telegram bot.

Simulates full user flows with mocked python-telegram-bot objects:
free-form intake, forwards, guided intake, highlights, client pipeline,
premium gating, and deleted-listing filtering.

Run from ~/workspace/broker-bot with the project venv:
    .venv/bin/python -m unittest tests.test_flows -v

Every test uses a FRESH temp SQLite DB. No network, no real Telegram.
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

# ---------------------------------------------------------------- setup
# Temp DB must be chosen before config is imported (it reads env at import).
_TMPDIR = tempfile.mkdtemp(prefix="linh_flowtest_")
os.environ["BOT_DB_PATH"] = os.path.join(_TMPDIR, "test_broker.db")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))

import bot  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import feat_intake  # noqa: E402
import feat_clients  # noqa: E402
import feat_listings  # noqa: E402
import feat_premium  # noqa: E402
import feat_sendclient  # noqa: E402
import feat_write  # noqa: E402
import utils  # noqa: E402
from utils import _buffers, _media_groups  # noqa: E402


# ---------------------------------------------------------------- mocks
class MockPhoto:
    def __init__(self, file_id):
        self.file_id = file_id


class MockUser:
    def __init__(self, uid, username="testuser", full_name="Test User"):
        self.id = uid
        self.username = username
        self.full_name = full_name
        self.first_name = "Test"


class MockChat:
    def __init__(self, chat_id, title=None, username=None):
        self.id = chat_id
        self.title = title
        self.username = username
        self.type = "private"

    async def send_action(self, action):
        return None


class MockMessage:
    _mid = 0

    def __init__(self, outbox, chat, from_user, text=None, caption=None,
                 photo_ids=None, media_group_id=None, forward_from_chat=None,
                 forward_from=None, forward_sender_name=None):
        MockMessage._mid += 1
        self.message_id = MockMessage._mid
        self._outbox = outbox
        self.chat = chat
        self.from_user = from_user
        self.text = text
        self.caption = caption
        self.photo = [MockPhoto(fid) for fid in (photo_ids or [])]
        self.media_group_id = media_group_id
        self.forward_from_chat = forward_from_chat
        self.forward_from = forward_from
        self.forward_sender_name = forward_sender_name
        self.forward_origin = None

    @property
    def chat_id(self):
        return self.chat.id

    async def reply_text(self, text, reply_markup=None, parse_mode=None,
                         **kwargs):
        self._outbox.append({"kind": "reply", "text": text,
                             "markup": reply_markup})
        return self

    async def set_reaction(self, emoji):
        return None


class MockCallbackQuery:
    def __init__(self, outbox, data, from_user, message):
        self.id = "cbq1"
        self._outbox = outbox
        self.data = data
        self.from_user = from_user
        self.message = message
        self.answered = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)
        return None

    async def edit_message_text(self, text, reply_markup=None,
                                parse_mode=None, **kwargs):
        self._outbox.append({"kind": "edit", "text": text,
                             "markup": reply_markup, "data": self.data})
        return None


class MockUpdate:
    def __init__(self, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query

    @property
    def effective_user(self):
        if self.message:
            return self.message.from_user
        return self.callback_query.from_user

    @property
    def effective_chat(self):
        if self.message:
            return self.message.chat
        return self.callback_query.message.chat

    @property
    def effective_message(self):
        return self.message or self.callback_query.message


class MockBot:
    def __init__(self, outbox):
        self._outbox = outbox

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None, reply_to_message_id=None):
        self._outbox.append({"kind": "send", "chat_id": chat_id,
                             "text": text, "markup": reply_markup,
                             "reply_to": reply_to_message_id})
        chat = MockChat(chat_id)
        user = MockUser(0)
        return MockMessage(self._outbox, chat, user, text=text)

    async def send_chat_action(self, chat_id, action):
        return None


class MockContext:
    def __init__(self, outbox):
        self.user_data = {}
        self.bot = MockBot(outbox)


# ---------------------------------------------------------------- base
async def _noop(*a, **k):
    return None


class LinhFlowTest(unittest.IsolatedAsyncioTestCase):
    """Base: fresh DB, mocked sleeps, per-uid contexts, simulate helpers."""

    async def asyncSetUp(self):
        # fresh DB
        db_path = os.environ["BOT_DB_PATH"]
        if os.path.exists(db_path):
            os.remove(db_path)
        db.init_db()
        _buffers.clear()
        _media_groups.clear()

        self.outbox = []          # every bot-visible message, in order
        self._ctxs = {}
        self._uid_seq = [1000]

        # instant sleeps (no real 5s/typing waits in tests)
        self._real_sleep = asyncio.sleep

        async def _instant(*a, **k):
            return None

        self._patches = [
            patch("asyncio.sleep", _instant),
            patch.object(utils, "maybe_send_hint_to_chat", _noop),
            patch.object(utils, "maybe_send_hint", _noop),
        ]
        for p in self._patches:
            p.start()
        # _flush_after is patched to no-op; tests fire the real one on demand
        self._real_flush = feat_intake._flush_after
        self._p_flush = patch.object(feat_intake, "_flush_after", _noop)
        self._p_flush.start()

    async def asyncTearDown(self):
        self._p_flush.stop()
        for p in self._patches:
            p.stop()
        _buffers.clear()
        _media_groups.clear()
        # cancel stray tasks
        for t in asyncio.all_tasks():
            if t is not asyncio.current_task():
                t.cancel()

    # -- helpers ------------------------------------------------------
    def _next_uid(self):
        self._uid_seq[0] += 1
        return self._uid_seq[0]

    def ctx(self, uid):
        if uid not in self._ctxs:
            self._ctxs[uid] = MockContext(self.outbox)
        return self._ctxs[uid]

    def _msg(self, uid, text=None, **kw):
        user = MockUser(uid)
        chat = MockChat(uid)
        return MockMessage(self.outbox, chat, user, text=text, **kw)

    async def text(self, uid, t, **kw):
        upd = MockUpdate(message=self._msg(uid, text=t, **kw))
        await bot.on_text(upd, self.ctx(uid))
        await self.drain()

    async def photo(self, uid, file_id, caption=None, **kw):
        upd = MockUpdate(message=self._msg(
            uid, photo_ids=[file_id], caption=caption, **kw))
        await feat_intake.on_photo(upd, self.ctx(uid))
        await self.drain()

    async def album(self, uid, file_ids, caption=None, mg_id="mg1", **kw):
        for i, fid in enumerate(file_ids):
            cap = caption if i == 0 else None
            upd = MockUpdate(message=self._msg(
                uid, photo_ids=[fid], caption=cap,
                media_group_id=mg_id, **kw))
            await feat_intake.on_photo(upd, self.ctx(uid))
        await self.drain()

    async def cb(self, uid, data):
        msg = self._msg(uid)
        q = MockCallbackQuery(self.outbox, data, MockUser(uid), msg)
        upd = MockUpdate(callback_query=q)
        await bot.on_callback(upd, self.ctx(uid))
        await self.drain()
        return q

    async def drain(self, n=6):
        for _ in range(n):
            await self._real_sleep(0)

    async def fire_flush(self, uid):
        """Expire the collection buffer and run the real _flush_after."""
        buf = _buffers.get(uid)
        if buf:
            buf["deadline"] = time.time() - 1
        await self._real_flush(uid, self.ctx(uid))
        await self.drain()

    # -- outbox assertions --------------------------------------------
    def texts(self, kind=None):
        return [m["text"] for m in self.outbox
                if kind is None or m["kind"] == kind]

    def last_text(self, kind=None):
        ts = self.texts(kind)
        return ts[-1] if ts else ""

    def buttons(self, kind="edit"):
        """(text, callback_data) of the last keyboard sent via kind."""
        for m in reversed(self.outbox):
            if m["kind"] == kind and m.get("markup") is not None:
                kb = m["markup"].inline_keyboard
                return [(b.text, b.callback_data) for row in kb for b in row]
        return []

    def sent_buttons(self):
        return self.buttons(kind="send")

    # -- fixtures ------------------------------------------------------
    def broker(self, uid=None, phone=None, tier=None):
        uid = uid or self._next_uid()
        db.get_or_create_broker(uid, f"user{uid}", f"User {uid}")
        if phone:
            db.update_broker(uid, phone=phone)
        if tier:
            db.set_tier(uid, tier, days=30)
        # mark all hints seen so existing tests hit handlers directly
        # (hint flow is tested separately in TestHints)
        import hints as _hints
        for _k in _hints.HINTS:
            db.mark_hint_seen(uid, _k)
        return uid

    def listing(self, uid, status="submitted", **parsed):
        p = {"price_vnd": 12000000.0, "bedrooms": 2.0,
             "district": "Sơn Trà", "primary_phone": "0905123456"}
        p.update(parsed)
        lid = db.create_listing(
            uid, raw_text="test", photo_file_ids=["ph1"],
            parsed=p, missing_fields=[], status=status)
        return db.get_listing(lid)


# ---------------------------------------------------------------- tests
class TestFreeformIntake(LinhFlowTest):
    async def test_text_then_photos_then_confirm_then_save(self):
        uid = self.broker(phone="0905123456")
        await self.text(uid, "Cho thuê căn 2PN ở Sơn Trà, 12tr/tháng")
        self.assertIn(uid, _buffers)
        self.assertIn("Đang đợi ảnh", self.last_text("reply"))

        await self.photo(uid, "f1")
        await self.photo(uid, "f2")
        buf = _buffers[uid]
        self.assertEqual(len(buf["photos"]), 2)

        await self.fire_flush(uid)
        self.assertIn("đủ chưa", self.last_text("send"))
        btns = self.sent_buttons()
        self.assertTrue(any(d == "buf:done" for _, d in btns))

        await self.cb(uid, "buf:done")
        confirming = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(confirming)
        lid = confirming["listing_id"]

        await self.cb(uid, f"cfm:hl_done:{lid}")
        btns = self.buttons("edit")
        self.assertTrue(any(d.startswith("cfm:save:") for _, d in btns),
                        f"no save button: {btns}")

        await self.cb(uid, f"cfm:save:{lid}")
        l = db.get_listing(lid)
        self.assertEqual(l["status"], "submitted")
        self.assertEqual(l["parsed"]["bedrooms"], 2.0)
        self.assertEqual(l["parsed"]["price_vnd"], 12000000.0)
        self.assertEqual(len(l["photo_file_ids"]), 2)

    async def test_album_reassembly(self):
        uid = self.broker(phone="0905123456")
        await self.album(uid, ["a1", "a2", "a3"],
                         caption="2PN Sơn Trà 12tr 0905123456")
        buf = _buffers.get(uid)
        self.assertIsNotNone(buf)
        self.assertEqual(len(buf["photos"]), 3)
        self.assertTrue(any("Sơn Trà" in t for t in buf["texts"]))
        self.assertIn("Nhận 3 ảnh", self.last_text("send"))

    async def test_buf_more_extends(self):
        uid = self.broker()
        await self.text(uid, "2PN 12tr")
        await self.fire_flush(uid)
        await self.cb(uid, "buf:more")
        self.assertIn(uid, _buffers)  # still waiting
        self.assertIn("chờ thêm", self.last_text("edit"))


class TestForwardHandling(LinhFlowTest):
    def _fwd_chat(self, title):
        return MockChat(-100123, title=title)

    async def test_forwarded_text_noise_stripped_and_source_noted(self):
        uid = self.broker()
        await self.text(uid, "Cho thuê 2PN 12tr/tháng\n👉 @kenhbds",
                        forward_from_chat=self._fwd_chat("Kênh BĐS"))
        # forward → immediate draft (no buffer wait)
        cfm = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm)
        l = db.get_listing(cfm["listing_id"])
        self.assertNotIn("@kenhbds", l["raw_text"])
        self.assertIn("2PN", l["raw_text"])
        self.assertEqual(cfm["forward_source"], "Kênh BĐS")
        # confirmation replies to the forwarded message
        sent = [m for m in self.outbox if m["kind"] == "send"]
        self.assertTrue(any(m.get("reply_to") for m in sent))

    async def test_forwarded_photo_skips_stray_question(self):
        uid = self.broker()
        # a recent listing exists — non-forward photo would ask "stray?"
        self.listing(uid)
        await self.photo(uid, "ff1",
                         forward_from_chat=self._fwd_chat("Kênh BĐS"))
        self.assertNotIn("stray_photo", self.ctx(uid).user_data)
        # forward → immediate draft (no buffer, no stray prompt)
        cfm = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm)
        l = db.get_listing(cfm["listing_id"])
        self.assertIn("ff1", l["photo_file_ids"])

    async def test_back_to_back_forwards_create_separate_listings(self):
        uid = self.broker()
        await self.text(uid, "Cho thuê 2PN 12tr/tháng An Thượng",
                        forward_from_chat=self._fwd_chat("Kênh BĐS"))
        await self.text(uid, "Cho thuê 3PN 18tr/tháng Sơn Trà",
                        forward_from_chat=self._fwd_chat("Kênh BĐS"))
        # first forward → confirming; second → queued
        cfm = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm)
        l1 = db.get_listing(cfm["listing_id"])
        self.assertIn("2PN", l1["raw_text"])
        q = self.ctx(uid).user_data.get("confirming_queue") or []
        self.assertEqual(len(q), 1)
        l2 = db.get_listing(q[0]["listing_id"])
        self.assertIn("3PN", l2["raw_text"])
        # each confirmation reply threads to its own forward
        self.assertNotEqual(cfm.get("reply_to_message_id"),
                            q[0].get("reply_to_message_id"))

    async def test_forwarded_album_processes_immediately(self):
        uid = self.broker()
        await self.album(uid, ["a1", "a2", "a3"], caption="2PN 12tr An Thượng",
                         forward_from_chat=self._fwd_chat("Kênh BĐS"))
        # album flushed → immediate draft, no manual buffer
        self.assertNotIn(uid, _buffers)
        cfm = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm)
        l = db.get_listing(cfm["listing_id"])
        self.assertEqual(len(l["photo_file_ids"]), 3)

    async def test_duplicate_forward_suggests_not_blocks(self):
        uid = self.broker(phone="0905123456")
        # first forward (album+caption) → draft → confirm → submit
        await self.album(uid, ["dup1"], caption="Cho thuê 2PN 12tr An Thượng",
                         forward_from_chat=self._fwd_chat("Kênh BĐS"))
        cfm1 = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm1)
        await self.cb(uid, f"cfm:save:{cfm1['listing_id']}")
        l1 = db.get_listing(cfm1["listing_id"])
        self.assertEqual(l1["status"], "submitted")
        # second identical forward → draft
        await self.album(uid, ["dup1"], caption="Cho thuê 2PN 12tr An Thượng",
                         forward_from_chat=self._fwd_chat("Kênh BĐS"))
        cfm2 = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(cfm2)
        # confirm second → duplicate suggestion shown (not auto-blocked).
        # Note: the 60s timeout is instant in tests (sleep mocked), so the
        # suggestion is immediately followed by auto-save as new.
        await self.cb(uid, f"cfm:save:{cfm2['listing_id']}")
        texts = [m["text"] for m in self.outbox if m.get("text")]
        self.assertTrue(any("có vẻ giống" in t for t in texts),
                        "duplicate suggestion not shown")
        # timeout defaulted to new listing → submitted (not merged/blocked)
        l2 = db.get_listing(cfm2["listing_id"])
        self.assertEqual(l2["status"], "submitted")

    async def test_manual_input_still_uses_buffer(self):
        uid = self.broker()
        await self.text(uid, "Cho thuê 2PN 12tr/tháng An Thượng")
        buf = _buffers.get(uid)
        self.assertIsNotNone(buf)
        self.assertIn("2PN", buf["texts"][0])

    async def test_stray_photo_asks_for_recent_listing(self):
        uid = self.broker()
        lid = self.listing(uid)["id"]
        await self.photo(uid, "stray1")  # no forward, no buffer
        self.assertIn("stray_photo", self.ctx(uid).user_data)
        self.assertIn("phải không anh", self.last_text("reply"))
        await self.cb(uid, "stray:yes")
        l = db.get_listing(lid)
        self.assertIn("stray1", l["photo_file_ids"])

    async def test_stray_photo_new_listing(self):
        uid = self.broker()
        self.listing(uid)
        await self.photo(uid, "stray2")
        await self.cb(uid, "stray:new")
        self.assertIn(uid, _buffers)
        self.assertEqual(_buffers[uid]["photos"], ["stray2"])


class TestGuidedIntake(LinhFlowTest):
    async def _start_guided(self, uid):
        await self.cb(uid, "menu:new")
        self.assertIn("muốn nhập căn mới kiểu nào", self.last_text("edit"))
        await self.cb(uid, "guided:mode:guided")
        gd = self.ctx(uid).user_data.get("guided")
        self.assertIsNotNone(gd)
        self.assertEqual(gd["step"], 0)
        return gd

    async def test_back_button_and_cancel(self):
        uid = self.broker()
        await self._start_guided(uid)
        await self.cb(uid, "guided:set:bedrooms:2")
        gd = self.ctx(uid).user_data["guided"]
        self.assertEqual(gd["step"], 1)
        await self.cb(uid, "guided:back")
        gd = self.ctx(uid).user_data["guided"]
        self.assertEqual(gd["step"], 0)
        # cancel via text
        await self.text(uid, "huy")
        self.assertNotIn("guided", self.ctx(uid).user_data)

    async def test_huy_command_clears_guided(self):
        uid = self.broker()
        await self._start_guided(uid)
        upd = MockUpdate(message=self._msg(uid, text="/huy"))
        await feat_listings.cmd_cancel_addphoto(upd, self.ctx(uid))
        self.assertNotIn("guided", self.ctx(uid).user_data)

    async def test_full_walkthrough(self):
        uid = self.broker(phone="0905123456")
        await self._start_guided(uid)

        await self.cb(uid, "guided:set:bedrooms:2")
        await self.cb(uid, "guided:set:bathrooms:2")
        await self.cb(uid, "guided:set:ptype:lux_apt")
        await self.text(uid, "12tr")
        await self.text(uid, "65")
        await self.cb(uid, "guided:set:ward:6")  # Ngũ Hành Sơn
        # street: text search the 3682-street catalog
        await self.text(uid, "trần hưng đạo")
        gd = self.ctx(uid).user_data["guided"]
        snames = gd.get("ssearch", {}).get("names", [])
        self.assertTrue(snames, "street search returned nothing")
        await self.cb(uid, "guided:sset:0")
        # landmark: fuzzy search the building catalog
        await self.cb(uid, "guided:set:landmark:custom")
        await self.text(uid, "monarchy")
        gd = self.ctx(uid).user_data["guided"]
        names = gd.get("bsearch", {}).get("names", [])
        self.assertTrue(names, "building search returned nothing")
        await self.cb(uid, "guided:bset:0")
        gd = self.ctx(uid).user_data["guided"]
        self.assertEqual(gd["answers"]["landmark"], names[0])

        await self.cb(uid, "guided:skip")      # building_detail
        await self.text(uid, "5")              # floor
        await self.cb(uid, "guided:set:furnishing:full")
        await self.cb(uid, "guided:set:pet:yes")
        await self.cb(uid, "guided:set:availability:now")
        await self.cb(uid, "guided:set:lease_min:12")
        await self.cb(uid, "guided:set:deposit:2")
        await self.cb(uid, "guided:set:pay_schedule:monthly")
        await self.cb(uid, "guided:amen:pool")
        await self.cb(uid, "guided:amen:gym")
        await self.cb(uid, "guided:amen:done")  # -> photos step

        await self.photo(uid, "gf1")
        buf = _buffers.get(uid)
        self.assertIsNotNone(buf)
        self.assertTrue(buf.get("guided"))
        await self.fire_flush(uid)
        await self.cb(uid, "buf:done")
        gd = self.ctx(uid).user_data.get("guided")
        self.assertIsNotNone(gd)  # still in guided, now description step

        await self.cb(uid, "guided:skip")  # description -> finish
        confirming = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(confirming)
        lid = confirming["listing_id"]
        l = db.get_listing(lid)
        self.assertEqual(l["parsed"]["bedrooms"], 2.0)
        self.assertEqual(l["parsed"]["price_vnd"], 12000000.0)
        self.assertEqual(l["parsed"]["district"], "Ngũ Hành Sơn")
        self.assertEqual(gd["answers"]["landmark"], names[0])

        await self.cb(uid, f"cfm:hl_done:{lid}")
        await self.cb(uid, f"cfm:save:{lid}")
        l = db.get_listing(lid)
        self.assertEqual(l["status"], "submitted")
        self.assertEqual(len(l["photo_file_ids"]), 1)


class TestHighlights(LinhFlowTest):
    async def test_highlights_extracted_and_appended(self):
        uid = self.broker(phone="0905123456")
        await self.text(
            uid, "Cho thuê 2PN view biển trực diện, cách biển 3 phút đi bộ, "
                 "có hồ bơi vô cực, 15tr/tháng")
        await self.photo(uid, "h1")
        await self.fire_flush(uid)
        await self.cb(uid, "buf:done")
        confirming = self.ctx(uid).user_data["confirming"]
        lid = confirming["listing_id"]
        self.assertIn("✨", self.last_text("send"))
        l = db.get_listing(lid)
        hls = (l["parsed"] or {}).get("highlights") or []
        self.assertTrue(any("View biển" in h for h in hls),
                        f"highlights missing view biển: {hls}")

        # broker adds more selling points as free text
        await self.text(uid, "chủ dễ tính, khu yên tĩnh")
        l = db.get_listing(lid)
        hls = (l["parsed"] or {}).get("highlights") or []
        self.assertTrue(any("chủ dễ tính" in h for h in hls),
                        f"appended highlight missing: {hls}")

        await self.cb(uid, f"cfm:hl_done:{lid}")
        await self.cb(uid, f"cfm:save:{lid}")
        self.assertEqual(db.get_listing(lid)["status"], "submitted")


class TestClientPipelinePro(LinhFlowTest):
    async def test_send_track_schedule(self):
        uid = self.broker(phone="0905123456", tier="pro")
        cid = db.create_client(
            uid, name="Anh A", phone="0901111111",
            requirements_raw="2PN Sơn Trà dưới 15tr",
            requirements={"bedrooms": 2.0, "district": "Sơn Trà",
                          "max_price": 15000000.0})
        l1 = self.listing(uid, price_vnd=12000000.0)
        l2 = self.listing(uid, price_vnd=14000000.0)

        # step 1: picker
        await self.cb(uid, f"send2client:start:{cid}")
        self.assertIn("Chọn tin gửi", self.last_text("edit"))
        await self.cb(uid, f"send2client:toggle:{l1['id']}")
        await self.cb(uid, f"send2client:toggle:{l2['id']}")

        # step 2: language picker -> message
        await self.cb(uid, "send2client:done")
        self.assertIn("Chọn ngôn ngữ", self.last_text("edit"))
        await self.cb(uid, "send2client:lang:vi")
        self.assertIn("Anh A", self.last_text("edit"))
        await self.cb(uid, "send2client:copy")
        self.assertTrue(any(m["kind"] == "send" for m in self.outbox))
        await self.cb(uid, "send2client:sent")
        c = db.get_client(cid)
        self.assertEqual(c["status"], "sent")
        self.assertEqual(len(c["sent_listings"]), 2)

        # step 3: followup -> chose
        await self.cb(uid, f"send2client:followup:{cid}")
        self.assertIn("chọn căn nào", self.last_text("edit"))
        await self.cb(uid, f"send2client:chose:{l1['id']}")
        c = db.get_client(cid)
        self.assertEqual(c["status"], "pending_viewing")

        # step 4: datetime -> viewing scheduled
        await self.text(uid, "mai 9h sáng")
        c = db.get_client(cid)
        self.assertEqual(c["status"], "scheduled")
        viewings = db.list_viewings(uid)
        self.assertTrue(viewings)
        self.assertIn(l1["id"], viewings[0]["listing_ids"])


class TestPremiumGating(LinhFlowTest):
    async def test_free_user_blocked_from_send2client(self):
        uid = self.broker()  # free by default
        cid = db.create_client(uid, name="Anh B")
        self.listing(uid)
        await self.cb(uid, f"send2client:start:{cid}")
        self.assertIn("🔒", self.last_text("edit"))
        self.assertNotIn("send2client", self.ctx(uid).user_data)

    async def test_free_user_blocked_from_viewings_menu(self):
        uid = self.broker()
        await self.cb(uid, "menu:viewings")
        self.assertIn("🔒", self.last_text("edit"))

    async def test_pro_user_allowed(self):
        uid = self.broker(tier="pro")
        cid = db.create_client(uid, name="Anh C")
        self.listing(uid)
        await self.cb(uid, f"send2client:start:{cid}")
        self.assertIn("Chọn tin gửi", self.last_text("edit"))

    async def test_requires_tier_matrix(self):
        uid = self.broker()
        self.assertTrue(feat_premium.requires_tier(uid, "followup"))
        self.assertFalse(feat_premium.requires_tier(uid, "send2client"))
        self.assertFalse(feat_premium.requires_tier(uid, "viewings"))
        db.set_tier(uid, "pro", days=30)
        self.assertTrue(feat_premium.requires_tier(uid, "send2client"))
        self.assertTrue(feat_premium.requires_tier(uid, "viewings"))
        self.assertFalse(feat_premium.requires_tier(uid, "broadcast"))
        db.set_tier(uid, "max", days=30)
        self.assertTrue(feat_premium.requires_tier(uid, "broadcast"))


class TestDeletedListings(LinhFlowTest):
    async def test_deleted_hidden_from_write_picker(self):
        uid = self.broker()
        l1 = self.listing(uid)
        l2 = self.listing(uid)
        # write picker only shows listings with saved posts
        db.save_post(l1["id"], "Bài đăng test 1", "vi")
        db.save_post(l2["id"], "Bài đăng test 2", "vi")
        db.set_listing_status(l2["id"], "deleted", changed_by="broker")
        await self.cb(uid, "menu:write")
        btns = self.buttons(kind="edit")
        datas = [d for _, d in btns if d]
        self.assertTrue(any(l1["id"] in d for d in datas))
        self.assertFalse(any(l2["id"] in d for d in datas))

    async def test_deleted_excluded_from_list_query(self):
        uid = self.broker()
        l1 = self.listing(uid)
        l2 = self.listing(uid)
        db.set_listing_status(l2["id"], "deleted", changed_by="broker")
        items = db.list_broker_listings(
            uid, limit=10, statuses=["submitted", "draft", "pending_info",
                                     "rented", "expired"])
        ids = [l["id"] for l in items]
        self.assertIn(l1["id"], ids)
        self.assertNotIn(l2["id"], ids)


class TestHints(LinhFlowTest):
    def _fresh_broker(self):
        """Broker WITHOUT hints marked seen (for hint flow testing)."""
        uid = self._next_uid()
        db.get_or_create_broker(uid, f"user{uid}", f"User {uid}")
        return uid

    async def test_first_tap_shows_hint(self):
        import hints as _hints
        uid = self._fresh_broker()
        self.assertTrue(_hints.should_show_hint(uid, "clients"))
        await self.cb(uid, "menu:clients")
        # hint text shown, not the clients list
        txt = self.last_text("edit")
        self.assertIn("Khách hàng", txt)
        btns = self.buttons(kind="edit")
        datas = [d for _, d in btns if d]
        self.assertTrue(any("hint:go:menu:clients" in d for d in datas))

    async def test_hint_go_proceeds_and_marks_seen(self):
        import hints as _hints
        uid = self._fresh_broker()
        await self.cb(uid, "menu:clients")
        await self.cb(uid, "hint:go:menu:clients")
        # hint marked seen
        self.assertFalse(_hints.should_show_hint(uid, "clients"))
        # now shows the actual clients UI (not hint again)
        txt = self.last_text("edit")
        self.assertNotIn("Đây là nơi quản lý khách thuê", txt)

    async def test_hint_skip_marks_seen_and_goes_to_menu(self):
        import hints as _hints
        uid = self._fresh_broker()
        await self.cb(uid, "menu:clients")
        await self.cb(uid, "hint:skip")
        self.assertFalse(_hints.should_show_hint(uid, "clients"))

    async def test_second_tap_skips_hint(self):
        import hints as _hints
        uid = self._fresh_broker()
        db.mark_hint_seen(uid, "clients")
        await self.cb(uid, "menu:clients")
        txt = self.last_text("edit")
        # goes straight to clients, no hint
        self.assertNotIn("Đây là nơi quản lý khách thuê", txt)

    async def test_proactive_tips(self):
        import hints as _hints
        # 1st listing tip
        self.assertIsNotNone(_hints.tip_after_listing(1))
        # 5th listing tip
        self.assertIsNotNone(_hints.tip_after_listing(5))
        # no tip on 2nd, 3rd, 4th, 6th
        self.assertIsNone(_hints.tip_after_listing(2))
        self.assertIsNone(_hints.tip_after_listing(6))
        # 1st client tip
        self.assertIsNotNone(_hints.tip_after_client(1))
        self.assertIsNone(_hints.tip_after_client(2))


class TestSendClientLanguages(LinhFlowTest):
    async def test_all_languages_generate(self):
        import feat_sendclient as s2c
        c = {"name": "David", "id": "cli:x"}
        listings = [{
            "parsed": {
                "bedrooms": 2.0, "price_vnd": 15000000.0, "area_m2": 75,
                "building_name": "The Monarchy", "street": "Trần Hưng Đạo",
                "district": "Sơn Trà", "furnishing": "full",
                "property_type": "apartment",
                "highlights": ["View biển"],
            }}]
        for lang in ["vi", "en", "ko", "zh", "ru"]:
            msg = s2c._build_client_message(c, listings, "anh", lang)
            self.assertTrue(len(msg) > 50, f"{lang} too short")
        # vi unchanged
        vi = s2c._build_client_message(c, listings, "anh", "vi")
        self.assertIn("Chào David!", vi)
        self.assertIn("2PN", vi)
        # en content
        en = s2c._build_client_message(c, listings, "anh", "en")
        self.assertIn("Hi David!", en)
        self.assertIn("2BR", en)
        self.assertIn("apartment", en)
        # ko content
        ko = s2c._build_client_message(c, listings, "anh", "ko")
        self.assertIn("안녕하세요 David님!", ko)
        # zh content
        zh = s2c._build_client_message(c, listings, "anh", "zh")
        self.assertIn("您好David！", zh)
        # ru content + plural
        ru = s2c._build_client_message(c, listings, "anh", "ru")
        self.assertIn("Здравствуйте, David!", ru)
        self.assertIn("вариант", ru)
        ru5 = s2c._build_client_message(c, listings * 5, "anh", "ru")
        self.assertIn("вариантов", ru5)

    async def test_lang_picker_flow(self):
        uid = self.broker(phone="0905123456", tier="pro")
        cid = db.create_client(uid, name="Kim", phone="0901111111",
                               requirements_raw="test")
        l1 = self.listing(uid, price_vnd=12000000.0)
        await self.cb(uid, f"send2client:start:{cid}")
        await self.cb(uid, f"send2client:toggle:{l1['id']}")
        # done -> language picker
        await self.cb(uid, "send2client:done")
        self.assertIn("Chọn ngôn ngữ", self.last_text("edit"))
        btns = self.buttons(kind="edit")
        datas = [d for _, d in btns if d]
        self.assertTrue(any("send2client:lang:ko" in d for d in datas))
        # pick Korean -> message in Korean
        await self.cb(uid, "send2client:lang:ko")
        self.assertIn("안녕하세요", self.last_text("edit"))
        # change language back via the button
        await self.cb(uid, "send2client:done")
        await self.cb(uid, "send2client:lang:en")
        self.assertIn("Hi Kim!", self.last_text("edit"))


class TestReferral(LinhFlowTest):
    """Broker invite system: 3 qualified invitees -> 1 month Pro."""

    def _qualifying_listing(self, uid, age_days=8):
        """A listing that counts toward referral qualification."""
        p = {"price_vnd": 12000000.0, "bedrooms": 2.0, "bathrooms": 2.0,
             "district": "Sơn Trà", "primary_phone": "0905123456",
             "description": "x" * 60, "street": "An Thượng 32",
             "amenities": ["hồ bơi", "gym"], "building_name": "Monarchy",
             "property_type": "apartment"}
        lid = db.create_listing(
            uid, raw_text="Cho thuê 2PN 12tr LH 0905123456",
            photo_file_ids=["ph1", "ph2", "ph3"],
            parsed=p, missing_fields=[], status="submitted")
        # backdate past the 7-day minimum
        conn = db.connect()
        conn.execute("UPDATE tg_listings SET created_at = ? WHERE id = ?",
                     (time.time() - age_days * 86400, lid))
        conn.commit()
        conn.close()
        return lid

    def test_create_referral_idempotent(self):
        a = self.broker()
        b = self.broker()
        r1 = db.create_referral(a, b)
        r2 = db.create_referral(a, b)
        self.assertIsNotNone(r1)
        self.assertEqual(r1["id"], r2["id"])
        # self-referral + unknown inviter blocked
        self.assertIsNone(db.create_referral(a, a))
        self.assertIsNone(db.create_referral(999999, b))

    def test_progress_and_qualification(self):
        inviter = self.broker()
        invitees = [self.broker() for _ in range(3)]
        for ie in invitees:
            db.create_referral(inviter, ie)
        prog = db.get_referral_progress(inviter)
        self.assertEqual(prog, {"invited": 3, "qualified": 0, "needed": 3})
        # one invitee makes 5 quality listings -> qualifies
        for _ in range(5):
            self._qualifying_listing(invitees[0])
        ok, n = db.check_invitee_qualified(invitees[0])
        self.assertTrue(ok)
        self.assertEqual(n, 5)
        db.mark_qualified(invitees[0])
        prog = db.get_referral_progress(inviter)
        self.assertEqual(prog["qualified"], 1)
        # not enough listings -> not qualified
        self._qualifying_listing(invitees[1])
        ok, _ = db.check_invitee_qualified(invitees[1])
        self.assertFalse(ok)

    def test_reward_grant_and_cap(self):
        import feat_referral  # noqa
        inviter = self.broker()
        for _ in range(3):
            ie = self.broker()
            db.create_referral(inviter, ie)
            for _ in range(5):
                self._qualifying_listing(ie)
            db.mark_qualified(ie)
        exp = db.maybe_grant_inviter_reward(inviter)
        self.assertIsNotNone(exp)
        self.assertGreater(exp, time.time())
        self.assertEqual(db.get_tier(inviter), "pro")
        # no double-grant for the same milestone
        self.assertIsNone(db.maybe_grant_inviter_reward(inviter))
        # below threshold -> nothing
        inviter2 = self.broker()
        ie = self.broker()
        db.create_referral(inviter2, ie)
        self.assertIsNone(db.maybe_grant_inviter_reward(inviter2))

    def test_phone_duplicate_fraud(self):
        inviter = self.broker(phone="0901111222")
        invitee = self.broker()
        db.create_referral(inviter, invitee)
        db.create_listing(invitee, raw_text="Cho thuê 0901111222",
                          photo_file_ids=["x"], parsed={}, status="draft")
        self.assertTrue(db.check_phone_duplicate(invitee, inviter))
        ref = db.get_referral_by_invitee(invitee)
        self.assertEqual(ref["fraud_flag"], 1)
        self.assertEqual(ref["fraud_reason"], "duplicate_phone")
        # fraud referrals don't count toward progress
        prog = db.get_referral_progress(inviter)
        self.assertEqual(prog["qualified"], 0)

    def test_behavior_warning(self):
        ie = self.broker()
        for _ in range(5):
            self.listing(ie)  # all created now -> within 24h of signup
        w = db.check_behavior_pattern(ie)
        self.assertIsNotNone(w)
        self.assertIn("suspicious", w)

    async def test_moi_command(self):
        import feat_referral  # noqa
        uid = self.broker()
        upd = MockUpdate(message=self._msg(uid, text="/moi"))
        await feat_referral.cmd_moi(upd, self.ctx(uid))
        self.assertIn("Mời bạn", self.last_text())
        self.assertIn("0/3", self.last_text())

    async def test_start_referral_hook(self):
        import feat_referral  # noqa
        inviter = self.broker()
        new_uid = 777001
        db.get_or_create_broker(new_uid, "newbie", "Newbie")
        upd = MockUpdate(message=self._msg(new_uid, text="/start"))
        ctx = self.ctx(new_uid)
        ctx.args = [f"ref_{inviter}"]
        got = feat_referral.parse_start_referral(upd, ctx)
        self.assertEqual(got, inviter)
        ref = db.get_referral_by_invitee(new_uid)
        self.assertIsNotNone(ref)
        self.assertEqual(ref["inviter_id"], inviter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
