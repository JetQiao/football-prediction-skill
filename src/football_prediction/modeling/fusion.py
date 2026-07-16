"""统计模型、参考市场、目标市场与情报残差的严格角色融合。"""

from __future__ import annotations

import math

from ..config import Settings
from ..domain import Match, MatchIntel, MatchPrediction, Outcome, Probability3, TeamFeatures, ThreeWayOdds
from ..intelligence.validator import validate_intel
from ..policy import assess_confidence, assess_decision
from ..providers.names import name_key
from .calibration import TemperatureCalibrator
from .dixon_coles import DixonColesModel, DixonColesPrediction, build_prediction, predict_from_features
from .ensemble import LogPoolEnsemble, logarithmic_pool
from .market_calibration import MarketCalibration, calibrate_from_official_markets
from .matrix import blend_matrices, matrix_expected_goals, matrix_top_scores, tilt_matrix
from .odds import remove_vig
from .registry import ModelMetadata


def apply_intelligence(probabilities: Probability3, intel: MatchIntel | None, max_logit: float) -> Probability3:
    if not intel or not intel.evidences:
        return probabilities
    effects = {outcome: 0.0 for outcome in Outcome}
    fingerprints: set[tuple[str, str, str]] = set()
    for evidence in intel.evidences:
        # 同一来源、标题和方向只计一次，避免转载或重复输入放大影响。
        fingerprint = (evidence.url, evidence.title.strip().lower(), evidence.outcome.value)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        effects[evidence.outcome] += evidence.impact * evidence.credibility
    effects = {outcome: max(-max_logit, min(max_logit, value)) for outcome, value in effects.items()}
    logits = [math.log(max(1e-12, probabilities.get(outcome))) + effects[outcome] for outcome in Outcome]
    peak = max(logits)
    return Probability3.normalized(math.exp(value - peak) for value in logits)


def apply_availability_facts(
    prediction: DixonColesPrediction,
    intel: MatchIntel | None,
    *,
    home: str,
    away: str,
    rho: float,
) -> tuple[DixonColesPrediction, tuple[str, ...]]:
    """把结构化阵容事实映射为有界 xG 调整，不让上游直接填写赛果方向。"""

    if not intel or not intel.facts:
        return prediction, ()
    attack_loss = {name_key(home): 0.0, name_key(away): 0.0}
    defence_loss = {name_key(home): 0.0, name_key(away): 0.0}
    seen: set[str] = set()
    used = 0
    for fact in intel.facts:
        if fact.event_fingerprint in seen:
            continue
        seen.add(fact.event_fingerprint)
        team_key = name_key(fact.team)
        if team_key not in attack_loss:
            continue
        status = fact.status.lower()
        status_weight = 1.0 if any(token in status for token in ("out", "missing", "confirmed", "injury")) else 0.65
        scale = abs(fact.expected_minutes_delta) / 90 * fact.credibility * status_weight
        position = fact.position.upper()
        if any(token in position for token in ("GK", "CB", "DF", "DEF", "BACK")):
            attack_component, defence_component = 0.002, 0.035
        elif any(token in position for token in ("DM", "CM", "MF", "MID")):
            attack_component, defence_component = 0.014, 0.014
        elif any(token in position for token in ("ST", "CF", "FW", "FWD", "WG", "AM")):
            attack_component, defence_component = 0.032, 0.002
        else:
            attack_component, defence_component = 0.008, 0.008
        attack_loss[team_key] += attack_component * scale
        defence_loss[team_key] += defence_component * scale
        used += 1

    home_key, away_key = name_key(home), name_key(away)
    home_attack_loss = min(0.12, attack_loss[home_key])
    away_attack_loss = min(0.12, attack_loss[away_key])
    home_defence_loss = min(0.12, defence_loss[home_key])
    away_defence_loss = min(0.12, defence_loss[away_key])
    if used == 0:
        return prediction, ()
    home_xg = prediction.home_xg * (1 - home_attack_loss) * (1 + away_defence_loss)
    away_xg = prediction.away_xg * (1 - away_attack_loss) * (1 + home_defence_loss)
    adjusted = build_prediction(
        max(0.2, min(4.5, home_xg)),
        max(0.2, min(4.5, away_xg)),
        rho=rho,
    )
    notes = (
        f"结构化阵容事实 {used} 条：主队进攻调整 {-home_attack_loss:.1%}、"
        f"客队进攻调整 {-away_attack_loss:.1%}",
    )
    return adjusted, notes


class PredictionEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        model: DixonColesModel | None = None,
        calibrator: TemperatureCalibrator | None = None,
        ensemble: LogPoolEnsemble | None = None,
        metadata: ModelMetadata | None = None,
    ) -> None:
        self.settings = settings.validate()
        self.model = model
        self.calibrator = calibrator
        self.ensemble = ensemble
        self.metadata = metadata

    def predict(
        self,
        match: Match,
        home_features: TeamFeatures,
        away_features: TeamFeatures,
        *,
        market_odds: ThreeWayOdds | None = None,
        target_market_odds: ThreeWayOdds | None = None,
        intel: MatchIntel | None = None,
        as_of: str = "",
        use_official_market_signal: bool = False,
        devig_method: str | None = None,
    ) -> MatchPrediction:
        method = devig_method or (self.metadata.devig_method if self.metadata else "multiplicative")
        if intel:
            validate_intel(intel, kickoff_at=match.kickoff_at, as_of=as_of or None)
        model_ready = bool(
            self.model
            and match.home in self.model.teams
            and match.away in self.model.teams
        )
        dc = (
            self.model.predict(match.home, match.away)
            if model_ready and self.model
            else predict_from_features(home_features, away_features)
        )
        dc, availability_notes = apply_availability_facts(
            dc,
            intel,
            home=match.home,
            away=match.away,
            rho=self.model.rho if model_ready and self.model else -0.08,
        )
        feature_ready = all(
            feature.source != "fallback"
            and any(value is not None for value in (feature.elo, feature.xg_for, feature.xg_against))
            for feature in (home_features, away_features)
        )
        statistical_ready = model_ready or feature_ready
        external_probs = remove_vig(market_odds, method=method) if market_odds else None
        target_odds = target_market_odds if target_market_odds is not None else match.sporttery_odds
        official_calibration = calibrate_from_official_markets(match, dc)
        official_probs = official_calibration.prediction.probabilities if official_calibration else None
        independent_ready = statistical_ready or external_probs is not None

        fused = dc.probabilities
        matrix = dc.matrix
        target_used_as_signal = False

        if statistical_ready and external_probs:
            fused = (
                self.ensemble.transform(fused, external_probs)
                if self.ensemble
                else logarithmic_pool(fused, external_probs, self.settings.market_weight)
            )
        elif external_probs and not statistical_ready:
            fused = external_probs

        if official_calibration and use_official_market_signal:
            target_used_as_signal = True
            if independent_ready:
                fused = logarithmic_pool(fused, official_probs, self.settings.official_market_weight)
                matrix = blend_matrices(
                    matrix,
                    official_calibration.prediction.matrix,
                    self.settings.official_market_weight,
                )
            else:
                fused = official_probs
                matrix = official_calibration.prediction.matrix
        elif official_calibration and not independent_ready:
            # 无独立数据时只能展示目标市场共识，并强制弃权。
            fused = official_probs
            matrix = official_calibration.prediction.matrix
            target_used_as_signal = True

        analysis_mode = self._analysis_mode(
            statistical_ready,
            external_probs is not None,
            official_calibration is not None,
            target_used_as_signal,
        )
        final = apply_intelligence(fused, intel, self.settings.max_intel_logit)
        if self.calibrator and independent_ready:
            final = self.calibrator.transform(final)

        final_matrix = tilt_matrix(matrix, final)
        expected_home_goals, expected_away_goals = matrix_expected_goals(final_matrix)
        top_scores = matrix_top_scores(final_matrix)
        calibration_status = self.metadata.calibration_status if self.metadata else "unavailable"
        calibration_sample_size = self.metadata.calibration_sample_size if self.metadata else 0
        confidence_assessment = assess_confidence(
            final,
            statistical_ready=statistical_ready,
            reference_market=external_probs,
            calibration_status=calibration_status,
            calibration_sample_size=calibration_sample_size,
            intel_completeness=intel.completeness if intel else 0.0,
            is_a_tier=match.intel_tier == "A",
        )
        decision = assess_decision(
            final,
            target_odds,
            independent_ready=independent_ready,
            target_used_as_signal=target_used_as_signal,
            confidence=confidence_assessment,
            calibration_status=calibration_status,
            value_threshold=self.settings.value_threshold,
            devig_method=method,
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
            model_ready,
            availability_notes,
        )
        if self.ensemble and external_probs:
            reasons.append(f"参考市场融合权重由样本外训练得到：{self.ensemble.market_weight:.1%}")
        elif statistical_ready and external_probs:
            reasons.append(f"参考市场使用默认融合权重：{self.settings.market_weight:.0%}")
        if official_calibration and use_official_market_signal and independent_ready:
            reasons.append(
                f"目标竞彩多玩法以 {self.settings.official_market_weight:.0%} 市场权重参与概率形成"
            )

        warnings = self._warnings(
            match=match,
            analysis_mode=analysis_mode,
            target_odds=target_odds,
            independent_ready=independent_ready,
            target_used_as_signal=target_used_as_signal,
            official_calibration=official_calibration,
            external_ready=external_probs is not None,
            intel=intel,
            calibration_status=calibration_status,
        )
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
            confidence=confidence_assessment.level,
            value=decision.value,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            intel=intel,
            home_features=home_features,
            away_features=away_features,
            reference_market_odds=market_odds,
            official_market_probs=official_probs,
            analysis_mode=analysis_mode,
            calibrated_markets=official_calibration.used_markets if official_calibration else (),
            decision_state=decision.state,
            decision_reason=decision.reason,
            uncertainty=confidence_assessment.uncertainty,
            data_quality=confidence_assessment.data_quality,
            as_of=as_of,
            model_version=self.metadata.version if self.metadata else "unregistered",
            model_trained_until=self.metadata.trained_until if self.metadata else None,
            calibration_status=calibration_status,
            calibration_sample_size=calibration_sample_size,
            devig_method=method,
            target_used_as_signal=target_used_as_signal,
        )

    @staticmethod
    def _analysis_mode(
        statistical_ready: bool,
        external_ready: bool,
        official_ready: bool,
        target_used_as_signal: bool,
    ) -> str:
        if statistical_ready and external_ready:
            return "hybrid"
        if statistical_ready:
            return "statistical"
        if external_ready:
            return "reference_market"
        if official_ready and target_used_as_signal:
            return "market_baseline"
        return "prior_only"

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
        model_ready: bool,
        availability_notes: tuple[str, ...],
    ) -> list[str]:
        if model_ready:
            reasons = [f"动态 Dixon-Coles：主/平/客 {model.home:.1%} / {model.draw:.1%} / {model.away:.1%}"]
        elif analysis_mode == "prior_only":
            reasons = ["独立统计数据缺失，当前只保留联赛中性占位先验"]
        else:
            reasons = [f"Elo/xG 统计层：主/平/客 {model.home:.1%} / {model.draw:.1%} / {model.away:.1%}"]
        if home.elo is not None and away.elo is not None:
            reasons.append(f"Elo 实力差：{match.home} {home.elo:.0f}，{match.away} {away.elo:.0f}")
        if home.xg_for is not None and away.xg_for is not None:
            reasons.append(f"近期 xG：{match.home} {home.xg_for:.2f}，{match.away} {away.xg_for:.2f}")
        if official_calibration:
            markets = "/".join(official_calibration.used_markets).upper()
            probability = official_calibration.prediction.probabilities
            reasons.append(
                f"目标竞彩多玩法共识（{markets}）：主/平/客 "
                f"{probability.home:.1%} / {probability.draw:.1%} / {probability.away:.1%}"
            )
        if external_market:
            reasons.append(
                f"独立参考市场去水概率：主/平/客 "
                f"{external_market.home:.1%} / {external_market.draw:.1%} / {external_market.away:.1%}"
            )
        if intel and intel.evidences:
            reasons.append(f"已纳入 {len(intel.evidences)} 条去重后的有来源情报，完整度 {intel.completeness:.0%}")
        reasons.extend(availability_notes)
        return reasons

    @staticmethod
    def _warnings(
        *,
        match: Match,
        analysis_mode: str,
        target_odds: ThreeWayOdds | None,
        independent_ready: bool,
        target_used_as_signal: bool,
        official_calibration: MarketCalibration | None,
        external_ready: bool,
        intel: MatchIntel | None,
        calibration_status: str,
    ) -> list[str]:
        warnings: list[str] = []
        if analysis_mode == "market_baseline":
            warnings.append("缺少独立实力或参考市场，当前仅展示目标竞彩市场共识")
        elif analysis_mode == "prior_only":
            warnings.append("当前没有可用模型、参考市场或完整官方玩法，已强制弃权")
        elif not external_ready:
            warnings.append("缺少同一预测截点的独立参考市场，无法评估收盘价值")
        if target_used_as_signal:
            warnings.append("目标竞彩价格参与了概率形成，已禁止输出循环价值信号")
        if target_odds is None and match.sporttery_markets:
            warnings.append("普通胜平负尚未开售，当前只展示开放玩法推演")
        if match.sporttery_markets and not official_calibration:
            warnings.append("已获取的官方玩法选项不完整，未进入多玩法共识计算")
        if not independent_ready:
            warnings.append("独立数据不足，已暂停输出价值信号并将决策状态设为弃权")
        if calibration_status != "validated" and independent_ready:
            warnings.append("模型尚未通过样本外校准晋级门槛，候选价值功能保持关闭")
        if match.intel_tier == "A" and (not intel or intel.completeness < 0.6):
            warnings.append("A 级场情报尚不完整，置信度已下调")
        return warnings


__all__ = [
    "PredictionEngine",
    "apply_availability_facts",
    "apply_intelligence",
    "logarithmic_pool",
]
