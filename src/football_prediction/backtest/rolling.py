"""通过生产 PredictionPipeline 执行同日无泄漏滚动回放。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from ..config import Settings
from ..domain import MarketRole, Match, Outcome, TeamFeatures, ThreeWayOdds
from ..modeling.calibration import TemperatureCalibrator
from ..modeling.dixon_coles import DixonColesEstimator, DixonColesModel
from ..modeling.odds import select_devig_method
from ..modeling.registry import ModelBundle, ModelMetadata
from ..modeling.training import OOFRow, _evaluate_stack, _fit_probability_stack, passes_promotion_gate
from ..prediction import PredictionContext, PredictionPipeline
from ..providers.football_data import HistoricalMatch
from .metrics import BacktestObservation, evaluate


def _actual(row: HistoricalMatch) -> Outcome:
    return (
        Outcome.HOME
        if row.home_goals > row.away_goals
        else Outcome.AWAY
        if row.home_goals < row.away_goals
        else Outcome.DRAW
    )


def _odds(row: HistoricalMatch) -> ThreeWayOdds | None:
    if not (row.home_odds and row.draw_odds and row.away_odds):
        return None
    return ThreeWayOdds(
        row.home_odds,
        row.draw_odds,
        row.away_odds,
        f"football-data:{row.odds_source or 'unknown'}",
        f"{row.date}T00:00:00+08:00",
        MarketRole.BENCHMARK,
    )


def rolling_backtest(
    matches: Sequence[HistoricalMatch],
    *,
    min_train: int = 120,
    window: int = 600,
    refit_every: int = 30,
    pipeline_mode: str = "production",
    settings: Settings | None = None,
):
    """回放生产管线。

    `production`：历史市场作为 reference/benchmark，只评价概率，不把同源价格用于价值下注。
    `independent-value`：市场只作为 target/benchmark，用独立模型评估价值策略。
    """

    if pipeline_mode not in {"production", "independent-value"}:
        raise ValueError("pipeline_mode 必须是 production 或 independent-value")
    ordered = sorted(matches, key=lambda row: (datetime.fromisoformat(row.date), row.home, row.away))
    if len(ordered) <= min_train:
        raise ValueError(f"滚动回测至少需要 {min_train + 1} 场比赛")

    by_date: dict[str, list[HistoricalMatch]] = {}
    for row in ordered:
        by_date.setdefault(row.date, []).append(row)

    estimator = DixonColesEstimator()
    model: DixonColesModel | None = None
    observations: list[BacktestObservation] = []
    history: list[HistoricalMatch] = []
    past_oof: list[OOFRow] = []
    rows_since_refit = refit_every
    stack_since_refit = refit_every
    ensemble = None
    calibrator: TemperatureCalibrator | None = None
    devig_method = "multiplicative"
    stack_gate_passed = False
    prediction_pipeline = PredictionPipeline(settings or Settings())

    for match_date, day_rows in sorted(by_date.items()):
        if len(history) < min_train:
            history.extend(day_rows)
            continue
        if model is None or rows_since_refit >= refit_every:
            model = estimator.fit(history[max(0, len(history) - window) :])
            rows_since_refit = 0

        market_oof = [row for row in past_oof if row.benchmark_odds]
        if len(past_oof) >= 60 and (calibrator is None or stack_since_refit >= refit_every):
            if len(market_oof) >= 30:
                devig_method, _ = select_devig_method(
                    [row.benchmark_odds for row in market_oof if row.benchmark_odds],
                    [row.actual for row in market_oof],
                )
            split = max(30, int(len(past_oof) * 0.75))
            stack_train = past_oof[:split]
            stack_validation = past_oof[split:]
            if pipeline_mode == "production":
                validation_ensemble, validation_calibrator = _fit_probability_stack(
                    stack_train,
                    trained_until=stack_train[-1].date,
                    devig_method=devig_method,
                )
            else:
                validation_ensemble = None
                validation_calibrator = TemperatureCalibrator.fit(
                    [row.model_probability for row in stack_train],
                    [row.actual for row in stack_train],
                    trained_until=stack_train[-1].date,
                )
            stack_gate_passed = passes_promotion_gate(
                _evaluate_stack(
                    stack_validation,
                    devig_method=devig_method,
                    ensemble=validation_ensemble,
                    calibrator=validation_calibrator,
                )
            )

            # 回放中的生产参数只使用预测日前已产生的全部 OOF 概率重训。
            if pipeline_mode == "production":
                ensemble, calibrator = _fit_probability_stack(
                    past_oof,
                    trained_until=history[-1].date,
                    devig_method=devig_method,
                )
            else:
                ensemble = None
                calibrator = TemperatureCalibrator.fit(
                    [row.model_probability for row in past_oof],
                    [row.actual for row in past_oof],
                    trained_until=history[-1].date,
                )
            stack_since_refit = 0

        metadata = ModelMetadata(
            version=f"replay-{match_date}",
            competition="historical-replay",
            trained_until=history[-1].date,
            sample_size=len(history),
            calibration_status="validated" if stack_gate_passed else "provisional",
            calibration_sample_size=len(past_oof),
            devig_method=devig_method,
            promoted=True,
        )
        bundle = ModelBundle(metadata, model, calibrator, ensemble)

        for current in day_rows:
            if current.home not in model.teams or current.away not in model.teams:
                continue
            benchmark = _odds(current)
            match = Match(
                id=f"{current.date}:{current.home}:{current.away}",
                business_date=current.date,
                match_no=f"{current.date}-{len(observations) + 1}",
                league="historical-replay",
                home=current.home,
                away=current.away,
                kickoff_at=f"{current.date}T12:00:00+08:00",
                intel_tier="B",
            )
            prediction = prediction_pipeline.predict(
                PredictionContext(
                    match=match,
                    home_features=TeamFeatures(current.home),
                    away_features=TeamFeatures(current.away),
                    reference_market_odds=benchmark if pipeline_mode == "production" else None,
                    target_market_odds=benchmark if pipeline_mode == "independent-value" else None,
                    as_of=f"{current.date}T01:00:00+08:00",
                ),
                bundle=bundle,
            )
            actual = _actual(current)
            observations.append(
                BacktestObservation(
                    prediction.final_probs,
                    actual,
                    benchmark,
                    decision_state=prediction.decision_state,
                    direction_state=prediction.direction_state,
                    value_state=prediction.value_state,
                    target_used_as_signal=prediction.target_used_as_signal,
                    devig_method=devig_method,
                )
            )
            past_oof.append(
                OOFRow(
                    date=current.date,
                    model_probability=prediction.model_probs,
                    actual=actual,
                    benchmark_odds=benchmark,
                )
            )

        # 关键约束：当天全部预测结束后，赛果才进入训练历史。
        history.extend(day_rows)
        rows_since_refit += len(day_rows)
        stack_since_refit += len(day_rows)
    return evaluate(observations), observations
