"""命中率、Brier、log-loss、ROI、最大回撤和可靠性曲线。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ..domain import BacktestSummary, Outcome, Probability3, ThreeWayOdds
from ..modeling.odds import remove_vig


@dataclass(frozen=True)
class BacktestObservation:
    probabilities: Probability3
    actual: Outcome
    offered_odds: ThreeWayOdds | None = None
    value_threshold: float = 0.05


def evaluate(observations: Sequence[BacktestObservation]) -> BacktestSummary:
    if not observations:
        return BacktestSummary(0, 0, 0, 0, 0, 0, 0)
    hits = 0
    brier_total = 0.0
    log_loss_total = 0.0
    equity = 0.0
    equity_curve = [equity]
    peak = 0.0
    max_drawdown = 0.0
    bets = 0
    baseline_brier_total = 0.0
    baseline_log_loss_total = 0.0
    baseline_count = 0
    bins: dict[int, list[int]] = {index: [0, 0] for index in range(10)}

    for row in observations:
        predicted = row.probabilities.best()
        hits += predicted == row.actual
        actual_vector = [1.0 if outcome == row.actual else 0.0 for outcome in Outcome]
        brier_total += (
            sum(
                (probability - actual) ** 2
                for probability, actual in zip(row.probabilities.vector(), actual_vector, strict=True)
            )
            / 3
        )
        log_loss_total -= math.log(max(1e-12, row.probabilities.get(row.actual)))

        confidence = row.probabilities.get(predicted)
        bin_index = min(9, int(confidence * 10))
        bins[bin_index][0] += 1
        bins[bin_index][1] += predicted == row.actual

        if row.offered_odds:
            baseline = remove_vig(row.offered_odds)
            baseline_brier_total += (
                sum(
                    (probability - actual) ** 2
                    for probability, actual in zip(baseline.vector(), actual_vector, strict=True)
                )
                / 3
            )
            baseline_log_loss_total -= math.log(max(1e-12, baseline.get(row.actual)))
            baseline_count += 1
            odds = row.offered_odds.get(predicted)
            ev = confidence * odds - 1
            if ev >= row.value_threshold:
                bets += 1
                equity += odds - 1 if predicted == row.actual else -1
                equity_curve.append(equity)
                peak = max(peak, equity)
                max_drawdown = max(max_drawdown, peak - equity)

    reliability = tuple(
        {
            "lower": index / 10,
            "upper": (index + 1) / 10,
            "count": count,
            "actual": hits_in_bin / count if count else 0,
        }
        for index, (count, hits_in_bin) in bins.items()
        if count
    )
    return BacktestSummary(
        matches=len(observations),
        accuracy=hits / len(observations),
        brier=brier_total / len(observations),
        log_loss=log_loss_total / len(observations),
        roi=equity / bets if bets else 0.0,
        max_drawdown=max_drawdown,
        bets=bets,
        baseline_brier=baseline_brier_total / baseline_count if baseline_count else None,
        baseline_log_loss=baseline_log_loss_total / baseline_count if baseline_count else None,
        reliability=reliability,
        equity_curve=tuple(equity_curve),
    )
