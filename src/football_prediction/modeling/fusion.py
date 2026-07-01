"""统计层、市场层和情报残差的概率融合。"""

from __future__ import annotations

import math

from ..config import Settings
from ..domain import Match, MatchIntel, MatchPrediction, Outcome, Probability3, TeamFeatures, ThreeWayOdds
from ..intelligence.validator import validate_intel
from .calibration import TemperatureCalibrator
from .dixon_coles import DixonColesModel, predict_from_features
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
        market_probs = remove_vig(market_odds) if market_odds else None
        official_probs = remove_vig(match.sporttery_odds) if match.sporttery_odds else None
        # 官方竞彩 SP 是最具流动性、校准最好的市场信号：只要拿到就融入最终概率，
        # 不再只当实力特征缺失时的兜底。特征就绪→按 market_weight 与统计层对数池化；
        # 特征缺失→权重升到 1.0，退化为纯 SP 去水基线，避免退回中性先验。
        official_only = market_probs is None and official_probs is not None
        official_fallback = official_only and not feature_ready
        if market_probs:
            fused = logarithmic_pool(dc.probabilities, market_probs, self.settings.market_weight)
        elif official_only and official_probs:
            weight = 1.0 if not feature_ready else self.settings.market_weight
            fused = logarithmic_pool(dc.probabilities, official_probs, weight)
        else:
            fused = dc.probabilities
        market_layer = market_probs or official_probs
        if intel:
            validate_intel(intel, kickoff_at=match.kickoff_at)
        final = apply_intelligence(fused, intel, self.settings.max_intel_logit)
        if self.calibrator:
            final = self.calibrator.transform(final)
        # 只有真实实力特征或同一时点外部市场至少存在一层时，才允许输出价值信号。
        # 否则中性先验与官方 SP 的差异会制造看似精确、实际不可执行的高 EV。
        value_eligible = bool(match.sporttery_odds and (feature_ready or market_probs))
        value = (
            assess_value(final, match.sporttery_odds, threshold=self.settings.value_threshold)
            if value_eligible and match.sporttery_odds
            else None
        )
        recommended = final.best()
        confidence = self._confidence(final, dc.probabilities, market_layer, intel)
        reasons = self._reasons(match, home_features, away_features, dc.probabilities, market_layer, intel)
        if official_fallback:
            confidence = "low"
            reasons.insert(1, "实力特征缺失，概率基线切换为当期竞彩 SP 去水结果")
        elif official_only:
            reasons.insert(1, f"已按 {self.settings.market_weight:.0%} 市场权重把官方竞彩 SP 去水概率融入最终结果")
        warnings: list[str] = []
        if official_fallback:
            warnings.append("缺少实力特征与外部市场，当前概率主要来自官方 SP 去水基线")
        elif not market_probs:
            warnings.append("缺少实时锐角/市场基准，最终概率由统计模型与官方 SP 去水融合")
        if match.sporttery_odds and not value_eligible:
            warnings.append("实力特征与外部市场均不足，已暂停输出价值信号")
        if match.intel_tier == "A" and (not intel or intel.completeness < 0.6):
            warnings.append("A 级场情报尚不完整，置信度已下调")
        return MatchPrediction(
            match=match,
            model_probs=dc.probabilities,
            market_probs=market_probs,
            final_probs=final,
            expected_home_goals=dc.home_xg,
            expected_away_goals=dc.away_xg,
            score_matrix=dc.matrix,
            top_scores=dc.top_scores,
            recommended=recommended,
            confidence=confidence,
            value=value,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            intel=intel,
            home_features=home_features,
            away_features=away_features,
            reference_market_odds=market_odds,
        )

    @staticmethod
    def _confidence(
        final: Probability3, model: Probability3, market: Probability3 | None, intel: MatchIntel | None
    ) -> str:
        agreement = (
            0.5
            if market is None
            else 1 - sum(abs(a - b) for a, b in zip(model.vector(), market.vector(), strict=True)) / 2
        )
        completeness = intel.completeness if intel else 0.45
        score = 0.5 * max(final.vector()) + 0.3 * agreement + 0.2 * completeness
        return "high" if score >= 0.72 else "mid" if score >= 0.58 else "low"

    @staticmethod
    def _reasons(
        match: Match,
        home: TeamFeatures,
        away: TeamFeatures,
        model: Probability3,
        market: Probability3 | None,
        intel: MatchIntel | None,
    ) -> list[str]:
        reasons = [f"Dixon-Coles 统计层：主/平/客 {model.home:.1%} / {model.draw:.1%} / {model.away:.1%}"]
        if home.elo is not None and away.elo is not None:
            reasons.append(f"Elo 实力差：{match.home} {home.elo:.0f}，{match.away} {away.elo:.0f}")
        if home.xg_for is not None and away.xg_for is not None:
            reasons.append(f"近期 xG：{match.home} {home.xg_for:.2f}，{match.away} {away.xg_for:.2f}")
        if market:
            reasons.append(f"市场去水概率：主/平/客 {market.home:.1%} / {market.draw:.1%} / {market.away:.1%}")
        if intel and intel.evidences:
            reasons.append(f"已纳入 {len(intel.evidences)} 条有来源情报，完整度 {intel.completeness:.0%}")
        return reasons
