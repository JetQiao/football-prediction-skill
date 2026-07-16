"""生产与历史回放共享的单场预测管线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Settings
from .domain import MarketRole, Match, MatchIntel, MatchPrediction, TeamFeatures, ThreeWayOdds
from .modeling.fusion import PredictionEngine
from .modeling.registry import ModelBundle, ModelRegistry
from .snapshots import parse_timestamp


@dataclass(frozen=True)
class PredictionContext:
    match: Match
    home_features: TeamFeatures
    away_features: TeamFeatures
    reference_market_odds: ThreeWayOdds | None = None
    target_market_odds: ThreeWayOdds | None = None
    intel: MatchIntel | None = None
    as_of: str = ""
    use_target_market_as_signal: bool = False


class PredictionPipeline:
    """唯一的概率生产入口；日常预测和历史回放都调用该类。"""

    def __init__(self, settings: Settings, registry: ModelRegistry | None = None) -> None:
        self.settings = settings.validate()
        self.registry = registry or ModelRegistry(self.settings.paths.models)

    @staticmethod
    def _validate_observed_at(
        value: str,
        *,
        label: str,
        business_date: str,
        as_of: str,
        kickoff_at: str,
    ) -> None:
        if not value:
            return
        observed = parse_timestamp(value, business_date=business_date)
        cutoff = parse_timestamp(as_of, business_date=business_date)
        kickoff = parse_timestamp(kickoff_at, business_date=business_date)
        if observed > cutoff:
            raise ValueError(f"{label}更新时间晚于预测截点：{value} > {as_of}")
        if observed >= kickoff:
            raise ValueError(f"{label}更新时间不早于开赛时间：{value} >= {kickoff_at}")

    def _bundle(self, match: Match, as_of: str) -> ModelBundle | None:
        return self.registry.resolve(match.league, as_of=as_of)

    @staticmethod
    def _validate_market_role(odds: ThreeWayOdds, *, label: str, allowed: set[MarketRole]) -> None:
        role = MarketRole(odds.role)
        if role not in allowed:
            expected = " / ".join(sorted(item.value for item in allowed))
            raise ValueError(f"{label}角色错误：{role.value}，应为 {expected}")

    def predict(
        self,
        context: PredictionContext,
        *,
        bundle: ModelBundle | None = None,
    ) -> MatchPrediction:
        match = context.match
        as_of = context.as_of or datetime.now().astimezone().isoformat(timespec="seconds")
        cutoff = parse_timestamp(as_of, business_date=match.business_date)
        kickoff = parse_timestamp(match.kickoff_at, business_date=match.business_date)
        if cutoff >= kickoff:
            raise ValueError(f"预测截点必须早于开赛时间：{as_of} >= {match.kickoff_at}")
        if context.reference_market_odds:
            self._validate_market_role(
                context.reference_market_odds,
                label="参考市场",
                allowed={MarketRole.REFERENCE, MarketRole.BENCHMARK},
            )
            self._validate_observed_at(
                context.reference_market_odds.updated_at,
                label="参考市场",
                business_date=match.business_date,
                as_of=as_of,
                kickoff_at=match.kickoff_at,
            )
        if context.target_market_odds:
            self._validate_market_role(
                context.target_market_odds,
                label="目标市场",
                allowed={MarketRole.TARGET, MarketRole.BENCHMARK},
            )
            if context.target_market_odds.updated_at:
                self._validate_observed_at(
                    context.target_market_odds.updated_at,
                    label="目标市场",
                    business_date=match.business_date,
                    as_of=as_of,
                    kickoff_at=match.kickoff_at,
                )
        if (
            context.reference_market_odds is not None
            and context.reference_market_odds is context.target_market_odds
        ):
            raise ValueError("同一赔率对象不能同时作为参考市场和目标市场")
        for market in match.sporttery_markets:
            if market.updated_at:
                self._validate_observed_at(
                    market.updated_at,
                    label=f"目标竞彩 {market.code.upper()}",
                    business_date=match.business_date,
                    as_of=as_of,
                    kickoff_at=match.kickoff_at,
                )
        for label, feature in (("主队特征", context.home_features), ("客队特征", context.away_features)):
            if feature.observed_at:
                self._validate_observed_at(
                    feature.observed_at,
                    label=label,
                    business_date=match.business_date,
                    as_of=as_of,
                    kickoff_at=match.kickoff_at,
                )

        bundle = bundle or self._bundle(match, as_of)
        if bundle and bundle.metadata.trained_until >= match.business_date:
            raise ValueError(
                f"模型训练截止日不早于比赛日：{bundle.metadata.trained_until} >= {match.business_date}"
            )
        engine = PredictionEngine(
            self.settings,
            model=bundle.model if bundle else None,
            calibrator=bundle.calibrator if bundle else None,
            ensemble=bundle.ensemble if bundle else None,
            metadata=bundle.metadata if bundle else None,
        )
        return engine.predict(
            match,
            context.home_features,
            context.away_features,
            market_odds=context.reference_market_odds,
            target_market_odds=context.target_market_odds,
            intel=context.intel,
            as_of=as_of,
            # 默认严格隔离目标竞彩价格；只有显式历史兼容模式才允许作为信号。
            use_official_market_signal=context.use_target_market_as_signal,
            devig_method=bundle.metadata.devig_method if bundle else "multiplicative",
        )
