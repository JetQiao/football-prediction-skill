"""防未来数据泄漏的滚动窗口 Dixon-Coles 回测。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from ..domain import Outcome, ThreeWayOdds
from ..modeling.dixon_coles import DixonColesEstimator, DixonColesModel
from ..providers.football_data import HistoricalMatch
from .metrics import BacktestObservation, evaluate


def rolling_backtest(
    matches: Sequence[HistoricalMatch],
    *,
    min_train: int = 120,
    window: int = 600,
    refit_every: int = 30,
):
    ordered = sorted(matches, key=lambda row: datetime.fromisoformat(row.date))
    if len(ordered) <= min_train:
        raise ValueError(f"滚动回测至少需要 {min_train + 1} 场比赛")
    estimator = DixonColesEstimator()
    model: DixonColesModel | None = None
    observations: list[BacktestObservation] = []
    for index in range(min_train, len(ordered)):
        if model is None or (index - min_train) % refit_every == 0:
            model = estimator.fit(ordered[max(0, index - window) : index])
        current = ordered[index]
        if current.home not in model.teams or current.away not in model.teams:
            continue
        prediction = model.predict(current.home, current.away)
        actual = (
            Outcome.HOME
            if current.home_goals > current.away_goals
            else Outcome.AWAY
            if current.home_goals < current.away_goals
            else Outcome.DRAW
        )
        odds = None
        if current.home_odds and current.draw_odds and current.away_odds:
            odds = ThreeWayOdds(
                current.home_odds,
                current.draw_odds,
                current.away_odds,
                f"football-data:{current.odds_source or 'unknown'}",
                current.date,
            )
        observations.append(BacktestObservation(prediction.probabilities, actual, odds))
    return evaluate(observations), observations
