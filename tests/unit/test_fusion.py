import unittest

from football_prediction.domain import IntelEvidence, MatchIntel, Outcome, Probability3
from football_prediction.modeling.fusion import apply_intelligence, logarithmic_pool


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


if __name__ == "__main__":
    unittest.main()
