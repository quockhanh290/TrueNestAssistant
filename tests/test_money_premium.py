"""Money reader, Pro->Max conversion, /baocao admin command, /api/today.

Reuses the mocked-Telegram harness of tests/test_flows.py (fresh temp DB
per test; BOT_DB_PATH points at a temp dir before config is imported).

Run:  python -m pytest tests/test_money_premium.py -q
"""
import datetime as _dt
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_flows as tf  # noqa: E402,F401  (sets BOT_DB_PATH, imports bot)
from test_flows import (  # noqa: E402
    LinhFlowTest, MockCallbackQuery, MockUpdate, MockUser,
)
from test_high_fixes import AdminMixin, PendingMixin, ADMIN, DAY  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import feat_deals  # noqa: E402
import feat_metrics  # noqa: E402
import parser as listing_parser  # noqa: E402
from db import money  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "webapp"))
import api as webapi  # noqa: E402
import api_clients_deals as webapi2  # noqa: E402

VN = _dt.timezone(_dt.timedelta(hours=7))   # independent reference clock


def vn_epoch(y, mo, d, h=0, mi=0):
    return _dt.datetime(y, mo, d, h, mi, tzinfo=VN).timestamp()


def frozen_vn_now(y, mo, d, h, mi=0):
    fixed = _dt.datetime(y, mo, d, h, mi, tzinfo=VN)
    return lambda: fixed


# ======================================================== 1. money reader
READABLE = [
    ("15tr", 15_000_000),
    ("15 triệu", 15_000_000),
    ("15tr5", 15_500_000),
    ("15tr 5", 15_500_000),
    ("2tr500", 2_500_000),
    ("15 triệu 500 nghìn", 15_500_000),
    ("15 triệu 500 ngàn", 15_500_000),
    ("1 tỷ", 1_000_000_000),
    ("1 tỉ", 1_000_000_000),
    ("1,5 tỷ", 1_500_000_000),
    ("1.5 tỷ", 1_500_000_000),
    ("1 tỷ 2", 1_200_000_000),
    ("1 tỷ 200 triệu", 1_200_000_000),
    ("15000000", 15_000_000),
    ("7.500.000", 7_500_000),
    ("7,500,000", 7_500_000),
    ("500k", 500_000),
    ("500 nghìn", 500_000),
    ("500 ngàn", 500_000),
    ("15 củ", 15_000_000),
    ("15m", 15_000_000),
    ("12,5tr", 12_500_000),
    ("7500000đ", 7_500_000),
    ("7.500.000đ", 7_500_000),
    ("7.500.000 vnd", 7_500_000),
    ("15 triệu đồng", 15_000_000),
    ("15tr đ", 15_000_000),
    ("  15TR  ", 15_000_000),
]

# None = ask again. Never a silently shortened number.
UNREADABLE = [
    "7.500.000k",          # either a typo or 7,5 tỷ: do not guess
    "15",                  # 15 đồng or 15 triệu?
    "1.500tr",             # 1,5tr or 1500tr?
    "15 triệu 1500 nghìn",  # lower part bigger than the unit above it
    "1,5 tỷ 200 triệu",
    "500 nghìn 2 triệu",   # units must go down
    "15tr5000",            # trailing part longer than 3 digits
    "15 triệu đồng 5",     # currency word in the middle
    "15 usd",
    "$500",
    "abc",
    "",
    "0",
    "0tr",
    "15tr\n5",
    "cho thuê 2PN 8tr5 sơn trà",
]


