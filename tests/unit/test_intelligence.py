import unittest

from football_prediction.domain import IntelEvidence, MatchIntel, Outcome
from football_prediction.intelligence.validator import validate_intel


class IntelligenceTests(unittest.TestCase):
    def test_rejects_post_kickoff_evidence(self):
        evidence = IntelEvidence(
            "赛后消息",
            "https://example.com/post",
            "2026-01-01T21:00:00+08:00",
            0.9,
            -0.03,
            Outcome.HOME,
        )
        with self.assertRaisesRegex(ValueError, "未来数据泄漏"):
            validate_intel(MatchIntel("1", (evidence,), 0.5), kickoff_at="2026-01-01T20:00:00+08:00")

    def test_rejects_oversized_impact(self):
        with self.assertRaises(ValueError):
            IntelEvidence("x", "https://example.com", "2026-01-01T00:00:00Z", 1, 0.2, Outcome.HOME)


if __name__ == "__main__":
    unittest.main()
