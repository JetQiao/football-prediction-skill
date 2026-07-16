"""赔率概率与价值计算。"""

from __future__ import annotations

import math
from collections.abc import Sequence

from scipy.optimize import brentq

from ..domain import Outcome, Probability3, ThreeWayOdds, ValueAssessment

DEVIG_METHODS = ("multiplicative", "power", "shin")


def _power_probabilities(raw: Sequence[float]) -> list[float]:
    def objective(exponent: float) -> float:
        return sum(value**exponent for value in raw) - 1.0

    lower, upper = 0.05, 10.0
    if objective(lower) * objective(upper) > 0:
        return list(raw)
    exponent = brentq(objective, lower, upper)
    return [value**exponent for value in raw]


def _shin_probabilities(raw: Sequence[float]) -> list[float]:
    overround = sum(raw)
    if overround <= 1:
        return list(raw)

    def probabilities(z: float) -> list[float]:
        denominator = 2 * (1 - z)
        return [
            (math.sqrt(z * z + 4 * (1 - z) * value * value / overround) - z) / denominator
            for value in raw
        ]

    def objective(z: float) -> float:
        return sum(probabilities(z)) - 1.0

    try:
        z = brentq(objective, 0.0, 0.999999)
    except ValueError:
        return list(raw)
    return probabilities(z)


def remove_vig(odds: ThreeWayOdds, *, method: str = "multiplicative") -> Probability3:
    """把十进制赔率转换为去水概率，支持比例法、Power 和 Shin。"""

    raw = [1 / value for value in odds.vector()]
    if method == "multiplicative":
        values = raw
    elif method == "power":
        values = _power_probabilities(raw)
    elif method == "shin":
        values = _shin_probabilities(raw)
    else:
        raise ValueError(f"未知去水方法：{method}")
    return Probability3.normalized(values)


def select_devig_method(
    odds_rows: Sequence[ThreeWayOdds],
    outcomes: Sequence[Outcome],
) -> tuple[str, dict[str, float]]:
    """按历史 Log-loss 选择去水方法；只用于训练阶段。"""

    if len(odds_rows) != len(outcomes) or not odds_rows:
        raise ValueError("赔率与赛果数量必须一致且不能为空")
    scores: dict[str, float] = {}
    for method in DEVIG_METHODS:
        loss = 0.0
        for odds, actual in zip(odds_rows, outcomes, strict=True):
            probability = remove_vig(odds, method=method).get(actual)
            loss -= math.log(max(1e-12, probability))
        scores[method] = loss / len(outcomes)
    return min(scores, key=scores.get), scores


def assess_value(
    probabilities: Probability3,
    offered: ThreeWayOdds,
    *,
    threshold: float = 0.05,
    devig_method: str = "multiplicative",
) -> ValueAssessment:
    offered_implied = remove_vig(offered, method=devig_method)
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
