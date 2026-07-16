"""把领域预测转换为稳定、可测试的报告视图模型。"""

from __future__ import annotations

import hashlib

from ..domain import (
    DecisionState,
    DirectionState,
    MatchPrediction,
    TeamFeatures,
    ValueState,
)
from ..modeling.odds import remove_vig
from .analysis import derive_markets, plain_summary
from .flags import flag_for

OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
CONFIDENCE_LABELS = {"high": "高", "mid": "中", "low": "低"}
DECISION_LABELS = {
    DecisionState.CANDIDATE.value: "候选价值",
    DecisionState.LEAN.value: "有方向",
    DecisionState.NO_EDGE.value: "无优势",
    DecisionState.ABSTAIN.value: "弃权",
}
DIRECTION_LABELS = {
    DirectionState.STRONG.value: "明确方向",
    DirectionState.MODERATE.value: "中等方向",
    DirectionState.SLIGHT.value: "轻微方向",
    DirectionState.UNAVAILABLE.value: "数据不可用",
}
DIRECTION_SHORT_LABELS = {
    DirectionState.STRONG.value: "明确",
    DirectionState.MODERATE.value: "中等",
    DirectionState.SLIGHT.value: "轻微",
    DirectionState.UNAVAILABLE.value: "不可用",
}
VALUE_LABELS = {
    ValueState.CANDIDATE.value: "候选价值",
    ValueState.WATCH.value: "价值观察",
    ValueState.NO_EDGE.value: "无价格优势",
    ValueState.UNVERIFIED.value: "未独立验证",
    ValueState.UNAVAILABLE.value: "价格不可用",
}
ANALYSIS_MODE_LABELS = {
    "hybrid": "统计模型 + 独立参考市场",
    "statistical": "独立统计模型",
    "reference_market": "独立参考市场",
    "market_baseline": "目标竞彩市场共识",
    "prior_only": "数据不足占位",
}
DATA_QUALITY_LABELS = {
    "complete": "数据完整",
    "partial": "部分数据",
    "market_only": "仅市场",
    "market_consensus": "竞彩市场共识",
    "insufficient": "数据不足",
}
SOURCE_LABELS = {
    "sporttery-official": "中国体育彩票官方接口",
    "sporttery-api": "SportteryAPI",
    "stale-cache": "历史缓存",
    "local-market": "本地参考市场快照",
    "fallback": "未提供",
}


def _source_label(value: str | None) -> str:
    if not value:
        return "未提供"
    return SOURCE_LABELS.get(value, value.replace("the-odds-api:", "The Odds API · "))


def _timestamp(day: str, value: str | None) -> str:
    if not value:
        return "未提供"
    normalized = value.replace("T", " ")
    return f"{day} {normalized}" if len(normalized) <= 8 else normalized


def _feature_payload(feature: TeamFeatures | None, fallback_team: str) -> dict:
    row = feature or TeamFeatures(fallback_team)
    available = row.source != "fallback" and any(
        value is not None for value in (row.elo, row.xg_for, row.xg_against)
    )
    return {
        "team": row.team,
        "available": available,
        "source": _source_label(row.source),
        "observed_at": row.observed_at or "未记录",
        "sample_size": row.sample_size,
        "elo": row.elo,
        "xg_for": row.xg_for,
        "xg_against": row.xg_against,
    }


def _fair_odds(probability: float) -> float | None:
    return 1 / probability if probability > 0 else None


