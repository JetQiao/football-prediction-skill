"""统计层、市场层和情报残差的概率融合。"""

from __future__ import annotations

import math

from ..config import Settings
from ..domain import Match, MatchIntel, MatchPrediction, Outcome, Probability3, TeamFeatures, ThreeWayOdds
from ..intelligence.validator import validate_intel
from .calibration import TemperatureCalibrator
from .dixon_coles import DixonColesModel, predict_from_features
from .market_calibration import MarketCalibration, calibrate_from_official_markets
from .matrix import blend_matrices, matrix_expected_goals, matrix_top_scores, tilt_matrix
from .odds import assess_value, remove_vig


def logarithmic_pool(model: Probability3, market: Probability3, market_weight: float) -> Probability3:
    values = [
        math.exp((1 - market_weight) * math.log(max(1e-12, p_model)) + market_weight * math.log(max(1e-12, p_market)))
        for p_model, p_market in zip(model.vector(), market.vector(), strict=True)
    ]
    return Probability3.normalized(values)


def apply_intelligence(probabilities: Probability3, intel: MatchIntel | None, max_logit: float) -> Probability3:
    if not intel or not intel.evidences:
        return probabilities
    effects = {outcome: 0.0 for outcome in Outcome}
    for evidence in intel.evidences:
        effects[evidence.outcome] += evidence.impact * evidence.credibility
    effects = {outcome: max(-max_logit, min(max_logit, value)) for outcome, value in effects.items()}
    logits = [math.log(max(1e-12, probabilities.get(outcome))) + effects[outcome] for outcome in Outcome]
    peak = max(logits)
    return Probability3.normalized(math.exp(value - peak) for value in logits)


class PredictionEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        model: DixonColesModel | None = None,
        calibrator: TemperatureCalibrator | None = None,
    ) -> None:
        self.settings = settings.validate()
        self.model = model
        self.calibrator = calibrator

    def predict(
        self,
        match: Match,
        home_features: TeamFeatures,
        away_features: TeamFeatures,
        *,
        market_odds: ThreeWayOdds | None = None,
        intel: MatchIntel | None = None,
    ) -> MatchPrediction:
        dc = (
            self.model.predict(match.home, match.away)
            if self.model and match.home in self.model.teams and match.away in self.model.teams
            else predict_from_features(home_features, away_features)
        )
        feature_ready = all(
            feature.source != "fallback"
            and any(value is not None for value in (feature.elo, feature.xg_for, feature.xg_against))
            for feature in (home_features, away_features)
        )
        external_probs = remove_vig(market_odds) if market_odds else None
        official_calibration = calibrate_from_official_markets(match, dc)
        official_probs = official_calibration.prediction.probabilities if official_calibration else None
        independent_ready = feature_ready or external_probs is not None

        fused = dc.probabilities
        matrix = dc.matrix
        if official_calibration:
            if feature_ready:
                fused = logarithmic_pool(fused, official_probs, self.settings.official_market_weight)
                matrix = blend_matrices(dc.matrix, official_calibration.prediction.matrix, self.settings.official_market_weight)
            else:
                # 没有独立实力数据时，使用多玩法联合反推的市场基线，避免固定中性期望进球。
                fused = official_probs
                matrix = official_calibration.prediction.matrix
        if external_probs:
            fused = logarithmic_pool(fused, external_probs, self.settings.market_weight) if feature_ready or official_probs else external_probs

        analysis_mode = self._analysis_mode(feature_ready, external_probs is not None, official_calibration is not None)
        agreement_layer = external_probs or official_probs
        if intel:
            validate_intel(intel, kickoff_at=match.kickoff_at)
        final = apply_intelligence(fused, intel, self.settings.max_intel_logit)
        if self.calibrator:
            final = self.calibrator.transform(final)

        final_matrix = tilt_matrix(matrix, final)
        expected_home_goals, expected_away_goals = matrix_expected_goals(final_matrix)
        top_scores = matrix_top_scores(final_matrix)
        confidence = self._confidence(final, dc.probabilities, agreement_layer, intel, independent_ready)
        # 官方 SP 不能既充当唯一概率来源又充当价值比较对象，避免循环论证。
        value_eligible = bool(match.sporttery_odds and independent_ready and confidence != "low")
        value = (
            assess_value(final, match.sporttery_odds, threshold=self.settings.value_threshold)
            if value_eligible and match.sporttery_odds
            else None
        )
        recommended = final.best()
        reasons = self._reasons(
            match,
            home_features,
            away_features,
            dc.probabilities,
            external_probs,
            intel,
            official_calibration,
            analysis_mode,
        )
        if feature_ready and official_calibration:
            reasons.append(f"官方多玩法以 {self.settings.official_market_weight:.0%} 市场权重参与融合")
        warnings: list[str] = []
        if analysis_mode == "market_baseline":
            warnings.append("缺少独立实力特征，当前结论属于多玩法市场基线，不是独立模型优势")
        elif analysis_mode == "prior_only":
            warnings.append("当前没有完整官方玩法、实力特征或外部市场，仅保留低置信占位先验")
        elif not external_probs:
            warnings.append("缺少同一预测时点的外部锐角市场，价值判断需谨慎")
        if match.sporttery_odds is None and match.sporttery_markets:
            warnings.append("普通胜平负尚未开售，已使用当前开放玩法联合推演，不会漏掉本场")
        if match.sporttery_markets and not official_calibration:
            warnings.append("已获取的官方玩法选项不完整，暂未进入多玩法联合校准")
        if match.sporttery_odds and not value_eligible:
            warnings.append("独立数据或置信度不足，已暂停输出价值信号")
        if match.intel_tier == "A" and (not intel or intel.completeness < 0.6):
            warnings.append("A 级场情报尚不完整，置信度已下调")
        return MatchPrediction(
            match=match,
            model_probs=dc.probabilities,
            market_probs=external_probs,
            final_probs=final,
            expected_home_goals=expected_home_goals,
            expected_away_goals=expected_away_goals,
            score_matrix=final_matrix,
            top_scores=top_scores,
            recommended=recommended,
            confidence=confidence,
            value=value,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            intel=intel,
            home_features=home_features,
            away_features=away_features,
            reference_market_odds=market_odds,
            official_market_probs=official_probs,
            analysis_mode=analysis_mode,
            calibrated_markets=official_calibration.used_markets if official_calibration else (),
        )

    @staticmethod
    def _analysis_mode(feature_ready: bool, external_ready: bool, official_ready: bool) -> str:
        if feature_ready and (external_ready or official_ready):
            return "hybrid"
        if feature_ready:
            return "statistical"
        if external_ready or official_ready:
            return "market_baseline"
        return "prior_only"

    @staticmethod
    def _confidence(
        final: Probability3,
        model: Probability3,
        market: Probability3 | None,
        intel: MatchIntel | None,
        independent_ready: bool,
    ) -> str:
        if not independent_ready:
            return "low"
        agreement = (
            0.5
            if market is None
            else 1 - sum(abs(a - b) for a, b in zip(model.vector(), market.vector(), strict=True)) / 2
        )
        completeness = intel.completeness if intel else 0.45
        score = 0.45 * max(final.vector()) + 0.3 * agreement + 0.15 * completeness + 0.1
        return "high" if score >= 0.72 else "mid" if score >= 0.56 else "low"

    @staticmethod
    def _reasons(
        match: Match,
        home: TeamFeatures,
        away: TeamFeatures,
        model: Probability3,
        external_market: Probability3 | None,
        intel: MatchIntel | None,
        official_calibration: MarketCalibration | None,
        analysis_mode: str,
    ) -> list[str]:
        reasons = [f"Dixon-Coles 独立统计层：主/平/客 {model.home:.1%} / {model.draw:.1%} / {model.away:.1%}"]
        if analysis_mode == "prior_only":
            reasons[0] = "独立统计数据缺失，当前 Dixon-Coles 仅为联赛中性占位先验"
        if home.elo is not None and away.elo is not None:
            reasons.append(f"Elo 实力差：{match.home} {home.elo:.0f}，{match.away} {away.elo:.0f}")
        if home.xg_for is not None and away.xg_for is not None:
            reasons.append(f"近期 xG：{match.home} {home.xg_for:.2f}，{match.away} {away.xg_for:.2f}")
        if official_calibration:
            markets = "/".join(official_calibration.used_markets).upper()
            probability = official_calibration.prediction.probabilities
            reasons.append(
                f"官方多玩法联合校准（{markets}）：主/平/客 "
                f"{probability.home:.1%} / {probability.draw:.1%} / {probability.away:.1%}"
            )
        if external_market:
            reasons.append(
                f"外部市场去水概率：主/平/客 "
                f"{external_market.home:.1%} / {external_market.draw:.1%} / {external_market.away:.1%}"
            )
        if intel and intel.evidences:
            reasons.append(f"已纳入 {len(intel.evidences)} 条有来源情报，完整度 {intel.completeness:.0%}")
        return reasons
