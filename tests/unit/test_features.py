import unittest

from football_prediction.providers.features import SoccerDataUnderstatProvider


class FeatureProviderTests(unittest.TestCase):
    def test_understat_records_are_aggregated(self):
        records = [
            {"team": "Alpha FC", "xG": 1.2, "xGA": 0.8},
            {"team": "Alpha FC", "xG": 1.8, "xGA": 1.0},
            {"team": "Beta", "xG": 0.9, "xGA": 1.5},
        ]
        result = SoccerDataUnderstatProvider.aggregate_records(records, recent_matches=2)
        self.assertAlmostEqual(result["alpha"].xg_for, 1.5)
        self.assertAlmostEqual(result["alpha"].xg_against, 0.9)
        self.assertEqual(result["alpha"].sample_size, 2)


if __name__ == "__main__":
    unittest.main()