def build_match_view(prediction: MatchPrediction) -> dict:
    match = prediction.match
    markets = derive_markets(
        prediction.score_matrix,
        prediction.final_probs,
        prediction.expected_home_goals,
        prediction.expected_away_goals,
        match.handicap,
    )
    top_label = prediction.top_scores[0].label if prediction.top_scores else "—"
    summary = plain_summary(
        match.home,
        match.away,
        prediction.final_probs,
        prediction.expected_home_goals,
        prediction.expected_away_goals,
        top_label,
        markets,
    )
    legacy_state = (
        prediction.decision_state.value
        if isinstance(prediction.decision_state, DecisionState)
        else str(prediction.decision_state)
    )
    direction_state = (
        prediction.direction_state.value
        if isinstance(prediction.direction_state, DirectionState)
        else str(prediction.direction_state)
    )
    value_state = (
        prediction.value_state.value
        if isinstance(prediction.value_state, ValueState)
        else str(prediction.value_state)
    )
    if direction_state == DirectionState.UNAVAILABLE.value:
        summary = f"本场方向数据不可用：{prediction.direction_reason}。中性先验仅用于占位展示。"

    target_odds = match.sporttery_odds
    target_probs = remove_vig(target_odds, method=prediction.devig_method) if target_odds else None
    value = None
    if prediction.value:
        value = {
            "flag": prediction.value.flag,
            "pick": prediction.value.pick.value,
            "pick_label": OUTCOME_LABELS[prediction.value.pick.value],
            "probability": prediction.value.probability,
            "odds": prediction.value.odds,
            "expected_value": prediction.value.expected_value,
            "edge": prediction.value.edge,
        }

    home_features = _feature_payload(prediction.home_features, match.home)
    away_features = _feature_payload(prediction.away_features, match.away)
    feature_available = home_features["available"] and away_features["available"]
    intel_evidence_count = (
        len(prediction.intel.evidences) + len(prediction.intel.facts)
        if prediction.intel
        else 0
    )
    intel_fact_count = len(prediction.intel.facts) if prediction.intel else 0
    intel_completeness = prediction.intel.completeness if prediction.intel else 0.0
    official_markets = {
        market.code: {
            "code": market.code,
            "label": market.label,
            "line": market.line,
            "updated_at": market.updated_at,
            "outcomes": [
                {
                    "code": outcome.code,
                    "key": outcome.key,
                    "label": outcome.label,
                    "odds": outcome.odds,
                    "trend": outcome.trend,
                }
                for outcome in market.outcomes
            ],
        }
        for market in match.sporttery_markets
    }
    market_updates = [market.updated_at for market in match.sporttery_markets if market.updated_at]
    raw_target_update = target_odds.updated_at if target_odds else max(market_updates, default="")
    target_update = _timestamp(match.business_date, raw_target_update)
    layers = [
        {
            "label": "赛程",
            "available": bool(match.source_url),
            "source": "中国体育彩票公开接口" if match.source_url else "输入快照",
            "updated_at": match.business_date,
        },
        {
            "label": "目标竞彩",
            "available": bool(official_markets),
            "source": _source_label(target_odds.source if target_odds else None),
            "updated_at": target_update,
        },
        {
            "label": "统计模型",
            "available": prediction.model_version != "unregistered" or feature_available,
            "source": prediction.model_version if prediction.model_version != "unregistered" else home_features["source"],
            "updated_at": prediction.model_trained_until or home_features["observed_at"],
        },
        {
            "label": "参考市场",
            "available": prediction.reference_market_odds is not None,
            "source": _source_label(
                prediction.reference_market_odds.source if prediction.reference_market_odds else None
            ),
            "updated_at": _timestamp(
                match.business_date,
                prediction.reference_market_odds.updated_at if prediction.reference_market_odds else None,
            ),
        },
        {
            "label": "赛前情报",
            "available": intel_evidence_count > 0,
            "source": f"{intel_evidence_count} 条可核验证据" if intel_evidence_count else "未提供",
            "updated_at": f"完整度 {intel_completeness:.0%}",
        },
    ]
    coverage_count = sum(layer["available"] for layer in layers)
    dialog_hash = hashlib.sha256(match.id.encode("utf-8")).hexdigest()[:12]
    reference_odds = prediction.reference_market_odds
    reference_probs = prediction.market_probs

    return {
        "id": match.id,
        "dialog_id": f"match-{dialog_hash}",
        "match_no": match.match_no,
        "league": match.league,
        "home": match.home,
        "away": match.away,
        "home_flag": flag_for(match.home),
        "away_flag": flag_for(match.away),
        "kickoff": match.kickoff_at[11:16] if len(match.kickoff_at) >= 16 else match.kickoff_at,
        "kickoff_full": match.kickoff_at.replace("T", " "),
        "intel_tier": match.intel_tier,
        "final": prediction.final_probs,
        "model": prediction.model_probs,
        "reference": reference_probs,
        "target_probs": target_probs,
        "official_market_probs": prediction.official_market_probs,
        "fair_odds": {
            "home": _fair_odds(prediction.final_probs.home),
            "draw": _fair_odds(prediction.final_probs.draw),
            "away": _fair_odds(prediction.final_probs.away),
        },
        "target_odds": (
            {"home": target_odds.home, "draw": target_odds.draw, "away": target_odds.away}
            if target_odds
            else None
        ),
        "reference_odds": (
            {"home": reference_odds.home, "draw": reference_odds.draw, "away": reference_odds.away}
            if reference_odds
            else None
        ),
        "recommended": prediction.recommended.value,
        "recommended_label": OUTCOME_LABELS[prediction.recommended.value],
        "direction_state": direction_state,
        "direction_state_label": DIRECTION_LABELS.get(direction_state, direction_state),
        "direction_short_label": DIRECTION_SHORT_LABELS.get(direction_state, direction_state),
        "direction_label": (
            f"{OUTCOME_LABELS[prediction.recommended.value]} · "
            f"{DIRECTION_SHORT_LABELS.get(direction_state, direction_state)}"
            if direction_state != DirectionState.UNAVAILABLE.value
            else DIRECTION_LABELS[DirectionState.UNAVAILABLE.value]
        ),
        "direction_reason": prediction.direction_reason,
        "direction_margin": prediction.direction_margin,
        "direction_probability": prediction.final_probs.get(prediction.recommended),
        "direction_rank": {
            DirectionState.STRONG.value: 3,
            DirectionState.MODERATE.value: 2,
            DirectionState.SLIGHT.value: 1,
            DirectionState.UNAVAILABLE.value: 0,
        }.get(direction_state, 0),
        "value_state": value_state,
        "value_label": VALUE_LABELS.get(value_state, value_state),
        "value_reason": prediction.value_reason,
        # v0.5.0 兼容字段，不再驱动新版报告的主状态。
        "decision_state": legacy_state,
        "decision_label": DECISION_LABELS.get(legacy_state, legacy_state),
        "decision_reason": prediction.decision_reason,
        "confidence": prediction.confidence,
        "confidence_rank": {"high": 3, "mid": 2, "low": 1}.get(prediction.confidence, 0),
        "confidence_label": CONFIDENCE_LABELS.get(prediction.confidence, prediction.confidence),
        "uncertainty": prediction.uncertainty,
        "data_quality": prediction.data_quality,
        "data_quality_label": DATA_QUALITY_LABELS.get(prediction.data_quality, prediction.data_quality),
        "analysis_mode": prediction.analysis_mode,
        "analysis_label": ANALYSIS_MODE_LABELS.get(prediction.analysis_mode, prediction.analysis_mode),
        "value": value,
        "edge": value["edge"] if value else None,
        "expected_value": value["expected_value"] if value else None,
        "xg_home": prediction.expected_home_goals,
        "xg_away": prediction.expected_away_goals,
        "top_scores": [{"label": score.label, "p": score.probability} for score in prediction.top_scores],
        "score_matrix": prediction.score_matrix,
        "markets": markets,
        "summary": summary,
        "reasons": list(prediction.reasons),
        "warnings": list(prediction.warnings),
        "intel": prediction.intel,
        "intel_evidence_count": intel_evidence_count,
        "intel_fact_count": intel_fact_count,
        "intel_completeness": intel_completeness,
        "intel_missing": list(prediction.intel.missing) if prediction.intel else ["未提供赛前情报"],
        "home_features": home_features,
        "away_features": away_features,
        "official_markets": official_markets,
        "official_market_count": len(official_markets),
        "target_update": target_update,
        "data_layers": layers,
        "coverage_count": coverage_count,
        "coverage_pct": coverage_count / len(layers),
        "is_degraded": prediction.data_quality != "complete" or bool(prediction.warnings),
        "is_demo": match.id.startswith("demo-") or bool(target_odds and target_odds.source == "demo"),
        "model_version": prediction.model_version,
        "model_trained_until": prediction.model_trained_until,
        "calibration_status": prediction.calibration_status,
        "calibration_sample_size": prediction.calibration_sample_size,
        "devig_method": prediction.devig_method,
        "as_of": prediction.as_of,
        "target_used_as_signal": prediction.target_used_as_signal,
    }
