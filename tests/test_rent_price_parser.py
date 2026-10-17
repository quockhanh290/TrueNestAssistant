import unittest

from parser import parse_price


class TestRentPriceParserGolden(unittest.TestCase):
    def test_existing_outputs_are_unchanged(self):
        # Captured from parse_price before adding support for trailing digits.
        cases = {
            "12tr": (12_000_000.0, "high"),
            "12 tr": (12_000_000.0, "high"),
            "12 triệu": (12_000_000.0, "high"),
            "12triệu": (12_000_000.0, "high"),
            "8.5tr": (8_500_000.0, "high"),
            "8,5 triệu": (8_500_000.0, "high"),
            "12,000,000": (12_000_000.0, "medium"),
            "12.000.000": (12_000_000.0, "medium"),
            "giá 12000000": (12_000_000.0, "medium"),
            "gia: 13500000": (13_500_000.0, "medium"),
            "rent: 18,500,000": (18_500_000.0, "medium"),
            "rent 18500000": (18_500_000.0, "medium"),
            "price-9.000.000": (9_000_000.0, "medium"),
            "18,500,000 VND/month": (18_500_000.0, "medium"),
            "9.000.000 VND": (9_000_000.0, "medium"),
            "7,500,000/tháng": (7_500_000.0, "medium"),
            "500 usd": (12_500_000.0, "medium"),
            "$500": (12_500_000.0, "medium"),
            "500$": (12_500_000.0, "medium"),
            "Cho thuê căn 2PN giá 10tr/tháng": (10_000_000.0, "high"),
            "studio 6 tr": (6_000_000.0, "high"),
            "15mil": (15_000_000.0, "high"),
            "15 mil": (15_000_000.0, "high"),
            "12.75tr": (12_750_000.0, "high"),
            "12,75tr": (12_750_000.0, "high"),
            "8,5tr": (8_500_000.0, "high"),
            "18tr 30m2": (18_000_000.0, "high"),
            "8tr 2 pn": (8_000_000.0, "high"),
            "7tr 1 phòng ngủ": (7_000_000.0, "high"),
            "12000000": (None, None),
            "500k": (None, None),
            "thỏa thuận": (None, None),
            "call 0905123456": (None, None),
            "": (None, None),
            "không ghi giá": (None, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_price(text), expected)


class TestRentPriceParserTrailingDigits(unittest.TestCase):
    def test_compact_one_digit(self):
        self.assertEqual(parse_price("8tr5"), (8_500_000.0, "high"))

    def test_spaced_one_digit(self):
        self.assertEqual(parse_price("8 tr 5"), (8_500_000.0, "high"))

    def test_vietnamese_unit_one_digit(self):
        self.assertEqual(parse_price("8 triệu 5"), (8_500_000.0, "high"))

    def test_spaced_suffix_before_punctuation(self):
        cases = {
            "8 tr 5/tháng": 8_500_000.0,
            "8 triệu 5, 2PN": 8_500_000.0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_price(text), (expected, "high"))

    def test_compact_three_digits(self):
        self.assertEqual(parse_price("8tr500"), (8_500_000.0, "high"))

    def test_compact_one_digit_after_two_digit_millions(self):
        self.assertEqual(parse_price("12tr2"), (12_200_000.0, "high"))

    def test_compact_two_digits(self):
        self.assertEqual(parse_price("12tr25"), (12_250_000.0, "high"))

    def test_trailing_digits_do_not_consume_listing_details(self):
        cases = {
            "8tr 2PN": 8_000_000.0,
            "8tr, 50m2": 8_000_000.0,
            "10tr/tháng": 10_000_000.0,
            "8tr5 2PN 70m2": 8_500_000.0,
            "8tr 0905": 8_000_000.0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_price(text), (expected, "high"))

    def test_spaced_suffix_does_not_consume_following_words(self):
        cases = {
            "10tr 6 tháng": 10_000_000.0,
            "Giá 8tr 3 tháng cọc": 8_000_000.0,
            "15tr 2 người ở": 15_000_000.0,
            "12 triệu 1 năm": 12_000_000.0,
            "9tr 2 xe máy": 9_000_000.0,
            "8tr 5 phút ra biển": 8_000_000.0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_price(text), (expected, "high"))


if __name__ == "__main__":
    unittest.main()
