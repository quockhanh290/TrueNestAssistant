"""Regression tests for the HIGH-severity fixes (premium, time zone, share
penalties, pending-step cleanup, silent menu crashes, outbox queue, stale
save button, guided photo step).

Reuses the mocked-Telegram harness of tests/test_flows.py (fresh temp DB per
test; BOT_DB_PATH is pointed at a temp dir before anything imports config).

Run:  python -m pytest tests/test_high_fixes.py -q
"""
import asyncio
import datetime as _dt
import os
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_flows as tf  # noqa: E402  (sets BOT_DB_PATH, imports bot)
from test_flows import (  # noqa: E402
    LinhFlowTest, MockCallbackQuery, MockUpdate, MockUser, MockChat,
    MockMessage, MockContext,
)

import bot  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import feat_premium  # noqa: E402

DAY = 86400
ADMIN = 999001


class AdminMixin:
    async def approve(self, *args):
        """Admin types /approve <args>."""
        msg = self._msg(ADMIN, text="/approve " + " ".join(args))
        upd = MockUpdate(message=msg)
        ctx = self.ctx(ADMIN)
        ctx.args = list(args)
        with patch.object(config, "ADMIN_TELEGRAM_ID", ADMIN):
            await feat_premium.cmd_approve(upd, ctx)
        await self.drain()


# =============================================================== 1. premium
class TestPremiumApproval(AdminMixin, LinhFlowTest):
    async def test_approve_grants_the_tier_the_admin_typed(self):
        uid = self.broker()
        db.get_or_create_broker(ADMIN, "admin", "Admin")
        db.create_premium_request(uid, tier_requested="pro")
        await self.approve(str(uid), "max")
        self.assertEqual(db.get_tier(uid), "max")
        req = db.list_pending_premium_requests()
        self.assertEqual(req, [], "the pending request must be closed")

    async def test_approve_grants_thirty_days_exactly_once(self):
        uid = self.broker()
        db.create_premium_request(uid, tier_requested="pro")
        before = time.time()
        await self.approve(str(uid), "pro")
        exp = db.get_broker(uid)["tier_expires_at"]
        self.assertAlmostEqual(exp, before + 30 * DAY, delta=120)

    async def test_paid_button_carries_the_chosen_tier(self):
        uid = self.broker()
        await self.cb(uid, "premium:want:max")
        paid = [d for _, d in self.buttons("edit")
                if d and d.startswith("premium:paid")]
        self.assertEqual(paid, ["premium:paid:max"])
        # bot restarted between the two taps: user_data is gone
        self.ctx(uid).user_data.clear()
        await self.cb(uid, "premium:paid:max")
        req = db.get_pending_premium_request(uid)
        self.assertIsNotNone(req)
        self.assertEqual(req["tier_requested"], "max")

    async def test_early_renewal_keeps_the_days_still_left(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        old_exp = db.get_broker(uid)["tier_expires_at"]
        db.create_premium_request(uid, tier_requested="pro")
        await self.approve(str(uid), "pro")
        exp = db.get_broker(uid)["tier_expires_at"]
        self.assertAlmostEqual(exp, old_exp + 30 * DAY, delta=120)

    async def test_renewal_after_expiry_starts_from_now(self):
        uid = self.broker()
        db.update_broker(uid, tier="pro", tier_expires_at=time.time() - 5 * DAY)
        db.create_premium_request(uid, tier_requested="pro")
        before = time.time()
        await self.approve(str(uid), "pro")
        exp = db.get_broker(uid)["tier_expires_at"]
        self.assertAlmostEqual(exp, before + 30 * DAY, delta=120)

    async def test_setting_free_tier_does_not_crash(self):
        uid = self.broker(tier="pro")
        db.set_tier(uid, "free", days=0)
        self.assertEqual(db.get_tier(uid), "free")


# ============================================================ 2. time zone
VN = _dt.timezone(_dt.timedelta(hours=7))   # independent reference clock


def vn_epoch(y, mo, d, h=0, mi=0):
    return _dt.datetime(y, mo, d, h, mi, tzinfo=VN).timestamp()


def frozen_vn_now(y, mo, d, h, mi=0):
    """A replacement for db.vntime.now() pinned to a Vietnam wall clock."""
    fixed = _dt.datetime(y, mo, d, h, mi, tzinfo=VN)
    return lambda: fixed


class TestVietnamTime(LinhFlowTest):
    """All expectations are absolute epochs computed with a fixed UTC+7
    clock, so they hold on any host zone (the host here is Calgary)."""

    async def test_picked_viewing_slot_is_stored_as_vietnam_time(self):
        uid = self.broker(tier="pro")
        l = self.listing(uid, status="active")
        cid = db.create_client(uid, name="Khách A")
        self.ctx(uid).user_data["scheduling"] = {
            "client_id": cid, "client_name": "Khách A",
            "listing_ids": [l["id"]], "date": "20261020", "time": "1500"}
        await self.cb(uid, "vw:ok")
        vs = db.list_viewings(uid, upcoming_only=False)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["scheduled_at"], vn_epoch(2026, 10, 20, 15, 0))

    async def test_typed_viewing_time_is_read_as_vietnam_time(self):
        import feat_sendclient
        from db import vntime
        with patch.object(vntime, "now", frozen_vn_now(2026, 10, 20, 8, 0)):
            ts = feat_sendclient.parse_vn_datetime("mai 9h sáng")
        self.assertEqual(ts, vn_epoch(2026, 10, 21, 9, 0))

    async def test_viewing_time_is_shown_in_vietnam_time(self):
        import feat_sendclient
        import feat_viewings
        ts = vn_epoch(2026, 10, 20, 15, 0)   # a Tuesday
        self.assertEqual(feat_sendclient.fmt_sched(ts), "Thứ 3, 20/10 lúc 15:00")
        self.assertEqual(feat_viewings._fmt_sched(ts), "Thứ 3, 20/10 lúc 15:00")

    async def test_date_picker_today_follows_the_vietnam_date(self):
        import feat_viewings
        from db import vntime
        # 06:30 on 21/10 in Vietnam = still 20/10 in Calgary
        with patch.object(vntime, "now", frozen_vn_now(2026, 10, 21, 6, 30)):
            days = feat_viewings._next_days(2)
            label = feat_viewings._date_label("20261021")
        self.assertEqual(days[0][0], "20261021")
        self.assertTrue(days[0][1].startswith("Hôm nay 21/10"), days[0][1])
        self.assertTrue(label.startswith("Hôm nay"), label)

    async def test_commission_month_starts_at_vietnam_midnight(self):
        import feat_deals
        from db import vntime
        start, end = feat_deals._month_bounds("202610")
        self.assertEqual(start, vn_epoch(2026, 10, 1))
        self.assertEqual(end, vn_epoch(2026, 11, 1))
        # 06:00 on 1/11 in Vietnam is already November
        with patch.object(vntime, "now", frozen_vn_now(2026, 11, 1, 6, 0)):
            self.assertEqual(feat_deals._cur_yyyymm(), "202611")


