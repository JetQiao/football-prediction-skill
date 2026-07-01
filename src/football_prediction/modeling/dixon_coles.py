"""Dixon-Coles 低比分修正与时间衰减拟合。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from ..domain import Probability3, ScoreProbability, TeamFeatures
from ..providers.football_data import HistoricalMatch


def poisson_pmf(goals: int, expected: float) -> float:
    return math.exp(-expected) * expected**goals / math.factorial(goals)


def dc_tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


@dataclass(frozen=True)
class DixonColesPrediction:
    home_xg: float
    away_xg: float
    matrix: tuple[tuple[float, ...], ...]
    probabilities: Probability3
    top_scores: tuple[ScoreProbability, ...]


@dataclass
class DixonColesModel:
    teams: tuple[str, ...] = ()
    attack: dict[str, float] | None = None
    defence: dict[str, float] | None = None
    intercept: float = math.log(1.28)
    home_advantage: float = math.log(1.12)
    rho: float = -0.08
    fitted_at: str | None = None

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        attack = self.attack or {}
        defence = self.defence or {}
        home_xg = math.exp(self.intercept + self.home_advantage + attack.get(home, 0) + defence.get(away, 0))
        away_xg = math.exp(self.intercept + attack.get(away, 0) + defence.get(home, 0))
        return _bounded_xg(home_xg), _bounded_xg(away_xg)

    def predict(self, home: str, away: str, max_goals: int = 8) -> DixonColesPrediction:
        home_xg, away_xg = self.expected_goals(home, away)
        return build_prediction(home_xg, away_xg, self.rho, max_goals)


class DixonColesEstimator:
    """用滚动历史数据拟合攻防强度，约束参数避免小样本发散。"""

    def __init__(self, decay: float = 0.0025, regularization: float = 0.015) -> None:
        self.decay = decay
        self.regularization = regularization

    def fit(self, matches: Sequence[HistoricalMatch]) -> DixonColesModel:
        if len(matches) < 20:
            raise ValueError("Dixon-Coles 拟合至少需要 20 场历史比赛")
        teams = tuple(sorted({row.home for row in matches} | {row.away for row in matches}))
        index = {team: i for i, team in enumerate(teams)}
        size = len(teams)
        newest = max(_parse_date(row.date) for row in matches)
        initial = np.zeros(size * 2 + 3)
        initial[-3] = math.log(1.28)
        initial[-2] = math.log(1.12)
        initial[-1] = np.arctanh(-0.08 / 0.2)

        def objective(params: np.ndarray) -> float:
            attack = params[:size]
            defence = params[size : size * 2]
            intercept, home_adv = params[-3], params[-2]
            rho = math.tanh(params[-1]) * 0.2
            loss = 0.0
            for row in matches:
                home_xg = math.exp(intercept + home_adv + attack[index[row.home]] + defence[index[row.away]])
                away_xg = math.exp(intercept + attack[index[row.away]] + defence[index[row.home]])
                tau = max(1e-9, dc_tau(row.home_goals, row.away_goals, home_xg, away_xg, rho))
                age = max(0, (newest - _parse_date(row.date)).days)
                weight = math.exp(-self.decay * age)
                log_likelihood = (
                    math.log(tau)
                    + row.home_goals * math.log(home_xg)
                    - home_xg
                    - math.lgamma(row.home_goals + 1)
                    + row.away_goals * math.log(away_xg)
                    - away_xg
                    - math.lgamma(row.away_goals + 1)
                )
                loss -= weight * log_likelihood
            # 攻击参数中心化，L2 抑制冷门球队的小样本极值。
            loss += 100 * float(np.mean(attack) ** 2)
            loss += self.regularization * float(np.sum(attack**2) + np.sum(defence**2))
            return loss

        result = minimize(objective, initial, method="L-BFGS-B", options={"maxiter": 600, "ftol": 1e-8})
        if not result.success:
            raise RuntimeError(f"Dixon-Coles 拟合失败：{result.message}")
        params = result.x
        attack_values = params[:size] - np.mean(params[:size])
        return DixonColesModel(
            teams=teams,
            attack={team: float(attack_values[index[team]]) for team in teams},
            defence={team: float(params[size + index[team]]) for team in teams},
            intercept=float(params[-3]),
            home_advantage=float(params[-2]),
            rho=float(math.tanh(params[-1]) * 0.2),
            fitted_at=newest.isoformat(),
        )


def build_prediction(home_xg: float, away_xg: float, rho: float = -0.08, max_goals: int = 8) -> DixonColesPrediction:
    raw: list[list[float]] = []
    for home_goals in range(max_goals + 1):
        row: list[float] = []
        for away_goals in range(max_goals + 1):
            probability = poisson_pmf(home_goals, home_xg) * poisson_pmf(away_goals, away_xg)
            probability *= max(0.0, dc_tau(home_goals, away_goals, home_xg, away_xg, rho))
            row.append(probability)
        raw.append(row)
    total = sum(sum(row) for row in raw)
    matrix = tuple(tuple(value / total for value in row) for row in raw)
    home = sum(matrix[i][j] for i in range(len(matrix)) for j in range(len(matrix[i])) if i > j)
    draw = sum(matrix[i][i] for i in range(len(matrix)))
    away = 1 - home - draw
    scores = sorted(
        (ScoreProbability(i, j, matrix[i][j]) for i in range(len(matrix)) for j in range(len(matrix[i]))),
        key=lambda item: item.probability,
        reverse=True,
    )
    return DixonColesPrediction(
        home_xg=home_xg,
        away_xg=away_xg,
        matrix=matrix,
        probabilities=Probability3.normalized((home, draw, away)),
        top_scores=tuple(scores[:5]),
    )


def predict_from_features(home: TeamFeatures, away: TeamFeatures, max_goals: int = 8) -> DixonColesPrediction:
    league_base = 1.32
    home_attack = home.xg_for if home.xg_for is not None else league_base
    away_defence = away.xg_against if away.xg_against is not None else league_base
    away_attack = away.xg_for if away.xg_for is not None else league_base
    home_defence = home.xg_against if home.xg_against is not None else league_base
    home_xg = (home_attack + away_defence) / 2 * 1.10
    away_xg = (away_attack + home_defence) / 2
    if home.elo is not None and away.elo is not None:
        # 标准 Elo 刻度是 /400；旧的 /900 + sqrt 会把实力差压缩到约四分之一，
        # 导致强队被严重低估（386 分差旧版只给 54% 胜率，市场/标准 Elo 均为约 76-90%）。
        elo_factor = math.exp(max(-600, min(600, home.elo - away.elo)) / 400)
        home_xg *= math.sqrt(elo_factor)
        away_xg /= math.sqrt(elo_factor)
    form_delta = max(-1, min(1, home.form_index - away.form_index))
    home_xg *= 1 + 0.06 * form_delta
    away_xg *= 1 - 0.06 * form_delta
    return build_prediction(_bounded_xg(home_xg), _bounded_xg(away_xg), max_goals=max_goals)


def _bounded_xg(value: float) -> float:
    return max(0.2, min(4.5, float(value)))


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析比赛日期：{value}")