class TestMoneyReader(unittest.TestCase):
    def test_every_common_way_of_writing_an_amount_is_read_exactly(self):
        for text, want in READABLE:
            with self.subTest(text=text):
                self.assertEqual(money.parse_money(text), want)

    def test_ambiguous_or_unreadable_amounts_return_none(self):
        for text in UNREADABLE:
            with self.subTest(text=text):
                self.assertIsNone(money.parse_money(text))

    def test_commission_filter_uses_the_readers_unit_list(self):
        # one list, shared: the filter cannot accept a word the reader
        # does not know, and the reader's words all pass the filter
        self.assertGreater(len(feat_deals._AMOUNT_UNITS), 0)
        self.assertEqual(set(feat_deals._AMOUNT_UNITS), set(money.AMOUNT_WORDS))

    def test_every_unit_word_turns_a_short_reply_into_money(self):
        self.assertGreater(len(money.UNIT_WORDS), 0)
        for unit, mult in money.UNIT_WORDS.items():
            for s in (f"15{unit}", f"15 {unit}"):
                with self.subTest(text=s):
                    self.assertTrue(feat_deals._looks_like_amount(s))
                    self.assertEqual(money.parse_money(s), 15 * mult)
        self.assertGreater(len(money.CURRENCY_WORDS), 0)
        for cur in money.CURRENCY_WORDS:
            s = f"7500000{cur}"
            with self.subTest(text=s):
                self.assertTrue(feat_deals._looks_like_amount(s))
                self.assertEqual(money.parse_money(s), 7_500_000)

    def test_rent_price_reader_is_unchanged(self):
        # values measured on parser.parse_price BEFORE this change (17/10);
        # the rent reader is a different function and must not move
        pinned = {
            "15tr": 15_000_000, "12,5tr": 12_500_000,
            "Giá 12.000.000/tháng": 12_000_000,
            "18,500,000 VND/month": 18_500_000,
            "rent 18500000": 18_500_000,
            "$500": 12_500_000,
            "cho thuê 2PN 8tr5 sơn trà": 8_500_000,
            "15000000": None, "500k": None,
        }
        for text, want in pinned.items():
            with self.subTest(text=text):
                self.assertEqual(listing_parser.parse_price(text)[0], want)


class TestCommissionStepReadsAmounts(PendingMixin, LinhFlowTest):
    def arm(self, uid):
        cid = self.client(uid)
        self.ctx(uid).user_data["adding_deal"] = {
            "client_id": cid, "listing_id": None, "client_name": "Khách A"}

    async def test_commission_step_books_the_full_amount(self):
        cases = [("15tr5", 15_500_000), ("15 triệu 500 nghìn", 15_500_000),
                 ("1,5 tỷ", 1_500_000_000), ("500k", 500_000),
                 ("15 củ", 15_000_000), ("7500000đ", 7_500_000),
                 ("15000000", 15_000_000)]
        for text, want in cases:
            with self.subTest(text=text):
                uid = self.broker()
                self.arm(uid)
                await self.text(uid, text)
                deals = self.deals(uid)
                self.assertEqual(len(deals), 1)
                self.assertEqual(deals[0]["commission_vnd"], want)

    async def test_commission_step_asks_again_instead_of_guessing(self):
        for text in ("7.500.000k", "15", "15 triệu 1500 nghìn"):
            with self.subTest(text=text):
                uid = self.broker()
                self.arm(uid)
                await self.text(uid, text)
                self.assertEqual(self.deals(uid), [])
                self.assertIn("adding_deal", self.ctx(uid).user_data)
                self.assertIn("chưa hiểu số tiền", self.last_text())


# ================================================== 2. Pro -> Max upgrade
PRO_PRICE, MAX_PRICE = 99_000, 199_000     # the prices on the plans screen