# ===================================================== 3. share-link penalty
class TestShareReportPenalty(LinhFlowTest):
    """A public share link must not be able to stack penalties."""

    def _setup(self, n_listings=1):
        uid = self.broker(tier="pro")
        ls = [self.listing(uid, status="active") for _ in range(n_listings)]
        for l in ls:
            db.log_refresh_claim(l["id"], uid, "available")
        token = db.create_share_page(uid, [l["id"] for l in ls])
        return uid, ls, token

    async def run_outbox(self):
        import feat_match
        await feat_match.process_outbox_notifications(self.ctx(0))

    def strikes(self, uid):
        conn = sqlite3.connect(os.environ["BOT_DB_PATH"])
        try:
            row = conn.execute("SELECT false_refresh_reports FROM brokers"
                               " WHERE user_id = ?", (uid,)).fetchone()
            return row[0] or 0
        finally:
            conn.close()

    async def test_repeated_reports_from_one_link_penalize_once(self):
        from webapp import share
        uid, ls, token = self._setup()
        for _ in range(3):
            body, status = share.handle_report(
                token, {"listing_id": ls[0]["id"], "reason": "rented"})
            self.assertEqual(status, 200)       # the client still gets OK
        await self.run_outbox()
        self.assertEqual(self.strikes(uid), 1)
        self.assertIsNone(db.get_refresh_cooldown(uid))

    async def test_one_link_cannot_ban_by_reporting_every_listing(self):
        from webapp import share
        uid, ls, token = self._setup(n_listings=3)
        for l in ls:
            share.handle_report(token, {"listing_id": l["id"],
                                        "reason": "rented"})
        await self.run_outbox()
        self.assertEqual(self.strikes(uid), 1)
        self.assertIsNone(db.get_refresh_cooldown(uid))

    async def test_reports_from_different_links_still_penalize(self):
        """The penalty mechanism itself stays: three separate links whose
        reports contradict a fresh 'available' claim still add up to a ban."""
        from webapp import share
        uid, ls, _ = self._setup()
        for _ in range(3):
            tok = db.create_share_page(uid, [ls[0]["id"]])
            share.handle_report(tok, {"listing_id": ls[0]["id"],
                                      "reason": "rented"})
        await self.run_outbox()
        self.assertEqual(self.strikes(uid), 3)
        self.assertIsNotNone(db.get_refresh_cooldown(uid))


