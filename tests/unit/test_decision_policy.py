import unittest

from football_prediction.domain import (
    DecisionState,
    DirectionState,
    MarketRole,
    Probability3,
    ThreeWayOdds,
    ValueState,
)
from football_prediction.policy.decision import (
    ConfidenceAssessment,
    assess_decision,
    assess_direction,
    assess_value_decision,
)


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

    def test_target_price_signal_keeps_direction_but_marks_value_unverified(self):
        direction = assess_direction(self.probabilities, analysis_mode="market_baseline")
        value = assess_value_decision(
            self.probabilities,
            self.target,
            independent_ready=False,
            target_used_as_signal=True,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        legacy = assess_decision(
            self.probabilities,
            self.target,
            independent_ready=False,
            target_used_as_signal=True,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        self.assertEqual(direction.state, DirectionState.STRONG)
        self.assertEqual(value.state, ValueState.UNVERIFIED)
        self.assertIsNone(value.value)
        self.assertEqual(legacy.state, DecisionState.LEAN)

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

    def test_value_states_cover_watch_no_edge_and_unavailable(self):
        watch = assess_value_decision(
            self.probabilities,
            self.target,
            independent_ready=True,
            target_used_as_signal=False,
            confidence=self.confidence,
            calibration_status="provisional",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        no_edge = assess_value_decision(
            self.probabilities,
            ThreeWayOdds(1.60, 3.00, 3.50, "sporttery", "", MarketRole.TARGET),
            independent_ready=True,
            target_used_as_signal=False,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        unavailable = assess_value_decision(
            self.probabilities,
            None,
            independent_ready=True,
            target_used_as_signal=False,
            confidence=self.confidence,
            calibration_status="validated",
            value_threshold=0.05,
            devig_method="multiplicative",
        )
        self.assertEqual(watch.state, ValueState.WATCH)
        self.assertEqual(no_edge.state, ValueState.NO_EDGE)
        self.assertEqual(unavailable.state, ValueState.UNAVAILABLE)

    def test_direction_strength_thresholds_match_report_semantics(self):
        cases = (
            (Probability3(0.57, 0.22, 0.21), DirectionState.STRONG),
            (Probability3(0.48, 0.26, 0.26), DirectionState.MODERATE),
            (Probability3(0.36, 0.24, 0.40), DirectionState.SLIGHT),
        )
        for probabilities, expected in cases:
            with self.subTest(probabilities=probabilities):
                result = assess_direction(probabilities, analysis_mode="market_baseline")
                self.assertEqual(result.state, expected)

    def test_prior_only_is_the_only_unavailable_direction(self):
        result = assess_direction(self.probabilities, analysis_mode="prior_only")
        self.assertEqual(result.state, DirectionState.UNAVAILABLE)
        self.assertIsNone(result.outcome)

    def test_market_consensus_slate_does_not_collapse_into_abstentions(self):
        probabilities = (
            Probability3(0.57, 0.22, 0.21),
            Probability3(0.23, 0.25, 0.52),
            Probability3(0.67, 0.19, 0.14),
            Probability3(0.29, 0.27, 0.44),
            Probability3(0.48, 0.26, 0.26),
            Probability3(0.41, 0.28, 0.31),
            Probability3(0.46, 0.25, 0.29),
            Probability3(0.36, 0.24, 0.40),
            Probability3(0.67, 0.19, 0.14),
            Probability3(0.64, 0.19, 0.17),
        )
        states = [
            assess_direction(row, analysis_mode="market_baseline").state
            for row in probabilities
        ]
        self.assertEqual(states.count(DirectionState.STRONG), 5)
        self.assertEqual(states.count(DirectionState.MODERATE), 4)
        self.assertEqual(states.count(DirectionState.SLIGHT), 1)
        self.assertNotIn(DirectionState.UNAVAILABLE, states)


if __name__ == "__main__":
    unittest.main()
