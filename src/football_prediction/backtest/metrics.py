"""命中率、Brier、log-loss、ROI、最大回撤和可靠性曲线。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from ..domain import (
    BacktestSummary,
    DecisionState,
    DirectionState,
    Outcome,
    Probability3,
    ThreeWayOdds,
    ValueState,
)
from ..modeling.odds import assess_value, remove_vig


@dataclass(frozen=True)
class BacktestObservation:
    probabilities: Probability3
    actual: Outcome
    offered_odds: ThreeWayOdds | None = None
    value_threshold: float = 0.05
    decision_state: DecisionState | str | None = None
    direction_state: DirectionState | str | None = None
    value_state: ValueState | str | None = None
    target_used_as_signal: bool = False
    devig_method: str = "multiplicative"


def _rps(probabilities: Probability3, actual: Outcome) -> float:
    values = probabilities.vector()
    actual_vector = tuple(1.0 if outcome == actual else 0.0 for outcome in Outcome)
    predicted_cumulative = (values[0], values[0] + values[1])
    actual_cumulative = (actual_vector[0], actual_vector[0] + actual_vector[1])
    return sum((predicted - observed) ** 2 for predicted, observed in zip(
        predicted_cumulative,
        actual_cumulative,
        strict=True,
    )) / 2


def _calibration_line(confidences: list[float], hits: list[int]) -> tuple[float | None, float | None]:
    if len(confidences) < 30 or len(set(hits)) < 2:
        return None, None
    x = np.log(np.clip(np.asarray(confidences), 1e-6, 1 - 1e-6) / np.clip(
        1 - np.asarray(confidences),
        1e-6,
        1,
    ))
    y = np.asarray(hits, dtype=float)

    def loss(params: np.ndarray) -> float:
        logits = params[0] + params[1] * x
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
        return float(
            -(
                y * np.log(np.clip(probabilities, 1e-12, 1))
                + (1 - y) * np.log(np.clip(1 - probabilities, 1e-12, 1))
            ).mean()
        )

    result = minimize(loss, np.asarray([0.0, 1.0]), method="BFGS")
    if not result.success:
        return None, None
    return float(result.x[1]), float(result.x[0])


def evaluate(observations: Sequence[BacktestObservation]) -> BacktestSummary:
    if not observations:
        return BacktestSummary(0, 0, 0, 0, 0, 0, 0)
    hits = 0
    brier_total = 0.0
    log_loss_total = 0.0
    rps_total = 0.0
    initial_bankroll = 100.0
    bankroll = initial_bankroll
    profit_units = 0.0
    equity_curve = [0.0]
    drawdown_curve = [0.0]
    peak = initial_bankroll
    max_drawdown = 0.0
    bets = 0
    baseline_brier_total = 0.0
    baseline_log_loss_total = 0.0
    baseline_rps_total = 0.0
    baseline_count = 0
    bins: dict[int, list[float]] = {index: [0.0, 0.0, 0.0] for index in range(10)}
    confidences: list[float] = []
    confidence_hits: list[int] = []
    decision_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    value_counts: dict[str, int] = {}

    for row in observations:
        predicted = row.probabilities.best()
        hit = int(predicted == row.actual)
        hits += hit
        actual_vector = [1.0 if outcome == row.actual else 0.0 for outcome in Outcome]
        brier_total += (
            sum(
                (probability - actual) ** 2
                for probability, actual in zip(row.probabilities.vector(), actual_vector, strict=True)
            )
            / 3
        )
        log_loss_total -= math.log(max(1e-12, row.probabilities.get(row.actual)))
        rps_total += _rps(row.probabilities, row.actual)

        confidence = row.probabilities.get(predicted)
        bin_index = min(9, int(confidence * 10))
        bins[bin_index][0] += 1
        bins[bin_index][1] += hit
        bins[bin_index][2] += confidence
        confidences.append(confidence)
        confidence_hits.append(hit)
        raw_state = (
            row.decision_state.value
            if isinstance(row.decision_state, DecisionState)
            else str(row.decision_state or "unclassified")
        )
        decision_counts[raw_state] = decision_counts.get(raw_state, 0) + 1
        raw_direction = (
            row.direction_state.value
            if isinstance(row.direction_state, DirectionState)
            else str(row.direction_state or "unclassified")
        )
        raw_value = (
            row.value_state.value
            if isinstance(row.value_state, ValueState)
            else str(row.value_state or "unclassified")
        )
        direction_counts[raw_direction] = direction_counts.get(raw_direction, 0) + 1
        value_counts[raw_value] = value_counts.get(raw_value, 0) + 1

        if row.offered_odds:
            baseline = remove_vig(row.offered_odds, method=row.devig_method)
            baseline_brier_total += (
                sum(
                    (probability - actual) ** 2
                    for probability, actual in zip(baseline.vector(), actual_vector, strict=True)
                )
                / 3
            )
            baseline_log_loss_total -= math.log(max(1e-12, baseline.get(row.actual)))
            baseline_rps_total += _rps(baseline, row.actual)
            baseline_count += 1
            value = assess_value(
                row.probabilities,
                row.offered_odds,
                threshold=row.value_threshold,
                devig_method=row.devig_method,
            )
            eligible_state = (
                raw_value == ValueState.CANDIDATE.value
                if row.value_state is not None
                else row.decision_state is None or raw_state == DecisionState.CANDIDATE.value
            )
            if eligible_state and not row.target_used_as_signal and value.flag == "value":
                bets += 1
                profit = value.odds - 1 if value.pick == row.actual else -1
                profit_units += profit
                bankroll += profit
                equity_curve.append(bankroll / initial_bankroll - 1)
                peak = max(peak, bankroll)
                drawdown = (peak - bankroll) / peak if peak > 0 else 0.0
                max_drawdown = max(max_drawdown, drawdown)
                drawdown_curve.append(drawdown)

    reliability = tuple(
        {
            "lower": index / 10,
            "upper": (index + 1) / 10,
            "count": int(count),
            "predicted": confidence_sum / count if count else 0,
            "actual": hits_in_bin / count if count else 0,
        }
        for index, (count, hits_in_bin, confidence_sum) in bins.items()
        if count
    )
    ece = sum(
        int(row["count"]) / len(observations) * abs(float(row["actual"]) - float(row["predicted"]))
        for row in reliability
    )
    calibration_slope, calibration_intercept = _calibration_line(confidences, confidence_hits)
    return BacktestSummary(
        matches=len(observations),
        accuracy=hits / len(observations),
        brier=brier_total / len(observations),
        log_loss=log_loss_total / len(observations),
        roi=profit_units / bets if bets else 0.0,
        max_drawdown=max_drawdown,
        bets=bets,
        baseline_brier=baseline_brier_total / baseline_count if baseline_count else None,
        baseline_log_loss=baseline_log_loss_total / baseline_count if baseline_count else None,
        reliability=reliability,
        equity_curve=tuple(equity_curve),
        rps=rps_total / len(observations),
        ece=ece,
        calibration_slope=calibration_slope,
        calibration_intercept=calibration_intercept,
        baseline_rps=baseline_rps_total / baseline_count if baseline_count else None,
        drawdown_curve=tuple(drawdown_curve),
        coverage=bets / len(observations),
        decision_counts=tuple(
            {"state": state, "count": count}
            for state, count in sorted(decision_counts.items())
        ),
        direction_counts=tuple(
            {"state": state, "count": count}
            for state, count in sorted(direction_counts.items())
        ),
        value_counts=tuple(
            {"state": state, "count": count}
            for state, count in sorted(value_counts.items())
        ),
    )
