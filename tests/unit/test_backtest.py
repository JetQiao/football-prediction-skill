import unittest

from football_prediction.backtest.metrics import BacktestObservation, evaluate
from football_prediction.domain import Outcome, Probability3, ThreeWayOdds


class BacktestTests(unittest.TestCase):
    def test_metrics_and_equity(self):
        odds = ThreeWayOdds(2.2, 3.4, 3.2, "test", "2026-01-01")
        rows = [
            BacktestObservation(Probability3(0.55, 0.25, 0.20), Outcome.HOME, odds),
            BacktestObservation(Probability3(0.20, 0.30, 0.50), Outcome.HOME, odds),
        ]
        summary = evaluate(rows)
        self.assertEqual(summary.matches, 2)
        self.assertAlmostEqual(summary.accuracy, 0.5)
        self.assertGreater(summary.brier, 0)
        self.assertGreaterEqual(summary.bets, 1)
        self.assertIsNotNone(summary.baseline_brier)


if __name__ == "__main__":
    unittest.main()
