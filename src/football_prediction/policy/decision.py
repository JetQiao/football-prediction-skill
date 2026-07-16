"""把概率质量、数据覆盖和价格优势转换为可解释决策状态。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain import DecisionState, Probability3, ThreeWayOdds, ValueAssessment
from ..modeling.odds import assess_value


@dataclass(frozen=True)
class ConfidenceAssessment:
    level: str
    uncertainty: float
    data_quality: str


@dataclass(frozen=True)
class DecisionAssessment:
    state: DecisionState
    reason: str
    value: ValueAssessment | None = None


def _entropy(probabilities: Probability3) -> float:
    raw = -sum(value * math.log(max(1e-12, value)) for value in probabilities.vector())
    return raw / math.log(3)


def _disagreement(left: Probability3, right: Probability3 | None) -> float:
    if right is None:
        return 0.5
    return sum(abs(a - b) for a, b in zip(left.vector(), right.vector(), strict=True)) / 2


def assess_confidence(
    probabilities: Probability3,
    *,
    statistical_ready: bool,
    reference_market: Probability3 | None,
    calibration_status: str,
    calibration_sample_size: int,
    intel_completeness: float,
    is_a_tier: bool,
) -> ConfidenceAssessment:
    independent_ready = statistical_ready or reference_market is not None
    if not independent_ready:
        quality = "market_only" if reference_market is not None else "insufficient"
        return ConfidenceAssessment("low", 1.0, quality)

    coverage = 0.35
    coverage += 0.25 if statistical_ready else 0.0
    coverage += 0.2 if reference_market is not None else 0.0
    coverage += 0.15 if calibration_status == "validated" else 0.05 if calibration_status == "provisional" else 0
    coverage += 0.05 * intel_completeness
    if is_a_tier and intel_completeness < 0.6:
        coverage -= 0.08
    coverage = max(0.0, min(1.0, coverage))

    entropy = _entropy(probabilities)
    disagreement = _disagreement(probabilities, reference_market)
    sample_penalty = 0.0 if calibration_sample_size >= 300 else 0.08 if calibration_sample_size >= 100 else 0.16
    uncertainty = 0.45 * entropy + 0.25 * disagreement + 0.3 * (1 - coverage) + sample_penalty
    uncertainty = max(0.0, min(1.0, uncertainty))

    if (
        calibration_status == "validated"
        and calibration_sample_size >= 100
        and uncertainty <= 0.42
        and max(probabilities.vector()) >= 0.45
    ):
        level = "high"
    elif uncertainty <= 0.78:
        level = "mid"
    else:
        level = "low"

    quality = (
        "complete"
        if statistical_ready and reference_market is not None and calibration_status == "validated"
        else "partial"
    )
    return ConfidenceAssessment(level, uncertainty, quality)


def assess_decision(
    probabilities: Probability3,
    target_odds: ThreeWayOdds | None,
    *,
    independent_ready: bool,
    target_used_as_signal: bool,
    confidence: ConfidenceAssessment,
    calibration_status: str,
    value_threshold: float,
    devig_method: str,
) -> DecisionAssessment:
    if not independent_ready:
        return DecisionAssessment(DecisionState.ABSTAIN, "缺少独立统计模型或参考市场")
    if target_used_as_signal:
        return DecisionAssessment(DecisionState.ABSTAIN, "目标竞彩价格已参与概率形成，禁止循环证明价值")
    if confidence.level == "low" or confidence.uncertainty > 0.72:
        return DecisionAssessment(DecisionState.ABSTAIN, "概率不确定性过高")
    if target_odds is None:
        return DecisionAssessment(DecisionState.LEAN, "有概率方向，但目标竞彩玩法尚无可比较价格")

    value = assess_value(
        probabilities,
        target_odds,
        threshold=value_threshold,
        devig_method=devig_method,
    )
    if (
        value.flag == "value"
        and calibration_status == "validated"
        and confidence.level in ("high", "mid")
    ):
        return DecisionAssessment(DecisionState.CANDIDATE, "独立概率、校准状态和价格优势均通过门槛", value)
    if value.expected_value <= 0 or value.edge <= 0:
        return DecisionAssessment(DecisionState.NO_EDGE, "当前竞彩价格没有正向独立优势", value)
    if calibration_status != "validated":
        return DecisionAssessment(DecisionState.LEAN, "存在方向性优势，但模型尚未通过校准晋级门槛", value)
    return DecisionAssessment(DecisionState.LEAN, "优势未达到候选价值阈值", value)
