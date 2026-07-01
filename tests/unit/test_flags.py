import unittest

from football_prediction.reporting.flags import NATIONAL_TEAM_CODES, flag_data_uri, flag_for


class FlagTests(unittest.TestCase):
    def test_national_teams_resolve_to_codes(self):
        self.assertEqual(flag_for("英格兰"), "gb-eng")
        self.assertEqual(flag_for("刚果金"), "cd")
        self.assertEqual(flag_for("美国"), "us")

    def test_name_variants_and_punctuation_match(self):
        # 全角括号写法应与简称归一到同一代码。
        self.assertEqual(flag_for("刚果（金）"), "cd")
        self.assertEqual(flag_for("沙特"), flag_for("沙特阿拉伯"))

    def test_clubs_and_unknowns_fall_back_to_letter_crest(self):
        self.assertIsNone(flag_for("阿森纳"))
        self.assertIsNone(flag_for("曼联"))
        self.assertIsNone(flag_for(""))

    def test_data_uri_is_offline_and_missing_returns_none(self):
        uri = flag_data_uri("gb-eng")
        self.assertIsNotNone(uri)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertIsNone(flag_data_uri("zz"))

    def test_every_mapped_flag_is_packaged(self):
        for code in set(NATIONAL_TEAM_CODES.values()):
            with self.subTest(code=code):
                self.assertIsNotNone(flag_data_uri(code))


if __name__ == "__main__":
    unittest.main()
