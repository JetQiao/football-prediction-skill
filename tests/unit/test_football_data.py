import unittest

from football_prediction.providers.football_data import FootballDataProvider


class FootballDataTests(unittest.TestCase):
    def test_recent_data_prefers_market_average_over_stale_pinnacle(self):
        row = {"AvgCH": "2.0", "AvgCD": "3.4", "AvgCA": "3.8", "PSCH": "1.8", "PSCD": "3.5", "PSCA": "4.2"}
        odds = FootballDataProvider._odds(row, "2026-01-01")
        self.assertEqual(odds[:3], (2.0, 3.4, 3.8))
        self.assertEqual(odds[3], "AvgC")


if __name__ == "__main__":
    unittest.main()
