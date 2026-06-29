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
        market_probs = remove_vig(market_odds) if market_odds else None
        fused = (
            logarithmic_pool(dc.probabilities, market_probs, self.settings.market_weight)
            if market_probs
            else dc.probabilities
        )
        if intel:
            validate_intel(intel, kickoff_at=match.kickoff_at)
        final = apply_intelligence(fused, intel, self.settings.max_intel_logit)
        if self.calibrator:
            final = self.calibrator.transform(final)
        value = (
            assess_value(final, match.sporttery_odds, threshold=self.settings.value_threshold)
            if match.sporttery_odds
            else None
        )
        recommended = final.best()
        confidence = self._confidence(final, dc.probabilities, market_probs, intel)
        reasons = self._reasons(match, home_features, away_features, dc.probabilities, market_probs, intel)
        warnings: list[str] = []
        if not market_probs:
            warnings.append("缺少实时锐角/市场基准，当前结果主要来自统计模型")
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
        )

    @staticmethod
    def _confidence(
        final: Probability3, model: Probability3, market: Probability3 | None, intel: MatchIntel | None
    ) -> str:
        agreement = (
            1.0
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
