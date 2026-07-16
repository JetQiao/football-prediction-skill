import unittest

from football_prediction.domain import DecisionState, MarketRole, Probability3, ThreeWayOdds
from football_prediction.policy.decision import ConfidenceAssessment, assess_decision


class DecisionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.probabilities = Probability3(0.55, 0.25, 0.20)
        self.target = ThreeWayOdds(
            2.2,
            3.4,
            3.2,
            "sporttery",
            "2026-07-16T10:00:00+08:00",
            MarketRole.TARGET,
        )
        self.confidence = ConfidenceAssessment("mid", 0.4, "complete")

    def test_target_price_used_as_signal_forces_abstention(self):
        result = assess_decision(
            self.probabilities,
            self.target,
            independent_ready=True,
            target_used_as_signal=True,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        self.assertEqual(result.state, DecisionState.ABSTAIN)
        self.assertIsNone(result.value)

    def test_candidate_requires_validated_calibration(self):
        provisional = assess_decision(
            self.probabilities,
            self.target,
            independent_ready=True,
            target_used_as_signal=False,
            confidence=self.confidence,
            calibration_status="provisional",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        validated = assess_decision(
            self.probabilities,
            self.target,
            independent_ready=True,
            target_used_as_signal=False,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        self.assertEqual(provisional.state, DecisionState.LEAN)
        self.assertEqual(validated.state, DecisionState.CANDIDATE)


if __name__ == "__main__":
    unittest.main()
