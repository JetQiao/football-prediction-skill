"""同日无泄漏的 OOF 训练、融合、校准与模型打包。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..backtest.metrics import BacktestObservation, evaluate
from ..domain import MarketRole, Outcome, Probability3, ThreeWayOdds
from ..providers.football_data import HistoricalMatch
from .calibration import TemperatureCalibrator
from .dixon_coles import DixonColesEstimator, DixonColesModel
from .ensemble import LogPoolEnsemble
from .odds import remove_vig, select_devig_method
from .registry import ModelBundle, ModelMetadata


@dataclass(frozen=True)
class OOFRow:
    date: str
    model_probability: Probability3
    actual: Outcome
    benchmark_odds: ThreeWayOdds | None


def _actual(row: HistoricalMatch) -> Outcome:
    if row.home_goals > row.away_goals:
        return Outcome.HOME
    if row.home_goals < row.away_goals:
        return Outcome.AWAY
    return Outcome.DRAW


def _benchmark_odds(row: HistoricalMatch) -> ThreeWayOdds | None:
    if not (row.home_odds and row.draw_odds and row.away_odds):
        return None
    return ThreeWayOdds(
        row.home_odds,
        row.draw_odds,
        row.away_odds,
        f"football-data:{row.odds_source or 'unknown'}",
        row.date,
        MarketRole.BENCHMARK,
    )


def rolling_oof_predictions(
    matches: Sequence[HistoricalMatch],
    *,
    min_train: int = 120,
    window: int = 600,
    refit_every: int = 30,
) -> list[OOFRow]:
    """按比赛日整体留出，确保同一天赛果不会进入同日其他比赛的训练集。"""

    ordered = sorted(matches, key=lambda row: (row.date, row.home, row.away))
    by_date: dict[str, list[HistoricalMatch]] = {}
    for row in ordered:
        by_date.setdefault(row.date, []).append(row)

    history: list[HistoricalMatch] = []
    model: DixonColesModel | None = None
    rows_since_refit = refit_every
    output: list[OOFRow] = []
    estimator = DixonColesEstimator()

    for match_date, day_rows in sorted(by_date.items()):
        if len(history) >= min_train:
            if model is None or rows_since_refit >= refit_every:
                model = estimator.fit(history[max(0, len(history) - window) :])
                rows_since_refit = 0
            for current in day_rows:
                if current.home not in model.teams or current.away not in model.teams:
                    continue
                output.append(
                    OOFRow(
                        date=match_date,
                        model_probability=model.predict(current.home, current.away).probabilities,
                        actual=_actual(current),
                        benchmark_odds=_benchmark_odds(current),
                    )
                )
        # 关键约束：整天预测完成后，才把当天赛果加入历史。
        history.extend(day_rows)
        rows_since_refit += len(day_rows)
    return output


def _fit_probability_stack(
    rows: Sequence[OOFRow],
    *,
    trained_until: str,
    devig_method: str,
) -> tuple[LogPoolEnsemble | None, TemperatureCalibrator | None]:
    market_rows = [row for row in rows if row.benchmark_odds]
    ensemble = None
    if len(market_rows) >= 30:
        ensemble = LogPoolEnsemble.fit(
            [row.model_probability for row in market_rows],
            [remove_vig(row.benchmark_odds, method=devig_method) for row in market_rows if row.benchmark_odds],
            [row.actual for row in market_rows],
            trained_until=trained_until,
        )
    probabilities = [
        ensemble.transform(
            row.model_probability,
            remove_vig(row.benchmark_odds, method=devig_method) if row.benchmark_odds else None,
        )
        if ensemble
        else row.model_probability
        for row in rows
    ]
    calibrator = (
        TemperatureCalibrator.fit(
            probabilities,
            [row.actual for row in rows],
            trained_until=trained_until,
        )
        if len(rows) >= 30
        else None
    )
    return ensemble, calibrator


def _evaluate_stack(
    rows: Sequence[OOFRow],
    *,
    devig_method: str,
    ensemble: LogPoolEnsemble | None,
    calibrator: TemperatureCalibrator | None,
):
    observations: list[BacktestObservation] = []
    for row in rows:
        market = remove_vig(row.benchmark_odds, method=devig_method) if row.benchmark_odds else None
        probability = ensemble.transform(row.model_probability, market) if ensemble else row.model_probability
        if calibrator:
            probability = calibrator.transform(probability)
        observations.append(
            BacktestObservation(
                probabilities=probability,
                actual=row.actual,
                offered_odds=row.benchmark_odds,
                value_threshold=10.0,  # 训练验证只比较概率，不模拟同源价格的价值策略。
            )
        )
    return evaluate(observations)


def passes_promotion_gate(summary) -> bool:
    """统一模型晋级门槛，训练与历史回放不得各自放宽。"""

    if (
        summary.baseline_brier is None
        or summary.baseline_log_loss is None
        or summary.baseline_rps is None
    ):
        return False
    return bool(
        summary.log_loss <= float(summary.baseline_log_loss) * 1.002
        and summary.brier <= float(summary.baseline_brier) * 0.995
        and summary.rps <= float(summary.baseline_rps) * 1.002
        and summary.ece <= 0.03
    )


def train_model_bundle(
    matches: Sequence[HistoricalMatch],
    *,
    competition: str,
    aliases: Sequence[str] = (),
    until: str | None = None,
    min_train: int = 120,
    window: int = 600,
    refit_every: int = 30,
    version: str | None = None,
) -> ModelBundle:
    if until:
        selected = [row for row in matches if row.date <= until]
    else:
        selected = list(matches)
    if len(selected) < min_train + 30:
        raise ValueError(f"训练至少需要 {min_train + 30} 场比赛")

    trained_until = max(row.date for row in selected)
    oof = rolling_oof_predictions(
        selected,
        min_train=min_train,
        window=window,
        refit_every=refit_every,
    )
    if len(oof) < 60:
        raise ValueError("可用样本外预测不足 60 场，无法可靠训练融合与校准")

    split = max(30, int(len(oof) * 0.75))
    train_rows = oof[:split]
    validation_rows = oof[split:]
    train_market_rows = [row for row in train_rows if row.benchmark_odds]
    if len(train_market_rows) >= 30:
        devig_method, devig_scores = select_devig_method(
            [row.benchmark_odds for row in train_market_rows if row.benchmark_odds],
            [row.actual for row in train_market_rows],
        )
    else:
        devig_method, devig_scores = "multiplicative", {}

    ensemble, calibrator = _fit_probability_stack(
        train_rows,
        trained_until=train_rows[-1].date,
        devig_method=devig_method,
    )
    validation = _evaluate_stack(
        validation_rows,
        devig_method=devig_method,
        ensemble=ensemble,
        calibrator=calibrator,
    )
    validated = passes_promotion_gate(validation)

    # 验证完成后用全部 OOF 概率重训生产融合器与校准器。
    final_ensemble, final_calibrator = _fit_probability_stack(
        oof,
        trained_until=trained_until,
        devig_method=devig_method,
    )
    final_model = DixonColesEstimator().fit(selected[-window:])

    if not version:
        digest = hashlib.sha256(
            f"{competition}|{trained_until}|{len(selected)}|{devig_method}".encode()
        ).hexdigest()[:8]
        version = f"{competition}-{trained_until}-{digest}"

    metadata = ModelMetadata(
        version=version,
        competition=competition,
        aliases=tuple(aliases),
        trained_until=trained_until,
        sample_size=len(selected),
        calibration_status="validated" if validated else "provisional",
        calibration_sample_size=len(oof),
        devig_method=devig_method,
        promoted=False,
        validation={
            "from": validation_rows[0].date,
            "until": validation_rows[-1].date,
            "matches": validation.matches,
            "brier": validation.brier,
            "baseline_brier": validation.baseline_brier,
            "log_loss": validation.log_loss,
            "baseline_log_loss": validation.baseline_log_loss,
            "rps": validation.rps,
            "baseline_rps": validation.baseline_rps,
            "ece": validation.ece,
            "market_weight": final_ensemble.market_weight if final_ensemble else 0.0,
            "gate_passed": validated,
            "devig_scores": {key: round(value, 8) for key, value in devig_scores.items()},
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    return ModelBundle(metadata, final_model, final_calibrator, final_ensemble)
