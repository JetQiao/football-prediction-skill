"""跨数据源的统一领域模型。"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable


class Outcome(str, Enum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"


class MarketRole(str, Enum):
    """赔率在预测流程中的角色，避免同一价格既参与预测又被用于证明价值。"""

    REFERENCE = "reference_market"
    TARGET = "target_market"
    BENCHMARK = "benchmark_market"
    UNKNOWN = "unknown"


class DecisionState(str, Enum):
    """报告中统一使用的决策状态。"""

    CANDIDATE = "candidate"
    LEAN = "lean"
    NO_EDGE = "no_edge"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Probability3:
    home: float
    draw: float
    away: float

    def __post_init__(self) -> None:
        values = self.vector()
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("概率必须位于 0~1")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError(f"三项概率之和必须为 1，当前为 {sum(values):.8f}")

    @classmethod
    def normalized(cls, values: Iterable[float]) -> "Probability3":
        vector = [max(0.0, float(value)) for value in values]
        if len(vector) != 3 or sum(vector) <= 0:
            raise ValueError("必须提供三个可归一化概率")
        total = sum(vector)
        return cls(*(value / total for value in vector))

    def vector(self) -> tuple[float, float, float]:
        return self.home, self.draw, self.away

    def get(self, outcome: Outcome | str) -> float:
        key = outcome.value if isinstance(outcome, Outcome) else outcome
        return {"home": self.home, "draw": self.draw, "away": self.away}[key]

    def best(self) -> Outcome:
        return (Outcome.HOME, Outcome.DRAW, Outcome.AWAY)[self.vector().index(max(self.vector()))]


@dataclass(frozen=True)
class ThreeWayOdds:
    home: float
    draw: float
    away: float
    source: str
    updated_at: str
    role: MarketRole | str = MarketRole.UNKNOWN

    def __post_init__(self) -> None:
        if any(value <= 1 for value in self.vector()):
            raise ValueError("十进制赔率必须大于 1")
        try:
            MarketRole(self.role)
        except ValueError as exc:
            raise ValueError(f"未知市场角色：{self.role}") from exc

    def vector(self) -> tuple[float, float, float]:
        return self.home, self.draw, self.away

    def get(self, outcome: Outcome | str) -> float:
        key = outcome.value if isinstance(outcome, Outcome) else outcome
        return {"home": self.home, "draw": self.draw, "away": self.away}[key]


@dataclass(frozen=True)
class MarketOutcomeOdds:
    """竞彩单个玩法选项的官方 SP。"""

    code: str
    key: str
    label: str
    odds: float
    trend: str = "unknown"

    def __post_init__(self) -> None:
        if self.odds <= 1:
            raise ValueError("竞彩 SP 必须大于 1")


@dataclass(frozen=True)
class BettingMarketOdds:
    """标准化后的竞彩玩法，兼容官方接口与 SportteryAPI。"""

    code: str
    label: str
    outcomes: tuple[MarketOutcomeOdds, ...]
    updated_at: str = ""
    line: float | None = None
    role: MarketRole | str = MarketRole.TARGET

    def __post_init__(self) -> None:
        try:
            MarketRole(self.role)
        except ValueError as exc:
            raise ValueError(f"未知市场角色：{self.role}") from exc

    def get(self, key: str) -> MarketOutcomeOdds | None:
        return next((outcome for outcome in self.outcomes if outcome.key == key), None)


@dataclass(frozen=True)
class Match:
    id: str
    business_date: str
    match_no: str
    league: str
    home: str
    away: str
    kickoff_at: str
    sale_close_at: str | None = None
    sporttery_odds: ThreeWayOdds | None = None
    sporttery_markets: tuple[BettingMarketOdds, ...] = ()
    handicap: float | None = None
    intel_tier: str = "B"
    stage: str = "league"
    source_url: str | None = None
    match_status: str = ""
    sale_status: int | None = None
    competition_id: str | None = None
    home_team_id: str | None = None
    away_team_id: str | None = None
    season_id: str | None = None
    provider_fixture_id: int | None = None

    def market(self, code: str) -> BettingMarketOdds | None:
        return next((market for market in self.sporttery_markets if market.code == code), None)


@dataclass(frozen=True)
class TeamFeatures:
    team: str
    elo: float | None = None
    xg_for: float | None = None
    xg_against: float | None = None
    form_index: float = 0.0
    sample_size: int = 0
    source: str = "fallback"
    observed_at: str = ""
    competition_id: str | None = None
    team_id: str | None = None


@dataclass(frozen=True)
class IntelEvidence:
    title: str
    url: str
    published_at: str
    credibility: float
    impact: float
    outcome: Outcome
    note: str = ""

    def __post_init__(self) -> None:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("情报必须包含可核验的 http(s) 来源")
        if not 0 <= self.credibility <= 1:
            raise ValueError("可信度必须位于 0~1")
        if not -0.08 <= self.impact <= 0.08:
            raise ValueError("单条情报影响必须位于 -0.08~0.08")


@dataclass(frozen=True)
class AvailabilityFact:
    """由官方/结构化来源抽取的阵容可用性事实，不直接携带胜平负方向。"""

    event_type: str
    team: str
    player: str
    status: str
    observed_at: str
    source_url: str
    credibility: float = 0.8
    position: str = ""
    expected_minutes_delta: float = -45.0
    reason: str = ""
    event_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.event_type or not self.team or not self.player or not self.status:
            raise ValueError("阵容事实必须包含事件类型、球队、球员和状态")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("阵容事实必须包含可核验的 http(s) 来源")
        if not 0 <= self.credibility <= 1:
            raise ValueError("阵容事实可信度必须位于 0~1")
        if not -90 <= self.expected_minutes_delta <= 0:
            raise ValueError("expected_minutes_delta 必须位于 -90~0")
        if not self.event_fingerprint:
            raw = "|".join(
                (
                    self.event_type,
                    self.team,
                    self.player,
                    self.status,
                    self.observed_at,
                    self.source_url,
                )
            )
            object.__setattr__(
                self,
                "event_fingerprint",
                hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            )


@dataclass(frozen=True)
class MatchIntel:
    match_id: str
    evidences: tuple[IntelEvidence, ...] = ()
    completeness: float = 0.0
    missing: tuple[str, ...] = ()
    facts: tuple[AvailabilityFact, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.completeness <= 1:
            raise ValueError("情报完整度必须位于 0~1")


@dataclass(frozen=True)
class ScoreProbability:
    home_goals: int
    away_goals: int
    probability: float

    @property
    def label(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"


@dataclass(frozen=True)
class ValueAssessment:
    pick: Outcome
    probability: float
    odds: float
    expected_value: float
    edge: float
    flag: str


@dataclass(frozen=True)
class MatchPrediction:
    match: Match
    model_probs: Probability3
    market_probs: Probability3 | None
    final_probs: Probability3
    expected_home_goals: float
    expected_away_goals: float
    score_matrix: tuple[tuple[float, ...], ...]
    top_scores: tuple[ScoreProbability, ...]
    recommended: Outcome
    confidence: str
    value: ValueAssessment | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    intel: MatchIntel | None = None
    home_features: TeamFeatures | None = None
    away_features: TeamFeatures | None = None
    reference_market_odds: ThreeWayOdds | None = None
    official_market_probs: Probability3 | None = None
    analysis_mode: str = "prior_only"
    calibrated_markets: tuple[str, ...] = ()
    decision_state: DecisionState | str = DecisionState.ABSTAIN
    decision_reason: str = ""
    uncertainty: float = 1.0
    data_quality: str = "insufficient"
    as_of: str = ""
    model_version: str = "unregistered"
    model_trained_until: str | None = None
    calibration_status: str = "unavailable"
    calibration_sample_size: int = 0
    devig_method: str = "multiplicative"
    target_used_as_signal: bool = False


@dataclass(frozen=True)
class BacktestSummary:
    matches: int
    accuracy: float
    brier: float
    log_loss: float
    roi: float
    max_drawdown: float
    bets: int
    baseline_brier: float | None = None
    baseline_log_loss: float | None = None
    reliability: tuple[dict[str, float | int], ...] = ()
    equity_curve: tuple[float, ...] = ()
    rps: float = 0.0
    ece: float = 0.0
    calibration_slope: float | None = None
    calibration_intercept: float | None = None
    baseline_rps: float | None = None
    drawdown_curve: tuple[float, ...] = ()
    coverage: float = 0.0
    decision_counts: tuple[dict[str, str | int], ...] = ()


@dataclass(frozen=True)
class DailyReport:
    business_date: str
    generated_at: str
    predictions: tuple[MatchPrediction, ...]
    sources: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    backtest: BacktestSummary | None = None
    run_id: str = ""
    as_of: str = ""
    model_version: str = "unregistered"
    model_trained_until: str | None = None
    calibration_status: str = "unavailable"
    schema_version: str = "2.0"


def to_dict(value: Any) -> Any:
    """转换 dataclass/Enum，确保产物是稳定的 JSON 基础类型。"""

    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_dict(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_dict(item) for item in value]
    return value
