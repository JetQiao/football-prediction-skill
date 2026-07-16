import unittest
from unittest.mock import patch

from football_prediction.domain import BacktestSummary
from football_prediction.modeling.dixon_coles import build_prediction
from football_prediction.modeling.training import passes_promotion_gate, rolling_oof_predictions
from football_prediction.providers.football_data import HistoricalMatch


class _FakeModel:
    teams = ("A", "B")

    def predict(self, home, away):
        return build_prediction(1.4, 1.1)


class TrainingTests(unittest.TestCase):
    def test_same_day_results_are_not_used_for_same_day_predictions(self):
        rows = []
        for index in range(120):
            day = f"2026-01-{index // 5 + 1:02d}"
            rows.append(HistoricalMatch(day, "A", "B", 1, 0, "H"))
        rows.extend(
            HistoricalMatch("2026-02-01", "A", "B", index % 3, (index + 1) % 2, "H")
            for index in range(5)
        )
        fitted_dates = []

        def fake_fit(_estimator, history):
            fitted_dates.append(max(row.date for row in history))
            return _FakeModel()

        with patch(
            "football_prediction.modeling.training.DixonColesEstimator.fit",
            autospec=True,
            side_effect=fake_fit,
        ):
            output = rolling_oof_predictions(rows, min_train=120, refit_every=1)

        self.assertEqual(len(output), 5)
        self.assertTrue(all(row.date == "2026-02-01" for row in output))
        self.assertTrue(all(day < "2026-02-01" for day in fitted_dates))

    def test_promotion_gate_requires_real_brier_improvement_and_low_ece(self):
        passing = BacktestSummary(
            matches=100,
            accuracy=0.5,
            brier=0.190,
            log_loss=0.969,
            roi=0,
            max_drawdown=0,
            bets=0,
            baseline_brier=0.192,
            baseline_log_loss=0.970,
            rps=0.190,
            baseline_rps=0.191,
            ece=0.025,
        )
        failing = BacktestSummary(
            **{
                **passing.__dict__,
                "brier": 0.192,
                "ece": 0.04,
            }
        )
        self.assertTrue(passes_promotion_gate(passing))
        self.assertFalse(passes_promotion_gate(failing))


if __name__ == "__main__":
    unittest.main()
