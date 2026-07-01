import unittest

from football_prediction.config import Settings
from football_prediction.domain import (
    IntelEvidence,
    Match,
    MatchIntel,
    Outcome,
    Probability3,
    TeamFeatures,
    ThreeWayOdds,
)
from football_prediction.modeling.fusion import PredictionEngine, apply_intelligence, logarithmic_pool


class FusionTests(unittest.TestCase):
    def test_log_pool_stays_normalized(self):
        result = logarithmic_pool(Probability3(0.5, 0.3, 0.2), Probability3(0.4, 0.32, 0.28), 0.58)
        self.assertAlmostEqual(sum(result.vector()), 1.0)
        self.assertGreater(result.home, result.away)

    def test_intel_is_bounded(self):
        evidence = IntelEvidence(
            "官方确认主力复出",
            "https://example.com/news",
            "2026-01-01T09:00:00+08:00",
            1.0,
            0.08,
            Outcome.HOME,
        )
        intel = MatchIntel("1", (evidence,) * 10, 1.0)
        before = Probability3(0.4, 0.3, 0.3)
        after = apply_intelligence(before, intel, 0.12)
        self.assertGreater(after.home, before.home)
        self.assertLess(after.home, 0.45)

    def test_features_present_blend_official_sp_into_final(self):
        match = Match(
            id="real-2",
            business_date="2026-07-01",
            match_no="周三080",
            league="世界杯",
            home="英格兰",
            away="刚果金",
            kickoff_at="2026-07-01T20:00:00+08:00",
            sporttery_odds=ThreeWayOdds(1.17, 5.25, 12.0, "sporttery-official", "09:15:46"),
        )
        home = TeamFeatures("英格兰", elo=2038, source="eloratings.net")
        away = TeamFeatures("刚果金", elo=1652, source="eloratings.net")
        from football_prediction.modeling.dixon_coles import predict_from_features
        from football_prediction.modeling.odds import remove_vig

        model = predict_from_features(home, away).probabilities
        sp = remove_vig(match.sporttery_odds)
        prediction = PredictionEngine(Settings()).predict(match, home, away)
        # 强队被合理评级，且最终概率被拉向官方 SP（介于纯模型与 SP 去水之间）。
        self.assertGreater(prediction.final_probs.home, 0.68)
        self.assertGreaterEqual(prediction.final_probs.home, min(model.home, sp.home) - 1e-6)
        self.assertLessEqual(prediction.final_probs.home, max(model.home, sp.home) + 1e-6)
        self.assertIn("市场权重", " ".join(prediction.reasons))
        self.assertNotEqual(prediction.confidence, "low")

    def test_fallback_model_does_not_emit_value_signal(self):
        match = Match(
            id="real-1",
            business_date="2026-07-01",
            match_no="周三001",
            league="世界杯",
            home="主队",
            away="客队",
            kickoff_at="2026-07-01T20:00:00+08:00",
            sporttery_odds=ThreeWayOdds(1.80, 3.40, 4.20, "sporttery-official", "12:00:00"),
        )
        prediction = PredictionEngine(Settings()).predict(match, TeamFeatures("主队"), TeamFeatures("客队"))
        self.assertIsNone(prediction.value)
        self.assertGreater(prediction.final_probs.home, 0.5)
        self.assertEqual(prediction.confidence, "low")
        self.assertIn("已暂停输出价值信号", " ".join(prediction.warnings))


if __name__ == "__main__":
    unittest.main()
