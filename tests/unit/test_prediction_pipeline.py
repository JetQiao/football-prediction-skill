import tempfile
import unittest
from pathlib import Path

from football_prediction.config import AppPaths, Settings
from football_prediction.domain import MarketRole, Match, TeamFeatures, ThreeWayOdds
from football_prediction.prediction import PredictionContext, PredictionPipeline


class PredictionPipelineTests(unittest.TestCase):
    def _pipeline(self, root: Path) -> PredictionPipeline:
        return PredictionPipeline(Settings(paths=AppPaths(root / "data", root / "cache", root / "config")))

    @staticmethod
    def _match() -> Match:
        return Match(
            id="match-1",
            business_date="2026-07-16",
            match_no="周四001",
            league="测试联赛",
            home="主队",
            away="客队",
            kickoff_at="2026-07-16T20:00:00+08:00",
            sporttery_odds=ThreeWayOdds(
                2.1,
                3.2,
                3.4,
                "sporttery",
                "2026-07-16T10:00:00+08:00",
                MarketRole.TARGET,
            ),
        )

    def test_rejects_cutoff_at_or_after_kickoff(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = self._pipeline(Path(temp))
            with self.assertRaisesRegex(ValueError, "预测截点必须早于开赛"):
                pipeline.predict(
                    PredictionContext(
                        match=self._match(),
                        home_features=TeamFeatures("主队"),
                        away_features=TeamFeatures("客队"),
                        target_market_odds=self._match().sporttery_odds,
                        as_of="2026-07-16T20:00:00+08:00",
                    )
                )

    def test_rejects_target_price_as_reference_market(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = self._pipeline(Path(temp))
            target = self._match().sporttery_odds
            with self.assertRaisesRegex(ValueError, "参考市场角色错误"):
                pipeline.predict(
                    PredictionContext(
                        match=self._match(),
                        home_features=TeamFeatures("主队"),
                        away_features=TeamFeatures("客队"),
                        reference_market_odds=target,
                        target_market_odds=target,
                        as_of="2026-07-16T12:00:00+08:00",
                    )
                )

    def test_rejects_feature_observed_after_cutoff(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = self._pipeline(Path(temp))
            with self.assertRaisesRegex(ValueError, "主队特征更新时间晚于预测截点"):
                pipeline.predict(
                    PredictionContext(
                        match=self._match(),
                        home_features=TeamFeatures(
                            "主队",
                            elo=1800,
                            source="test",
                            observed_at="2026-07-16T13:00:00+08:00",
                        ),
                        away_features=TeamFeatures("客队", elo=1700, source="test"),
                        target_market_odds=self._match().sporttery_odds,
                        as_of="2026-07-16T12:00:00+08:00",
                    )
                )


if __name__ == "__main__":
    unittest.main()
