"""把概率方向与价格价值拆成两个相互独立的可解释状态。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain import (
    DecisionState,
    DirectionState,
    Outcome,
    Probability3,
    ThreeWayOdds,
    ValueAssessment,
    ValueState,
)
from ..modeling.odds import assess_value

OUTCOME_LABELS = {
    Outcome.HOME: "主胜",
    Outcome.DRAW: "平局",
    Outcome.AWAY: "客胜",
}

# 方向强度只描述概率分布的清晰程度，不代表价格存在可下注价值。
STRONG_MIN_PROBABILITY = 0.50
STRONG_MIN_MARGIN = 0.18
MODERATE_MIN_PROBABILITY = 0.40
MODERATE_MIN_MARGIN = 0.08


@dataclass(frozen=True)
class ConfidenceAssessment:
    level: str
    uncertainty: float
    data_quality: str


@dataclass(frozen=True)
class DecisionAssessment:
    """旧版单状态兼容结果。"""

    state: DecisionState
    reason: str
    value: ValueAssessment | None = None


@dataclass(frozen=True)
class DirectionAssessment:
    state: DirectionState
    outcome: Outcome | None
    probability: float
    margin: float
    reason: str


@dataclass(frozen=True)
class ValueDecisionAssessment:
    state: ValueState
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
    official_market_ready: bool = False,
) -> ConfidenceAssessment:
    independent_ready = statistical_ready or reference_market is not None
    direction_ready = independent_ready or official_market_ready
    if not direction_ready:
        return ConfidenceAssessment("low", 1.0, "insufficient")

    coverage = 0.30
    coverage += 0.28 if statistical_ready else 0.0
    coverage += 0.22 if reference_market is not None else 0.0
    coverage += 0.18 if official_market_ready else 0.0
    coverage += 0.12 if calibration_status == "validated" else 0.04 if calibration_status == "provisional" else 0
    coverage += 0.05 * intel_completeness
    if is_a_tier and intel_completeness < 0.6:
        coverage -= 0.08
    coverage = max(0.0, min(1.0, coverage))

    entropy = _entropy(probabilities)
    disagreement = (
        _disagreement(probabilities, reference_market)
        if reference_market is not None
        else 0.0 if official_market_ready and not statistical_ready else 0.5
    )
    if independent_ready:
        sample_penalty = (
            0.0
            if calibration_sample_size >= 300
            else 0.08 if calibration_sample_size >= 100 else 0.16
        )
    else:
        # 目标竞彩市场共识可以支持方向，但没有独立模型样本，因此置信度最多为中。
        sample_penalty = 0.08
    uncertainty = 0.45 * entropy + 0.2 * disagreement + 0.25 * (1 - coverage) + sample_penalty
    uncertainty = max(0.0, min(1.0, uncertainty))

    if (
        independent_ready
        and calibration_status == "validated"
        and calibration_sample_size >= 100
        and uncertainty <= 0.42
        and max(probabilities.vector()) >= 0.45
    ):
        level = "high"
    elif uncertainty <= 0.78:
        level = "mid"
    else:
        level = "low"

    if statistical_ready and reference_market is not None and calibration_status == "validated":
        quality = "complete"
    elif official_market_ready and not independent_ready:
        quality = "market_consensus"
    elif reference_market is not None and not statistical_ready:
        quality = "market_only"
    else:
        quality = "partial"
    return ConfidenceAssessment(level, uncertainty, quality)


def assess_direction(
    probabilities: Probability3,
    *,
    analysis_mode: str,
) -> DirectionAssessment:
    """始终先回答概率偏向；只有中性占位先验才视为方向不可用。"""

    if analysis_mode == "prior_only":
        return DirectionAssessment(
            DirectionState.UNAVAILABLE,
            None,
            0.0,
            0.0,
            "缺少统计模型、参考市场或完整官方玩法，无法形成有效方向",
        )

    ranked = sorted(
        ((probabilities.get(outcome), outcome) for outcome in Outcome),
        reverse=True,
        key=lambda item: item[0],
    )
    top_probability, outcome = ranked[0]
    margin = top_probability - ranked[1][0]
    if top_probability >= STRONG_MIN_PROBABILITY and margin >= STRONG_MIN_MARGIN:
        state = DirectionState.STRONG
        strength = "明确"
    elif top_probability >= MODERATE_MIN_PROBABILITY and margin >= MODERATE_MIN_MARGIN:
        state = DirectionState.MODERATE
        strength = "中等"
    else:
        state = DirectionState.SLIGHT
        strength = "轻微"

    basis = {
        "hybrid": "统计模型与独立参考市场",
        "statistical": "独立统计模型",
        "reference_market": "独立参考市场",
        "market_baseline": "竞彩市场概率",
    }.get(analysis_mode, "当前概率分布")
    return DirectionAssessment(
        state,
        outcome,
        top_probability,
        margin,
        f"{basis}{strength}偏向{OUTCOME_LABELS[outcome]}："
        f"{top_probability:.1%}，领先第二结果 {margin:.1%}",
    )


def assess_value_decision(
    probabilities: Probability3,
    target_odds: ThreeWayOdds | None,
    *,
    independent_ready: bool,
    target_used_as_signal: bool,
    confidence: ConfidenceAssessment,
    calibration_status: str,
    value_threshold: float,
    devig_method: str,
) -> ValueDecisionAssessment:
    """只判断目标价格价值，不负责决定是否输出概率方向。"""

    if target_odds is None:
        return ValueDecisionAssessment(ValueState.UNAVAILABLE, "目标竞彩胜平负尚无可比较价格")
    if not independent_ready:
        return ValueDecisionAssessment(
            ValueState.UNVERIFIED,
            "方向来自目标竞彩市场共识，不能用同一价格独立验证价值",
        )
    if target_used_as_signal:
        return ValueDecisionAssessment(
            ValueState.UNVERIFIED,
            "目标竞彩价格已参与概率形成，价值判断保持未独立验证",
        )
    if confidence.level == "low" or confidence.uncertainty > 0.72:
        return ValueDecisionAssessment(ValueState.UNVERIFIED, "独立概率不确定性过高，暂不验证价格价值")

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
        return ValueDecisionAssessment(
            ValueState.CANDIDATE,
            "独立概率、校准状态和价格优势均通过门槛",
            value,
        )
    if value.expected_value <= 0 or value.edge <= 0:
        return ValueDecisionAssessment(ValueState.NO_EDGE, "当前竞彩价格没有正向独立优势", value)
    if calibration_status != "validated":
        return ValueDecisionAssessment(
            ValueState.WATCH,
            "存在正向价格差，但模型尚未通过校准晋级门槛",
            value,
        )
    return ValueDecisionAssessment(ValueState.WATCH, "正向价格差未达到候选价值阈值", value)


def legacy_decision(
    direction: DirectionAssessment,
    value: ValueDecisionAssessment,
) -> DecisionAssessment:
    """把双状态压缩成旧版字段，避免破坏历史 JSON 消费者。"""

    if direction.state == DirectionState.UNAVAILABLE:
        state = DecisionState.ABSTAIN
    elif value.state == ValueState.CANDIDATE:
        state = DecisionState.CANDIDATE
    elif value.state == ValueState.NO_EDGE:
        state = DecisionState.NO_EDGE
    else:
        state = DecisionState.LEAN
    return DecisionAssessment(
        state,
        f"{direction.reason}；{value.reason}",
        value.value,
    )


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
    """兼容旧调用方；新版代码应分别调用方向和价值评估。"""

    analysis_mode = (
        "statistical"
        if independent_ready
        else "market_baseline" if target_used_as_signal else "prior_only"
    )
    direction = assess_direction(probabilities, analysis_mode=analysis_mode)
    value = assess_value_decision(
        probabilities,
        target_odds,
        independent_ready=independent_ready,
        target_used_as_signal=target_used_as_signal,
        confidence=confidence,
        calibration_status=calibration_status,
        value_threshold=value_threshold,
        devig_method=devig_method,
    )
    return legacy_decision(direction, value)
