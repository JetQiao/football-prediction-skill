import unittest
import json
import tempfile
from pathlib import Path

from football_prediction.backtest.daily import evaluate_daily_files
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

    def test_daily_evaluation_matches_ids_and_builds_strata(self):
        prediction = {
            "business_date": "2026-07-03",
            "run_id": "run-1",
            "predictions": [
                {
                    "match": {
                        "id": "1001",
                        "match_no": "周五001",
                        "league": "测试联赛",
                        "sporttery_odds": {
                            "home": 2.0,
                            "draw": 3.2,
                            "away": 3.6,
                            "source": "snapshot",
                            "updated_at": "12:00:00",
                        },
                    },
                    "final_probs": {"home": 0.55, "draw": 0.25, "away": 0.20},
                    "confidence": "mid",
                    "analysis_mode": "hybrid",
                }
            ],
        }
        results = {"results": [{"match_id": "1001", "score": "2:1"}]}
        with tempfile.TemporaryDirectory() as temp:
            prediction_path = Path(temp) / "prediction.json"
            result_path = Path(temp) / "results.json"
            prediction_path.write_text(json.dumps(prediction), encoding="utf-8")
            result_path.write_text(json.dumps(results), encoding="utf-8")

            evaluation = evaluate_daily_files(prediction_path, result_path)

        self.assertEqual(evaluation["matched"], 1)
        self.assertEqual(evaluation["overall"]["accuracy"], 1.0)
        self.assertEqual(evaluation["by_confidence"]["mid"]["matches"], 1)


if __name__ == "__main__":
    unittest.main()