# ======================================================== 6. outbox queue
class TestOutboxQueue(LinhFlowTest):
    async def test_undeliverable_rows_do_not_block_the_queue(self):
        import feat_match
        uid = self.broker()
        # 20 'slot reopened' rows that can never be delivered (no request,
        # no broker group configured) sit at the head of the queue
        for _ in range(20):
            db.queue_notification("slot_reopened", None, {"summary": "x"})
        time.sleep(0.01)
        db.queue_notification("premium_request", None,
                              {"broker_id": uid, "tier": "max",
                               "request_id": "pr:1"})
        with patch.object(config, "ADMIN_TELEGRAM_ID", ADMIN), \
                patch.object(config, "BROKER_GROUP_ID", ""):
            for _ in range(3):      # three poller ticks (90 s in prod)
                await feat_match.process_outbox_notifications(self.ctx(0))
        to_admin = [m for m in self.outbox
                    if m["kind"] == "send" and m.get("chat_id") == ADMIN]
        self.assertEqual(len(to_admin), 1, "premium DM must reach the admin")
        self.assertEqual(db.pop_unsent_notifications(), [])

    async def test_a_group_send_failure_does_not_wedge_the_row_forever(self):
        import feat_match
        uid = self.broker()
        cid = db.create_client(uid, name="K")
        mr = db.create_match_request(uid, cid, "2PN Sơn Trà")
        db.queue_notification("slot_reopened", mr, {"summary": "2PN"})
        ctx = self.ctx(0)

        async def boom(*a, **k):
            raise RuntimeError("bot was kicked from the group")
        with patch.object(config, "BROKER_GROUP_ID", "-100123"), \
                patch.object(ctx.bot, "send_message", boom):
            await feat_match.process_outbox_notifications(ctx)
        self.assertEqual(db.pop_unsent_notifications(), [])


