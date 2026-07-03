"""用多个官方竞彩玩法联合校准比赛级 Dixon-Coles 比分矩阵。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from ..domain import BettingMarketOdds, MarketOutcomeOdds, Match
from .dixon_coles import DixonColesPrediction, build_prediction, poisson_pmf

MARKET_WEIGHTS = {"had": 1.0, "hhad": 1.1, "ttg": 1.0, "crs": 0.65, "hafu": 0.4}
REQUIRED_KEYS = {
    "had": {"home", "draw", "away"},
    "hhad": {"home", "draw", "away"},
    "ttg": {"0", "1", "2", "3", "4", "5", "6", "7+"},
    "hafu": {"HH", "HD", "HA", "DH", "DD", "DA", "AH", "AD", "AA"},
}


@dataclass(frozen=True)
class MarketCalibration:
    prediction: DixonColesPrediction
    used_markets: tuple[str, ...]
    outcome_count: int
    divergence: float


def _no_vig(market: BettingMarketOdds) -> dict[str, float]:
    values = {outcome.key: 1 / outcome.odds for outcome in market.outcomes}
    total = sum(values.values()) or 1.0
    return {key: value / total for key, value in values.items()}


def _is_complete(market: BettingMarketOdds) -> bool:
    keys = {outcome.key for outcome in market.outcomes}
    required = REQUIRED_KEYS.get(market.code)
    if required is not None:
        return required.issubset(keys)
    if market.code == "crs":
        # 官方比分玩法包含 28 个精确比分和胜/平/负其它，共 31 项。
        return len(keys) >= 31 and {"win-other", "draw-other", "loss-other"}.issubset(keys)
    return False


def _three_way(matrix: tuple[tuple[float, ...], ...]) -> dict[str, float]:
    return {
        "home": sum(value for i, row in enumerate(matrix) for j, value in enumerate(row) if i > j),
        "draw": sum(row[i] for i, row in enumerate(matrix) if i < len(row)),
        "away": sum(value for i, row in enumerate(matrix) for j, value in enumerate(row) if i < j),
    }


def _handicap(matrix: tuple[tuple[float, ...], ...], line: float) -> dict[str, float]:
    result = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            adjusted = home_goals + line
            key = "home" if adjusted > away_goals else "draw" if adjusted == away_goals else "away"
            result[key] += probability
    return result


def _total_goals(matrix: tuple[tuple[float, ...], ...]) -> dict[str, float]:
    result = {str(goals): 0.0 for goals in range(7)} | {"7+": 0.0}
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            total = home_goals + away_goals
            result[str(total) if total < 7 else "7+"] += probability
    return result


def _correct_score(matrix: tuple[tuple[float, ...], ...], keys: set[str]) -> dict[str, float]:
    exact = {key for key in keys if ":" in key}
    result = {key: 0.0 for key in keys}
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            label = f"{home_goals}:{away_goals}"
            if label in exact:
                result[label] += probability
            elif home_goals > away_goals and "win-other" in result:
                result["win-other"] += probability
            elif home_goals == away_goals and "draw-other" in result:
                result["draw-other"] += probability
            elif home_goals < away_goals and "loss-other" in result:
                result["loss-other"] += probability
    return result


def _half_full(home_xg: float, away_xg: float, cap: int = 6) -> dict[str, float]:
    """用上下半场独立泊松近似半全场分布，作为低权重校准约束。"""

    first_share = 0.45
    first = [
        [poisson_pmf(h, home_xg * first_share) * poisson_pmf(a, away_xg * first_share) for a in range(cap + 1)]
        for h in range(cap + 1)
    ]
    second = [
        [
            poisson_pmf(h, home_xg * (1 - first_share)) * poisson_pmf(a, away_xg * (1 - first_share))
            for a in range(cap + 1)
        ]
        for h in range(cap + 1)
    ]

    def outcome(home_goals: int, away_goals: int) -> str:
        return "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"

    result = {f"{half}{full}": 0.0 for half in "HDA" for full in "HDA"}
    for h1 in range(cap + 1):
        for a1 in range(cap + 1):
            for h2 in range(cap + 1):
                for a2 in range(cap + 1):
                    result[outcome(h1, a1) + outcome(h1 + h2, a1 + a2)] += first[h1][a1] * second[h2][a2]
    total = sum(result.values()) or 1.0
    return {key: value / total for key, value in result.items()}


def _market_distribution(
    market: BettingMarketOdds,
    prediction: DixonColesPrediction,
) -> dict[str, float]:
    if market.code == "had":
        return _three_way(prediction.matrix)
    if market.code == "hhad" and market.line is not None:
        return _handicap(prediction.matrix, market.line)
    if market.code == "ttg":
        return _total_goals(prediction.matrix)
    if market.code == "crs":
        return _correct_score(prediction.matrix, {outcome.key for outcome in market.outcomes})
    if market.code == "hafu":
        return _half_full(prediction.home_xg, prediction.away_xg)
    return {}


def calibrate_from_official_markets(
    match: Match,
    prior: DixonColesPrediction,
    *,
    max_goals: int = 10,
) -> MarketCalibration | None:
    """拟合主客队期望进球，使比分矩阵同时解释当前可用的官方玩法。"""

    source_markets = list(match.sporttery_markets)
    if match.sporttery_odds and not any(market.code == "had" for market in source_markets):
        # 兼容旧版/用户输入只提供 sporttery_odds、尚未提供完整玩法数组的稳定数据契约。
        odds = match.sporttery_odds
        source_markets.append(
            BettingMarketOdds(
                code="had",
                label="胜平负",
                outcomes=(
                    MarketOutcomeOdds("h", "home", "主胜", odds.home),
                    MarketOutcomeOdds("d", "draw", "平", odds.draw),
                    MarketOutcomeOdds("a", "away", "客胜", odds.away),
                ),
                updated_at=odds.updated_at,
            )
        )
    markets = tuple(
        market
        for market in source_markets
        if market.code in MARKET_WEIGHTS and _is_complete(market) and (market.code != "hhad" or market.line is not None)
    )
    if not markets:
        return None
    targets = {market.code: _no_vig(market) for market in markets}
    prior_logs = np.log([prior.home_xg, prior.away_xg])
    regularization = 0.06 if len(markets) == 1 else 0.045

    def objective(params: np.ndarray) -> float:
        prediction = build_prediction(float(math.exp(params[0])), float(math.exp(params[1])), max_goals=max_goals)
        loss = regularization * float(np.sum((params - prior_logs) ** 2))
        for market in markets:
            target = targets[market.code]
            modeled = _market_distribution(market, prediction)
            keys = tuple(target)
            modeled_total = sum(modeled.get(key, 0.0) for key in keys) or 1.0
            # KL 散度让每个玩法独立去水后参与拟合，避免选项数量多的比分盘独占目标函数。
            divergence = sum(
                probability
                * math.log(max(1e-12, probability) / max(1e-12, modeled.get(key, 0.0) / modeled_total))
                for key, probability in target.items()
            )
            loss += MARKET_WEIGHTS[market.code] * divergence
        return loss

    bounds = [(math.log(0.2), math.log(4.8)), (math.log(0.2), math.log(4.8))]
    result = minimize(objective, prior_logs, method="L-BFGS-B", bounds=bounds, options={"maxiter": 160, "ftol": 1e-10})
    if not result.success or not np.isfinite(result.fun):
        return None
    prediction = build_prediction(float(math.exp(result.x[0])), float(math.exp(result.x[1])), max_goals=max_goals)
    return MarketCalibration(
        prediction=prediction,
        used_markets=tuple(market.code for market in markets),
        outcome_count=sum(len(market.outcomes) for market in markets),
        divergence=float(result.fun),
    )
