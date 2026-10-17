"""Listing value rules and quality-score v5 regression tests."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import test_flows  # noqa: E402,F401  (selects a temp DB before app imports)

import config  # noqa: E402
import db  # noqa: E402
from db.listings import _check_parsed_value  # noqa: E402
from db.validate import FieldError  # noqa: E402
import parser  # noqa: E402
import schema  # noqa: E402
from webapp import api  # noqa: E402


def assert_bad(test, field, value, reason):
    with test.assertRaises(FieldError) as caught:
        _check_parsed_value(field, value)
    test.assertEqual(caught.exception.field, field)
    test.assertEqual(caught.exception.reason, reason)


class TestSection3ValueRules(unittest.TestCase):
    def test_price_rule(self):
        self.assertEqual(_check_parsed_value("price_vnd", "12tr"), 12_000_000)
        assert_bad(self, "price_vnd", 8, "price_maybe_millions")
        assert_bad(self, "price_vnd", 999_999, "out_of_range")
        assert_bad(self, "price_vnd", 200_000_001, "out_of_range")

    def test_bedrooms_and_bathrooms_rule(self):
        self.assertEqual(_check_parsed_value("bedrooms", 0), 0)
        self.assertEqual(_check_parsed_value("bathrooms", 10), 10)
        assert_bad(self, "bedrooms", 2.5, "not_an_integer")
        assert_bad(self, "bathrooms", 11, "out_of_range")

    def test_area_rule(self):
        self.assertEqual(_check_parsed_value("area_m2", 10), 10)
        self.assertEqual(_check_parsed_value("area_m2", 2_000), 2_000)
        assert_bad(self, "area_m2", 0, "out_of_range")
        assert_bad(self, "area_m2", 2_001, "out_of_range")

    def test_apartment_floor_rule(self):
        self.assertEqual(_check_parsed_value("floor_number", 0), 0)
        self.assertEqual(_check_parsed_value("floor_number", 80), 80)
        assert_bad(self, "floor_number", 80.5, "out_of_range")

    def test_house_floors_rule(self):
        self.assertEqual(_check_parsed_value("house_floors", 1), 1)
        self.assertEqual(_check_parsed_value("house_floors", 10), 10)
        assert_bad(self, "house_floors", 0, "out_of_range")

    def test_deposit_rule_accepts_month_text(self):
        self.assertEqual(_check_parsed_value("deposit_months", "2 thang"), 2)
        self.assertEqual(_check_parsed_value("deposit_months", "2 tháng"), 2)
        assert_bad(self, "deposit_months", 13, "out_of_range")

    def test_minimum_lease_rule(self):
        self.assertEqual(_check_parsed_value("min_lease_months", 1), 1)
        self.assertEqual(_check_parsed_value("min_lease_months", 60), 60)
        assert_bad(self, "min_lease_months", 0, "out_of_range")

    def test_management_fee_rule(self):
        self.assertEqual(
            _check_parsed_value("management_fee", "2tr"), 2_000_000)
        assert_bad(self, "management_fee", "21tr", "out_of_range")

    def test_phone_rule_uses_existing_normalizer(self):
        self.assertEqual(
            _check_parsed_value("primary_phone", "+84 905 123 456"),
            "0905123456")
        assert_bad(self, "primary_phone", "abc", "bad_phone")

    def test_fixed_list_rule(self):
        self.assertEqual(_check_parsed_value("property_type", "Apartment"),
                         "apartment")
        self.assertEqual(_check_parsed_value("furnishing", "full"), "full")
        self.assertEqual(_check_parsed_value("balcony_direction", "east"),
                         "east")
        for field in ("property_type", "furnishing", "balcony_direction"):
            assert_bad(self, field, "invented", "not_allowed")

    def test_available_from_rule(self):
        today = dt.date.today()
        try:
            earliest = today.replace(year=today.year - 1)
        except ValueError:
            earliest = today.replace(year=today.year - 1, day=28)
        self.assertEqual(
            _check_parsed_value("available_from", earliest.isoformat()),
            earliest.isoformat())
        assert_bad(self, "available_from", (earliest - dt.timedelta(days=1)).isoformat(),
                   "bad_date")
        assert_bad(self, "available_from", "17/10/2026", "bad_date")

    def test_electricity_and_water_price_rule(self):
        self.assertEqual(_check_parsed_value("electricity_price", "giá nhà nước"),
                         "giá nhà nước")
        self.assertEqual(_check_parsed_value("water_price", 100_000), 100_000)
        assert_bad(self, "electricity_price", "thỏa thuận", "not_allowed")
        assert_bad(self, "water_price", -1, "out_of_range")

    def test_electricity_price_upper_bound(self):
        self.assertEqual(_check_parsed_value("electricity_price", 3_500), 3_500)
        assert_bad(self, "electricity_price", 3_500_000, "out_of_range")

    def test_water_price_upper_bound(self):
        self.assertEqual(_check_parsed_value("water_price", 15_000), 15_000)
        assert_bad(self, "water_price", 3_000_000, "out_of_range")


class TestDatabaseAndApiValueGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tn_quality_")
        self.path = os.path.join(self.tmp, "test.db")
        self.db_patch = patch.object(config, "DB_PATH", self.path)
        self.db_patch.start()
        db.init_db()
        self.broker = 74101
        db.get_or_create_broker(self.broker, "quality", "Quality")

    def tearDown(self):
        self.db_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_path_rejects_before_insert(self):
        with self.assertRaises(FieldError):
            db.create_listing(self.broker, parsed={"price_vnd": 8})
        self.assertEqual(db.list_broker_listings(self.broker), [])

    def test_webapp_batch_is_atomic_and_keeps_bad_field_contract(self):
        listing_id = db.create_listing(
            self.broker, parsed={"price_vnd": 12_000_000, "bedrooms": 2})
        with self.assertRaises(FieldError) as caught:
            api.update_listing(self.broker, listing_id,
                               {"bedrooms": 3, "price_vnd": 8})
        self.assertEqual(caught.exception.field, "price_vnd")
        self.assertEqual(caught.exception.reason, "price_maybe_millions")
        parsed = db.get_listing(listing_id)["parsed"]
        self.assertEqual(parsed["bedrooms"], 2)
        self.assertEqual(parsed["price_vnd"], 12_000_000)

    def test_new_canonical_fields_and_parser_key_are_preserved(self):
        parsed = parser.parse_listing("Hợp đồng 12 tháng")["fields"]
        self.assertEqual(parsed["min_lease_months"], 12)
        for field in ("ward", "min_lease_months", "electricity_price",
                      "water_price", "available_from"):
            self.assertIn(field, schema.MASTER_SCHEMA)
            self.assertIn(field, api.EDITABLE_FIELDS)


class TestBotLenientListingWrites(test_flows.LinhFlowTest):
    async def _intake_bad_parser_value(self, text, bad_field, label):
        uid = self.broker(phone="0905123456")
        await self.text(uid, text)
        await self.fire_flush(uid)
        await self.cb(uid, "buf:done")

        confirming = self.ctx(uid).user_data.get("confirming")
        self.assertIsNotNone(confirming)
        listing = db.get_listing(confirming["listing_id"])
        self.assertEqual(listing["status"], "draft")
        self.assertNotIn(bad_field, listing["parsed"])
        self.assertIn(bad_field, listing["missing_fields"])
        self.assertTrue(any(label in message for message in self.texts()),
                        self.texts())
        return listing

    async def test_bot_intake_drops_bad_bedrooms_and_saves_draft(self):
        listing = await self._intake_bad_parser_value(
            "Cho thue nha 20PN Hai Chau 15tr", "bedrooms", "Số phòng ngủ")
        self.assertEqual(listing["parsed"]["price_vnd"], 15_000_000)

    async def test_bot_intake_drops_bad_price_and_saves_draft(self):
        listing = await self._intake_bad_parser_value(
            "Cho thue 2PN 500 trieu/thang", "price_vnd", "Giá thuê")
        self.assertEqual(listing["parsed"]["bedrooms"], 2)

    async def test_guided_set_bad_value_replies_and_stays_on_field(self):
        uid = self.broker()
        await self.cb(uid, "guided:mode:guided")
        await self.cb(uid, "guided:set:bedrooms:20")

        guided = self.ctx(uid).user_data["guided"]
        self.assertEqual(guided["step"], 0)
        self.assertNotIn("bedrooms", guided["answers"])
        self.assertIn("Số phòng ngủ", self.last_text("edit"))


def _complete_common(property_type):
    return {
        "price_vnd": 12_000_000,
        "bedrooms": 2,
        "area_m2": 75,
        "district": "Sơn Trà",
        "ward": "An Hải Bắc",
        "available_from": dt.date.today().isoformat(),
        "property_type": property_type,
        "bathrooms": 2,
        "primary_phone": "0905123456",
        "furnishing": "full",
        "pet_friendly": False,
        "min_lease_months": 12,
        "electricity_price": 3_500,
        "water_price": "giá nhà nước",
        "deposit_months": 2,
        "description": "Mô tả đầy đủ " * 6,
        "amenities": [f"amenity-{i}" for i in range(10)],
        "highlights": [f"highlight-{i}" for i in range(6)],
    }


def _detail(property_type):
    if property_type == "apartment":
        return {
            "building_name": "Monarchy", "unit_number": "A1203",
            "floor_number": 12, "management_fee": "2tr",
            "balcony_direction": "east", "view": "biển",
        }
    return {
        "street": "12 Trần Hưng Đạo", "alley_info": "mặt tiền 6m",
        "house_floors": 3,
    }


class TestQualityScoreV5(unittest.TestCase):
    def test_schema_blocks_derive_100_for_each_property_type(self):
        common_total = sum(meta[2] for meta in schema.COMMON_SCHEMA.values())
        for property_type, detail_schema in schema.TYPE_DETAIL_SCHEMAS.items():
            table_total = common_total + sum(meta[2] for meta in detail_schema.values())
            self.assertEqual(table_total, schema.QUALITY_TOTAL)
            listing = _complete_common(property_type)
            listing.update(_detail(property_type))
            score, _ = schema.quality_score(listing, photo_count=3)
            self.assertEqual(score, table_total)

    def test_section4_comparison_table(self):
        measured = {}
        new_fields = {"ward", "available_from", "min_lease_months",
                      "electricity_price", "water_price"}
        for property_type in ("house", "apartment"):
            complete = _complete_common(property_type)
            complete.update(_detail(property_type))
            current = {key: value for key, value in complete.items()
                       if key not in new_fields}
            measured[f"{property_type}_current"] = schema.quality_score(
                current, photo_count=5)[0]
            measured[f"{property_type}_full"] = schema.quality_score(
                complete, photo_count=5)[0]

        typical = {
            "price_vnd": 12_000_000, "primary_phone": "0905123456",
            "bedrooms": 2, "district": "Sơn Trà",
            "property_type": "apartment",
        }
        measured["typical"] = schema.quality_score(typical, photo_count=5)[0]
        measured["typical_no_photos"] = schema.quality_score(
            typical, photo_count=0)[0]

        self.assertEqual(measured, {
            "house_current": 88,
            "apartment_current": 88,
            "house_full": 100,
            "apartment_full": 100,
            "typical": 36,
            "typical_no_photos": 29,
        })

    def test_invalid_values_do_not_score(self):
        listing = {"price_vnd": 8, "bedrooms": 2.5, "area_m2": 0,
                   "primary_phone": "abc", "property_type": "invented"}
        self.assertEqual(schema.quality_score(listing, photo_count=0)[0], 0)

    def test_unknown_property_type_gets_no_detail_block(self):
        listing = _complete_common("room")
        listing.update(_detail("house"))
        score, _ = schema.quality_score(listing, photo_count=3)
        self.assertEqual(score, sum(meta[2] for meta in schema.COMMON_SCHEMA.values()))

    def test_placeholder_house_address_does_not_score(self):
        listing = {"property_type": "house", "street": "x"}
        self.assertEqual(schema.quality_score(listing)[0], 4)