class TestUpgradeConversion(AdminMixin, LinhFlowTest):
    def exp(self, uid):
        return db.get_broker(uid)["tier_expires_at"]

    async def test_pro_days_left_are_converted_by_price_on_upgrade(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        db.create_premium_request(uid, tier_requested="max")
        before = time.time()
        await self.approve(str(uid), "max")
        # 10 Pro days x 99k / 199k = 4.97 Max days, on top of the paid 30
        credit = 10 * PRO_PRICE / MAX_PRICE
        self.assertEqual(db.get_tier(uid), "max")
        self.assertAlmostEqual(self.exp(uid), before + (30 + credit) * DAY,
                               delta=120)

    async def test_upgrade_message_states_the_converted_days(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        db.create_premium_request(uid, tier_requested="max")
        await self.approve(str(uid), "max")
        to_broker = [m["text"] for m in self.outbox
                     if m.get("chat_id") == uid]
        self.assertTrue(to_broker, "broker got no approval message")
        self.assertIn("10,0 ngày Pro", to_broker[-1])
        self.assertIn("5,0 ngày Max", to_broker[-1])
        self.assertIn("5,0 ngày", self.last_text("reply"))

    async def test_upgrade_without_payment_request_does_not_convert(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        before = time.time()
        await self.approve(str(uid), "max")
        self.assertAlmostEqual(self.exp(uid), before + 30 * DAY, delta=120)

    async def test_downgrade_starts_from_now_as_before(self):
        uid = self.broker()
        db.set_tier(uid, "max", days=10)
        db.create_premium_request(uid, tier_requested="pro")
        before = time.time()
        await self.approve(str(uid), "pro")
        self.assertAlmostEqual(self.exp(uid), before + 30 * DAY, delta=120)

    async def test_same_tier_renewal_still_stacks_whole_days(self):
        uid = self.broker()
        db.set_tier(uid, "pro", days=10)
        old = self.exp(uid)
        db.create_premium_request(uid, tier_requested="pro")
        await self.approve(str(uid), "pro")
        self.assertAlmostEqual(self.exp(uid), old + 30 * DAY, delta=120)

    async def test_expired_pro_gives_no_credit(self):
        uid = self.broker()
        db.update_broker(uid, tier="pro", tier_expires_at=time.time() - DAY)
        db.create_premium_request(uid, tier_requested="max")
        before = time.time()
        await self.approve(str(uid), "max")
        self.assertAlmostEqual(self.exp(uid), before + 30 * DAY, delta=120)


# ============================================================ 3. /baocao
class BaocaoMixin:
    async def baocao(self, uid):
        msg = self._msg(uid, text="/baocao")
        upd = MockUpdate(message=msg)
        with patch.object(config, "ADMIN_TELEGRAM_ID", ADMIN):
            await feat_metrics.cmd_baocao(upd, self.ctx(uid))
        await self.drain()

    async def admin_cb(self, uid, data):
        msg = self._msg(uid)
        q = MockCallbackQuery(self.outbox, data, MockUser(uid), msg)
        with patch.object(config, "ADMIN_TELEGRAM_ID", ADMIN):
            await tf.bot.on_callback(MockUpdate(callback_query=q),
                                     self.ctx(uid))
        await self.drain()
        return q

    def penalised_report(self, uid, title="Monarchy <b>x</b>"):
        """A share-page report that caused a strike, as the pipeline does."""
        l = self.listing(uid, building_name=title)
        token = db.create_share_page(uid, [l["id"]])
        db.log_refresh_claim(l["id"], uid, "available")
        rid = db.create_listing_report(token, l["id"], uid, "rented")
        self.assertTrue(db.reserve_report_penalty(token, l["id"], rid,
                                                  "rented"))
        result = db.flag_false_refresh(l["id"])
        db.mark_report_penalty_applied(rid, result)
        return rid, token


class TestBaocaoCommand(BaocaoMixin, LinhFlowTest):
    async def test_non_admin_is_refused_and_sees_no_report(self):
        uid = self.broker()
        self.penalised_report(uid)
        await self.baocao(uid)
        out = " ".join(self.texts())
        self.assertNotIn("Monarchy", out)
        self.assertNotIn("Gỡ phạt", out)

    async def test_non_admin_cannot_press_the_unpenalise_button(self):
        uid = self.broker()
        rid, _ = self.penalised_report(uid)
        await self.admin_cb(uid, f"rpt:unpen:{rid}")
        self.assertEqual(db.get_broker(uid)["false_refresh_reports"], 1)

    async def test_admin_sees_reports_escaped_with_vn_time_and_penalty(self):
        uid = self.broker()
        rid, token = self.penalised_report(uid)
        db.update_broker(uid, display_name="Anh <Tú>")
        await self.baocao(ADMIN)
        out = self.last_text("reply")
        self.assertIn("Monarchy &lt;b&gt;x&lt;/b&gt;", out)
        self.assertNotIn("<b>x</b>", out)
        self.assertIn("Anh &lt;Tú&gt;", out)
        self.assertIn(token[:8], out)
        self.assertIn("Đã cho thuê", out)
        self.assertIn("đã phạt", out.lower())
        rep = [r for r in db.list_recent_reports(20) if r["id"] == rid][0]
        self.assertIn(_dt.datetime.fromtimestamp(rep["created_at"], VN)
                      .strftime("%H:%M %d/%m"), out)
        btns = [d for _, d in self.buttons("reply")]
        self.assertIn(f"rpt:unpen:{rid}", btns)

    async def test_admin_list_is_capped_at_twenty_newest(self):
        uid = self.broker()
        l = self.listing(uid)
        token = db.create_share_page(uid, [l["id"]])
        for _ in range(25):
            db.create_listing_report(token, l["id"], uid, "price_wrong")
        self.assertEqual(len(db.list_recent_reports(20)), 20)

    async def test_unpenalise_gives_the_strike_back_and_lifts_its_lock(self):
        uid = self.broker()
        rids = [self.penalised_report(uid, title=f"T{i}")[0]
                for i in range(3)]
        self.assertEqual(db.get_broker(uid)["false_refresh_reports"], 3)
        self.assertIsNotNone(db.get_refresh_cooldown(uid))
        await self.admin_cb(ADMIN, f"rpt:unpen:{rids[-1]}")
        self.assertEqual(db.get_broker(uid)["false_refresh_reports"], 2)
        self.assertIsNone(db.get_refresh_cooldown(uid))
        # pressing it again changes nothing
        await self.admin_cb(ADMIN, f"rpt:unpen:{rids[-1]}")
        self.assertEqual(db.get_broker(uid)["false_refresh_reports"], 2)

    async def test_unpenalise_keeps_a_lock_still_earned_by_other_strikes(self):
        uid = self.broker()
        rids = [self.penalised_report(uid, title=f"T{i}")[0]
                for i in range(4)]
        await self.admin_cb(ADMIN, f"rpt:unpen:{rids[0]}")
        self.assertEqual(db.get_broker(uid)["false_refresh_reports"], 3)
        self.assertIsNotNone(db.get_refresh_cooldown(uid))


# ============================================================ 4. /api/today
NOW = (2026, 10, 20, 10, 30)   # Vietnam wall clock; 19/10 21:30 in Calgary


class TestTodayApi(PendingMixin, LinhFlowTest):
    def today(self, uid):
        from db import vntime
        with patch.object(vntime, "now", frozen_vn_now(*NOW)):
            data, code = webapi.get_today(uid)
        self.assertEqual(code, 200)
        return data

    def viewing(self, uid, at, cid=None, lid=None):
        return db.create_viewing(uid, client_id=cid, client_name="Khách A",
                                 listing_ids=[lid] if lid else [],
                                 scheduled_at=at)

    async def test_date_and_viewings_follow_vietnam_day(self):
        uid = self.broker()
        cid = self.client(uid)
        lid = self.listing(uid, building_name="Monarchy")["id"]
        past = self.viewing(uid, vn_epoch(2026, 10, 20, 10, 0), cid, lid)
        late = self.viewing(uid, vn_epoch(2026, 10, 20, 22, 0), cid)
        # same Calgary date as "now" but the previous Vietnam day
        self.viewing(uid, vn_epoch(2026, 10, 19, 23, 0), cid)
        self.viewing(uid, vn_epoch(2026, 10, 21, 0, 0), cid)
        data = self.today(uid)
        self.assertEqual(data["date"], "2026-10-20")
        ids = [v["id"] for v in data["viewings"]]
        self.assertEqual(ids, [past, late])
        v0 = data["viewings"][0]
        self.assertEqual(v0["time"], "10:00")
        self.assertEqual(v0["scheduled_at"], vn_epoch(2026, 10, 20, 10, 0))
        self.assertEqual(v0["client_id"], cid)
        self.assertEqual(v0["client_name"], "Khách A")
        self.assertEqual(v0["listing_id"], lid)
        self.assertIn("Monarchy", v0["listing_title"])
        self.assertEqual(v0["status"], "scheduled")

    async def test_followups_are_urgent_or_quiet_for_five_days(self):
        uid = self.broker()
        urgent = db.create_client(uid, name="Gấp", urgency="urgent")
        quiet = db.create_client(uid, name="Im", urgency="normal")
        fresh = db.create_client(uid, name="Mới", urgency="normal")
        done = db.create_client(uid, name="Xong", urgency="urgent")
        db.update_client(done, status="rented")
        conn = db.connect()
        conn.execute("UPDATE clients SET updated_at = ? WHERE id = ?",
                     (time.time() - 6 * DAY, quiet))
        conn.commit()
        conn.close()
        data = self.today(uid)
        ids = [f["id"] for f in data["followups"]]
        self.assertIn(urgent, ids)
        self.assertIn(quiet, ids)
        self.assertNotIn(fresh, ids)
        self.assertNotIn(done, ids)
        q = [f for f in data["followups"] if f["id"] == quiet][0]
        self.assertEqual(q["days_since_update"], 6)
        self.assertEqual(set(q), {"id", "name", "summary", "urgency",
                                  "days_since_update"})
        for i in range(12):
            db.create_client(uid, name=f"G{i}", urgency="urgent")
        self.assertEqual(len(self.today(uid)["followups"]), 10)

    async def test_stale_listing_count_uses_freshness_window(self):
        uid = self.broker()
        old = self.listing(uid)["id"]
        self.listing(uid)
        conn = db.connect()
        conn.execute("UPDATE tg_listings SET updated_at = ? WHERE id = ?",
                     (time.time() - 8 * DAY, old))
        conn.commit()
        conn.close()
        data = self.today(uid)
        self.assertEqual(data["stale_listings"],
                         {"count": 1, "window_days": 7})

    async def test_broker_a_never_sees_broker_b(self):
        a, b = self.broker(), self.broker()
        cb = db.create_client(b, name="Khách của B", urgency="urgent")
        lb = self.listing(b)["id"]
        self.viewing(b, vn_epoch(2026, 10, 20, 11, 0), cb, lb)
        data = self.today(a)
        self.assertEqual(data["viewings"], [])
        self.assertEqual(data["followups"], [])
        self.assertEqual(data["stale_listings"]["count"], 0)
        self.assertEqual(data["counts"]["listings"], 0)
        self.assertEqual(data["counts"]["clients"], 0)
        self.assertEqual(data["counts"]["viewings_upcoming"], 0)

    async def test_counts_match_the_single_apis(self):
        a, b = self.broker(), self.broker()
        for _ in range(3):
            self.listing(a)
        self.listing(b)
        for n in ("K1", "K2"):
            db.create_client(a, name=n)
        kb = db.create_client(b, name="KB")
        self.viewing(a, time.time() + DAY)
        self.viewing(a, time.time() - DAY)
        db.create_match_request(b, kb, "2PN Sơn Trà")
        data = self.today(a)
        c = data["counts"]
        self.assertEqual(c["listings"], webapi.get_listings(a)[0]["total"])
        self.assertEqual(c["clients"],
                         len(webapi2.list_clients_api(a)[0]["clients"]))
        self.assertEqual(c["viewings_upcoming"],
                         len(webapi2.list_viewings_api(a)[0]["viewings"]))
        self.assertEqual(c["xbroker_pending"],
                         len(webapi.get_xbroker_requests(a)[0]["requests"]))
        self.assertEqual((c["listings"], c["clients"],
                          c["viewings_upcoming"]), (3, 2, 1))

    async def test_listing_summary_carries_updated_at(self):
        uid = self.broker()
        row = db.get_listing(self.listing(uid)["id"])
        self.assertEqual(webapi.listing_summary(row)["updated_at"],
                         row["updated_at"])


if __name__ == "__main__":
    unittest.main()


class TestWebappDealAmount(PendingMixin, LinhFlowTest):
    async def test_webapp_deal_reads_a_typed_amount_in_full(self):
        uid = self.broker()
        data, code = webapi2.create_deal_api(uid, {"commission_amount": "15tr5"})
        self.assertEqual(code, 200)
        self.assertEqual(self.deals(uid)[0]["commission_vnd"], 15_500_000)

    async def test_webapp_deal_refuses_an_ambiguous_amount(self):
        uid = self.broker()
        data, code = webapi2.create_deal_api(
            uid, {"commission_amount": "7.500.000k"})
        self.assertEqual(code, 400)
        self.assertEqual(self.deals(uid), [])

    async def test_webapp_deal_still_takes_a_plain_number(self):
        uid = self.broker()
        for amount in (15_000_000, 15000000.0, "15000000"):
            with self.subTest(amount=amount):
                webapi2.create_deal_api(uid, {"commission_amount": amount})
        self.assertEqual([d["commission_vnd"] for d in self.deals(uid)],
                         [15_000_000] * 3)