# =================================================== 5. silent menu crashes
class FrozenCallbackQuery(MockCallbackQuery):
    """Like PTB 21.6: assigning an attribute after creation raises."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"Attribute `{name}` of class `CallbackQuery` can't be set!")
        object.__setattr__(self, name, value)


class FrozenMixin:
    async def fcb(self, uid, data):
        """Tap a button with a PTB-like frozen callback query."""
        msg = self._msg(uid)
        q = FrozenCallbackQuery(self.outbox, data, MockUser(uid), msg)
        await bot.on_callback(MockUpdate(callback_query=q), self.ctx(uid))
        await self.drain()
        return q

    def menu_buttons(self):
        from utils import MENU_KB
        out = [b.callback_data for row in MENU_KB.inline_keyboard
               for b in row if b.callback_data]
        self.assertGreaterEqual(len(out), 9)
        return out


class TestMenuButtonsAnswer(FrozenMixin, LinhFlowTest):
    async def test_first_time_hint_start_button_opens_the_feature(self):
        uid = self._next_uid()
        db.get_or_create_broker(uid, "u", "U")       # hints NOT seen yet
        await self.fcb(uid, "menu:clients")
        self.assertIn("hint:go:menu:clients",
                      [d for _, d in self.buttons("edit")])
        await self.fcb(uid, "hint:go:menu:clients")
        self.assertIn("clients", db.get_seen_hints(uid))
        self.assertNotIn("Bắt đầu", self.last_text("edit"))

    async def test_every_main_menu_button_answers_free_and_pro(self):
        for tier in (None, "pro", "max"):
            uid = self.broker(tier=tier)
            for data in self.menu_buttons():
                before = len(self.outbox)
                try:
                    await self.fcb(uid, data)
                except Exception as e:  # noqa: BLE001
                    self.fail(f"{data} ({tier or 'free'}) crashed: {e!r}")
                self.assertGreater(len(self.outbox), before,
                                   f"{data} ({tier or 'free'}) said nothing")

    async def test_every_first_time_hint_start_button_answers(self):
        import hints
        for data in hints.MENU_HINT_MAP:
            uid = self._next_uid()
            db.get_or_create_broker(uid, "u", "U")
            db.set_tier(uid, "max", days=30)
            before = len(self.outbox)
            try:
                await self.fcb(uid, "hint:go:" + data)
            except Exception as e:  # noqa: BLE001
                self.fail(f"hint:go:{data} crashed: {e!r}")
            self.assertGreater(len(self.outbox), before, data)

    async def test_commission_button_shows_this_month(self):
        uid = self.broker(tier="pro")
        await self.fcb(uid, "menu:deals")
        self.assertIn("THÁNG", self.last_text("edit"))

    async def test_viewing_and_template_buttons_are_routed(self):
        uid = self.broker(tier="pro")
        self.ctx(uid).user_data["scheduling"] = {"listing_ids": []}
        await self.fcb(uid, "vw:no")
        self.assertIn("hủy", self.last_text("edit").lower())
        self.assertNotIn("scheduling", self.ctx(uid).user_data)
        await self.fcb(uid, "tpl:list")
        self.assertTrue(self.last_text("edit"))


class TestErrorHandler(LinhFlowTest):
    async def test_error_is_logged_and_the_user_gets_a_short_reply(self):
        uid = self.broker()
        msg = self._msg(uid)
        q = MockCallbackQuery(self.outbox, "menu:x", MockUser(uid), msg)
        upd = MockUpdate(callback_query=q)
        ctx = self.ctx(uid)
        try:
            raise ValueError("boom-xyz")
        except ValueError as e:
            ctx.error = e
        with self.assertLogs("linh", level="ERROR") as cm:
            await bot.on_error(upd, ctx)
        self.assertTrue(any("boom-xyz" in line for line in cm.output))
        sent = [m for m in self.outbox if m.get("chat_id") == uid]
        self.assertEqual(len(sent), 1)
        self.assertLess(len(sent[0]["text"]), 200)

    async def test_error_handler_survives_updates_without_a_chat(self):
        ctx = self.ctx(1)
        ctx.error = RuntimeError("job failed")
        with self.assertLogs("linh", level="ERROR"):
            await bot.on_error(None, ctx)

    async def test_main_registers_the_error_handler(self):
        registered = []

        class FakeJobQueue:
            def run_repeating(self, *a, **k):
                pass

        class FakeApp:
            job_queue = FakeJobQueue()

            def add_handler(self, *a, **k):
                pass

            def add_error_handler(self, cb, *a, **k):
                registered.append(cb)

            def run_polling(self, *a, **k):
                pass

        class FakeBuilder:
            def token(self, *_):
                return self

            def build(self):
                return FakeApp()

        class FakeApplication:
            @staticmethod
            def builder():
                return FakeBuilder()

        with patch.object(bot, "Application", FakeApplication), \
                patch.object(bot, "_single_instance_lock", lambda: None), \
                patch.object(config, "BOT_TOKEN", "x"):
            bot.main()
        self.assertEqual(registered, [bot.on_error])


# ======================================================= 4. pending steps
# Every user_data key that on_text / on_photo consults to decide that the
# next message belongs to an unfinished step. Written out by hand from the
# routing in bot.on_text (not imported from the code under test).
TEXT_HIJACKING_STEPS = (
    "onboarding", "onboarding2", "editing_contact", "editing_post",
    "confirming", "confirming_queue", "awaiting", "editing",
    "adding_client", "adding_note", "editing_client", "adding_deal",
    "refresh_discount", "adding_template", "relaying", "client_extra_req",
    "viewing_feedback", "send2client", "guided", "adding_photos",
    "photo_delete", "scheduling",
)

LISTING_PASTE = ("Cho thuê căn hộ 2PN Sơn Trà, full nội thất, view biển, "
                 "giá 8tr/tháng, LH 0905123456")


class PendingMixin:
    def arm_everything(self, uid):
        ud = self.ctx(uid).user_data
        for k in TEXT_HIJACKING_STEPS:
            ud[k] = {"armed": True}
        tf._buffers[uid] = {"texts": ["old"], "photos": [], "chat_id": uid,
                            "deadline": time.time() + 60}

    def assert_nothing_pending(self, uid, keep_guided=False):
        # plain navigation keeps a guided intake on purpose (review round:
        # its answers exist nowhere else); /start, /huy, menu:new drop it
        ud = self.ctx(uid).user_data
        left = [k for k in TEXT_HIJACKING_STEPS if k in ud
                and not (keep_guided and k == "guided")]
        self.assertEqual(left, [], "steps still waiting for input")
        self.assertNotIn(uid, tf._buffers, "old collection buffer kept")

    def client(self, uid, name="Khách A"):
        return db.create_client(uid, name=name)

    def deals(self, uid):
        return db.list_deals(uid)


class TestPendingStepsAreReleased(PendingMixin, LinhFlowTest):
    async def test_huy_command_releases_every_pending_step(self):
        import feat_listings
        uid = self.broker()
        self.arm_everything(uid)
        upd = MockUpdate(message=self._msg(uid, text="/huy"))
        await feat_listings.cmd_cancel_addphoto(upd, self.ctx(uid))
        self.assert_nothing_pending(uid)

    async def test_start_command_releases_every_pending_step(self):
        # phone + pronoun set: otherwise /start (by design) opens its own
        # fresh onboarding step right after clearing the old ones
        uid = self.broker(phone="0905123456")
        db.update_broker(uid, pronoun="anh")
        self.arm_everything(uid)
        ctx = self.ctx(uid)
        ctx.args = []
        await bot.cmd_start(MockUpdate(message=self._msg(uid, text="/start")),
                            ctx)
        self.assert_nothing_pending(uid)

    async def test_menu_command_releases_every_pending_step(self):
        uid = self.broker()
        self.arm_everything(uid)
        await bot.cmd_menu(MockUpdate(message=self._msg(uid, text="/menu")),
                           self.ctx(uid))
        self.assert_nothing_pending(uid, keep_guided=True)

    async def test_every_main_menu_button_releases_pending_steps(self):
        uid = self.broker(tier="max")
        menu = [cb for _, cb in self.menu_kb_buttons()
                if cb and cb.startswith("menu:")]
        self.assertGreaterEqual(len(menu), 9)
        for data in menu:
            self.arm_everything(uid)
            await self.cb(uid, data)
            with self.subTest(button=data):
                self.assert_nothing_pending(
                    uid, keep_guided=(data != "menu:new"))

    def menu_kb_buttons(self):
        return [(b.text, b.callback_data)
                for row in bot.MENU_KB.inline_keyboard for b in row]

    async def test_cancelled_client_note_does_not_eat_the_next_message(self):
        uid = self.broker()
        cid = self.client(uid)
        await self.cb(uid, f"client:note:{cid}")
        self.assertIn("adding_note", self.ctx(uid).user_data)
        cancel = [d for t, d in self.buttons("edit") if "Hủy" in t]
        self.assertEqual(len(cancel), 1)
        await self.cb(uid, cancel[0])
        await self.text(uid, LISTING_PASTE)
        self.assertFalse(db.get_client(cid).get("notes"),
                         "the pasted listing was saved as a client note")

    async def test_cancel_buttons_release_their_step(self):
        uid = self.broker(tier="max")
        cid = self.client(uid)
        cases = [
            ("adding_deal", "cms:cur"),
            ("send2client", f"client:{cid}:0:a:a"),
            ("editing_client", f"client:{cid}:0:a:a"),
            ("adding_note", f"client:{cid}:0:a:a"),
            ("client_extra_req", f"client:{cid}:0:a:a"),
            ("adding_client", "clients:cancel"),
            ("adding_template", "tpl:list:-"),
            ("refresh_discount", "rf:skip:"),
            ("scheduling", "vw:no"),
            ("confirming", "menu:back"),
            ("awaiting", "menu:back"),
            ("confirming_queue", "menu:back"),
        ]
        for key, cancel in cases:
            ud = self.ctx(uid).user_data
            ud[key] = {"client_id": cid, "awaiting_dt": True,
                       "listing_id": "tg:none"}
            await self.cb(uid, cancel)
            with self.subTest(step=key, button=cancel):
                self.assertNotIn(key, ud)

    async def test_auto_commission_skip_button_is_routed(self):
        uid = self.broker()
        self.ctx(uid).user_data["adding_deal"] = {"client_id": "x"}
        q = await self.cb(uid, "deal:skip_auto")
        self.assertTrue(q.answered)
        self.assertNotIn("adding_deal", self.ctx(uid).user_data)
        self.assertIn("Hoa hồng", self.last_text("edit"))

    async def test_commission_step_does_not_swallow_a_pasted_listing(self):
        uid = self.broker()
        cid = self.client(uid)
        self.ctx(uid).user_data["adding_deal"] = {
            "client_id": cid, "listing_id": None, "client_name": "Khách A"}
        await self.text(uid, LISTING_PASTE)
        self.assertEqual(self.deals(uid), [],
                         "the listing's 8tr was booked as a commission")
        self.assertNotIn("adding_deal", self.ctx(uid).user_data)
        self.assertIn(uid, tf._buffers,
                      "the pasted listing should start a new listing")

    async def test_commission_step_still_takes_a_short_amount(self):
        uid = self.broker()
        cid = self.client(uid)
        self.ctx(uid).user_data["adding_deal"] = {
            "client_id": cid, "listing_id": None, "client_name": "Khách A"}
        await self.text(uid, "15tr")
        deals = self.deals(uid)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["commission_vnd"], 15_000_000)

    async def test_viewing_feedback_can_be_cancelled_by_button(self):
        uid = self.broker(tier="max")
        cid = self.client(uid)
        lid = self.listing(uid)["id"]
        vid = db.create_viewing(uid, client_id=cid, client_name="Khách A",
                                listing_ids=[lid],
                                scheduled_at=time.time() - DAY)
        await self.cb(uid, f"vw:fb:{vid}")
        self.assertIn("viewing_feedback", self.ctx(uid).user_data)
        cancel = [d for t, d in self.buttons("edit") if "Hủy" in t]
        self.assertEqual(len(cancel), 1, "feedback prompt has no cancel")
        await self.cb(uid, cancel[0])
        self.assertNotIn("viewing_feedback", self.ctx(uid).user_data)


# ================================================ 7. stale "save" button
class TestStaleSaveButton(LinhFlowTest):
    def draft(self, uid, status="draft"):
        return self.listing(uid, status=status)["id"]

    def confirm(self, uid, lid):
        self.ctx(uid).user_data["confirming"] = {"listing_id": lid}

    def status(self, lid):
        return db.get_listing(lid)["status"]

    async def test_pressing_save_again_says_already_saved(self):
        uid = self.broker(phone="0905123456")
        lid = self.draft(uid)
        self.confirm(uid, lid)
        await self.cb(uid, f"cfm:save:{lid}")
        self.assertEqual(self.status(lid), "submitted")
        n_out = len(self.outbox)
        await self.cb(uid, f"cfm:save:{lid}")
        self.assertIn("đã lưu rồi", self.last_text("edit").lower())
        self.assertNotIn("Nhập tiếp", " ".join(self.texts()[n_out:]))
        self.assertEqual(self.ctx(uid).user_data.get("batch_import"), [lid])

    async def test_old_save_button_does_not_steal_the_current_draft(self):
        uid = self.broker(phone="0905123456")
        old = self.draft(uid, status="submitted")
        cur = self.draft(uid)
        self.confirm(uid, cur)
        await self.cb(uid, f"cfm:save:{old}")
        self.assertEqual(self.ctx(uid).user_data.get("confirming"),
                         {"listing_id": cur})
        self.assertEqual(self.status(cur), "draft")
        self.assertIn("đã lưu rồi", self.last_text("edit").lower())

    async def test_old_save_button_does_not_revive_a_rented_listing(self):
        uid = self.broker(phone="0905123456")
        lid = self.draft(uid, status="rented")
        await self.cb(uid, f"cfm:save:{lid}")
        self.assertEqual(self.status(lid), "rented")

    async def test_queued_draft_button_waits_for_the_current_one(self):
        uid = self.broker(phone="0905123456")
        cur, queued = self.draft(uid), self.draft(uid)
        self.confirm(uid, cur)
        self.ctx(uid).user_data["confirming_queue"] = [{"listing_id": queued}]
        await self.cb(uid, f"cfm:save:{queued}")
        self.assertEqual(self.status(queued), "draft")
        self.assertEqual(self.ctx(uid).user_data.get("confirming"),
                         {"listing_id": cur})

    async def test_save_button_for_another_brokers_listing_is_refused(self):
        owner = self.broker(phone="0905123456")
        other = self.broker(phone="0905999999")
        lid = self.draft(owner)
        self.confirm(owner, lid)
        await self.cb(other, f"cfm:save:{lid}")
        self.assertEqual(self.status(lid), "draft")


# ================================================ 8. guided photo step
class TestGuidedPhotoStep(LinhFlowTest):
    async def to_photo_step(self, uid):
        import feat_intake
        await self.cb(uid, "menu:new")
        await self.cb(uid, "guided:mode:guided")
        gd = self.ctx(uid).user_data["guided"]
        gd["step"] = feat_intake.GUIDED_STEPS.index("amenities")
        await self.cb(uid, "guided:amen:done")
        self.assertEqual(feat_intake.GUIDED_STEPS[gd["step"]], "photos")
        self.assertTrue(tf._buffers[uid].get("guided"))
        return gd

    async def test_photo_step_waits_longer_than_five_seconds(self):
        import feat_intake
        uid = self.broker(phone="0905123456")
        gd = await self.to_photo_step(uid)
        await self.fire_flush(uid)          # 5 s pass, no photo yet
        self.assertIn(uid, tf._buffers, "guided photo buffer was dropped")
        await self.photo(uid, "late1")      # broker finally sends a photo
        self.assertTrue(tf._buffers[uid].get("guided"))
        await self.fire_flush(uid)
        self.assertIn("gửi đủ chưa", self.last_text("send"))
        await self.cb(uid, "buf:done")
        self.assertEqual(gd["answers"].get("photos"), ["late1"])
        self.assertEqual(feat_intake.GUIDED_STEPS[gd["step"]], "description")

    async def test_first_late_photo_restarts_the_wait_timer(self):
        import feat_intake
        uid = self.broker(phone="0905123456")
        await self.to_photo_step(uid)
        await self.fire_flush(uid)
        started = []

        async def _record(u, c):
            started.append(u)
        with patch.object(feat_intake, "_flush_after", _record):
            await self.photo(uid, "late1")
            await self.photo(uid, "late2")
        self.assertTrue(tf._buffers[uid].get("guided"))
        self.assertEqual(tf._buffers[uid]["photos"], ["late1", "late2"])
        self.assertEqual(started, [uid],
                         "nobody would ever ask 'đủ chưa?' for late photos")

    async def test_photo_step_offers_no_photo_continue(self):
        import feat_intake
        uid = self.broker(phone="0905123456")
        gd = await self.to_photo_step(uid)
        btn = [d for t, d in self.buttons("edit") if "Không có ảnh" in t]
        self.assertEqual(len(btn), 1, "photo step has no 'no photo' button")
        await self.cb(uid, btn[0])
        self.assertEqual(feat_intake.GUIDED_STEPS[gd["step"]], "description")
        self.assertNotIn(uid, tf._buffers)
        self.assertIn("thông tin gì thêm", self.last_text("edit"))


# ======================================= missing names (found on the way)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNoMissingNames(LinhFlowTest):
    """Five crashes found while fixing the list above were all one kind: a
    name used but never imported (only hit at run time, on one branch)."""

    def test_no_bot_module_uses_an_undefined_name(self):
        try:
            from pyflakes import api as pf_api, reporter as pf_rep
        except ImportError:
            self.skipTest("pyflakes not installed")
        import glob
        import io
        files = (glob.glob(os.path.join(ROOT, "*.py"))
                 + glob.glob(os.path.join(ROOT, "db", "*.py"))
                 + glob.glob(os.path.join(ROOT, "webapp", "*.py")))
        self.assertGreater(len(files), 30)
        out, err = io.StringIO(), io.StringIO()
        for f in files:
            pf_api.checkPath(f, pf_rep.Reporter(out, err))
        undefined = [ln for ln in out.getvalue().splitlines()
                     if "undefined name '" in ln]
        self.assertEqual(undefined, [])

    async def test_group_broadcast_text_renders(self):
        import feat_match
        text = feat_match._broadcast_text("2PN Sơn Trà", "urgent", "Anh A")
        self.assertIn("2PN Sơn Trà", text)

    async def test_free_listing_limit_check_runs(self):
        uid = self.broker()
        ok, count, limit = db.check_listing_limit(uid)
        self.assertEqual(count, 0)

    async def test_broadcast_rate_limit_check_runs(self):
        uid = self.broker()
        for _ in range(10):
            self.listing(uid)
        ok, reason, _ = db.can_broadcast(uid, {"urgency": "urgent"})
        self.assertTrue(ok, reason)

    async def test_every_accepted_commission_unit_is_readable(self):
        # the "is this an amount?" filter must not accept a unit that the
        # commission reader (db.money, since 17/10) cannot turn into money
        import feat_deals
        from db import money
        self.assertGreater(len(feat_deals._AMOUNT_UNITS), 0)
        for unit in feat_deals._AMOUNT_UNITS:
            # currency words only mark a fully written amount; every other
            # unit must turn a short "15<unit>" reply into a number by itself
            samples = ((f"7500000{unit}", f"7.500.000 {unit}")
                       if unit in money.CURRENCY_WORDS
                       else (f"15{unit}", f"15 {unit}"))
            with self.subTest(unit=unit):
                self.assertTrue(all(money.parse_money(s) for s in samples))

    async def test_setting_a_broker_back_to_free_runs(self):
        uid = self.broker(tier="pro")
        db.set_tier(uid, "free")
        self.assertEqual(db.get_tier(uid), "free")


# ============================= review round (phiên F): regressions of fixes
class TestApproveTwice(AdminMixin, LinhFlowTest):
    def expiry(self, uid):
        return db.get_broker(uid)["tier_expires_at"]

    async def test_approving_twice_with_a_request_gives_thirty_days(self):
        uid = self.broker()
        db.create_premium_request(uid, tier_requested="pro")
        before = time.time()
        await self.approve(str(uid), "pro")
        await self.approve(str(uid), "pro")
        self.assertAlmostEqual(self.expiry(uid), before + 30 * DAY,
                               delta=120)

    async def test_approving_twice_without_a_request_gives_thirty_days(self):
        uid = self.broker()
        before = time.time()
        await self.approve(str(uid), "pro")
        await self.approve(str(uid), "pro")
        self.assertAlmostEqual(self.expiry(uid), before + 30 * DAY,
                               delta=120)

    async def test_repeat_approve_keeps_the_early_renewal_days(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        db.create_premium_request(uid, tier_requested="pro")
        await self.approve(str(uid), "pro")
        stacked = self.expiry(uid)
        await self.approve(str(uid), "pro")
        self.assertAlmostEqual(self.expiry(uid), stacked, delta=120)


class TestLeavingStepsKeepsWork(PendingMixin, LinhFlowTest):
    async def test_leaving_a_step_keeps_a_reserved_match_slot_releasable(self):
        import feat_match
        uid = self.broker()
        rid = "mr:test"
        feat_match._pending_picks[rid] = {uid}
        self.ctx(uid).user_data["match_picking"] = {
            "request_id": rid, "selected": [], "candidates": []}
        try:
            await self.cb(uid, "menu:back")
            await self.cb(uid, f"mpick:cancel:{rid}")
            self.assertNotIn(uid, feat_match._pending_picks.get(rid, set()),
                             "the reserved slot was never released")
        finally:
            feat_match._pending_picks.pop(rid, None)

    async def test_leaving_with_unsaved_drafts_says_so_and_can_reopen(self):
        uid = self.broker(phone="0905123456")
        a = self.listing(uid, status="draft")["id"]
        b = self.listing(uid, status="draft")["id"]
        ud = self.ctx(uid).user_data
        ud["confirming"] = {"listing_id": a}
        ud["confirming_queue"] = [{"listing_id": b}]
        await self.cb(uid, "menu:clients")
        notes = [m for m in self.outbox
                 if m["kind"] == "send" and "tin nháp" in m["text"]]
        self.assertEqual(len(notes), 1, "drafts dropped without a word")
        self.assertIn("2 tin nháp", notes[0]["text"])
        resume = [b_.callback_data for row in notes[0]["markup"].inline_keyboard
                  for b_ in row]
        self.assertEqual(resume, ["drafts:resume"])
        await self.cb(uid, "drafts:resume")
        cur = ud["confirming"]["listing_id"]
        queued = [e["listing_id"] for e in ud.get("confirming_queue") or []]
        self.assertEqual(sorted([cur] + queued), sorted([a, b]))
        save = [d for _, d in self.sent_buttons() if d.startswith("cfm:save:")]
        self.assertEqual(save, [f"cfm:save:{cur}"])

    async def test_navigation_keeps_the_guided_intake_answers(self):
        uid = self.broker(phone="0905123456")
        cid = self.client(uid)
        await self.cb(uid, "menu:new")
        await self.cb(uid, "guided:mode:guided")
        await self.cb(uid, "guided:set:bedrooms:2")
        for nav in ("menu:clients", f"client:{cid}:0:a:a", "menu:back"):
            await self.cb(uid, nav)
            with self.subTest(button=nav):
                gd = self.ctx(uid).user_data.get("guided")
                self.assertIsNotNone(gd)
                self.assertEqual(gd["answers"].get("bedrooms"), "2")

    async def test_new_listing_and_huy_still_drop_guided_intake(self):
        import feat_listings
        uid = self.broker(phone="0905123456")
        await self.cb(uid, "menu:new")
        await self.cb(uid, "guided:mode:guided")
        await self.cb(uid, "menu:new")
        self.assertNotIn("guided", self.ctx(uid).user_data)
        await self.cb(uid, "guided:mode:guided")
        await feat_listings.cmd_cancel_addphoto(
            MockUpdate(message=self._msg(uid, text="/huy")), self.ctx(uid))
        self.assertNotIn("guided", self.ctx(uid).user_data)


class TestGuidedPhotoStepText(LinhFlowTest):
    to_photo_step = TestGuidedPhotoStep.to_photo_step

    async def test_text_at_the_photo_step_is_not_swallowed(self):
        uid = self.broker(phone="0905123456")
        await self.to_photo_step(uid)
        await self.photo(uid, "p1")
        n = len(self.outbox)
        await self.text(uid, LISTING_PASTE)
        self.assertEqual(tf._buffers[uid]["texts"], [],
                         "text went into the photo buffer")
        self.assertEqual(tf._buffers[uid]["photos"], ["p1"])
        replies = [m["text"] for m in self.outbox[n:] if m["kind"] == "reply"]
        self.assertEqual(len(replies), 1, "the text got no answer")

    async def test_no_photo_button_drops_photos_sent_before_going_back(self):
        import feat_intake
        uid = self.broker(phone="0905123456")
        gd = await self.to_photo_step(uid)
        await self.photo(uid, "p1")
        await self.cb(uid, "guided:back")          # stashes p1
        self.assertEqual(gd["answers"].get("photos"), ["p1"])
        await self.cb(uid, "guided:amen:done")     # back on the photo step
        await self.cb(uid, "guided:nophoto")
        self.assertEqual(gd["answers"].get("photos") or [], [])
        self.assertEqual(feat_intake.GUIDED_STEPS[gd["step"]], "description")


class TestErrorHandlerScope(LinhFlowTest):
    def group_update(self, uid):
        msg = self._msg(uid)
        msg.chat = MockChat(-100123, title="Nhóm môi giới")
        msg.chat.type = "supergroup"
        return MockUpdate(message=msg)

    async def test_error_in_a_group_is_not_announced_to_the_group(self):
        uid = self.broker()
        ctx = self.ctx(uid)
        ctx.error = ValueError("boom")
        with self.assertLogs("linh", level="ERROR"):
            await bot.on_error(self.group_update(uid), ctx)
        self.assertEqual([m for m in self.outbox if m["kind"] == "send"], [])

    async def test_message_not_modified_is_only_logged(self):
        from telegram.error import BadRequest
        uid = self.broker()
        msg = self._msg(uid)
        q = MockCallbackQuery(self.outbox, "menu:back", MockUser(uid), msg)
        ctx = self.ctx(uid)
        ctx.error = BadRequest("Message is not modified: specified new "
                               "message content and reply markup are exactly "
                               "the same")
        with self.assertLogs("linh", level="INFO"):
            await bot.on_error(MockUpdate(callback_query=q), ctx)
        self.assertEqual([m for m in self.outbox if m["kind"] == "send"], [])


class TestRequestSummaryEscaped(LinhFlowTest):
    async def test_request_lists_escape_html_in_the_summary(self):
        uid = self.broker(tier="max")
        cid = db.create_client(uid, name="Chị <Lan>")
        db.create_match_request(uid, cid, "2PN <15tr Sơn Trà")
        for data in ("menu:match", f"client:reqs:{cid}"):
            await self.cb(uid, data)
            with self.subTest(button=data):
                last = self.last_text("edit")
                self.assertIn("&lt;15tr", last)
                self.assertNotIn("<15tr", last)
                self.assertNotIn("<Lan>", last)


if __name__ == "__main__":
    unittest.main()
