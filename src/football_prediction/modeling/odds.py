"""赔率概率与价值计算。"""

from __future__ import annotations

from ..domain import Outcome, Probability3, ThreeWayOdds, ValueAssessment


def remove_vig(odds: ThreeWayOdds) -> Probability3:
    return Probability3.normalized(1 / value for value in odds.vector())


def assess_value(
    probabilities: Probability3,
    offered: ThreeWayOdds,
    *,
    threshold: float = 0.05,
) -> ValueAssessment:
    offered_implied = remove_vig(offered)
    candidates: list[ValueAssessment] = []
    for outcome in Outcome:
        probability = probabilities.get(outcome)
        decimal_odds = offered.get(outcome)
        expected_value = probability * decimal_odds - 1
        edge = probability - offered_implied.get(outcome)
        flag = (
            "value" if expected_value >= threshold and edge > 0 else "risk" if expected_value < -threshold else "fair"
        )
        candidates.append(ValueAssessment(outcome, probability, decimal_odds, expected_value, edge, flag))
    return max(candidates, key=lambda item: item.expected_value)
