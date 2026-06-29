import unittest

from football_prediction.domain import Outcome, Probability3, ThreeWayOdds
from football_prediction.modeling.odds import assess_value, remove_vig


class OddsTests(unittest.TestCase):
    def test_remove_vig_normalizes_probabilities(self):
        odds = ThreeWayOdds(2.0, 3.5, 4.0, "test", "2026-01-01T00:00:00Z")
        probabilities = remove_vig(odds)
        self.assertAlmostEqual(sum(probabilities.vector()), 1.0)
        self.assertGreater(probabilities.home, probabilities.away)

    def test_value_uses_expected_value_and_edge(self):
        odds = ThreeWayOdds(2.2, 3.4, 3.2, "test", "2026-01-01T00:00:00Z")
        assessment = assess_value(Probability3(0.52, 0.25, 0.23), odds, threshold=0.05)
        self.assertEqual(assessment.pick, Outcome.HOME)
        self.assertEqual(assessment.flag, "value")
        self.assertAlmostEqual(assessment.expected_value, 0.144)


if __name__ == "__main__":
    unittest.main()
