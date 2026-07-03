"""比分矩阵的归一化、赛果对齐与摘要工具。"""

from __future__ import annotations

from ..domain import Probability3, ScoreProbability


def blend_matrices(
    model: tuple[tuple[float, ...], ...],
    market: tuple[tuple[float, ...], ...],
    market_weight: float,
) -> tuple[tuple[float, ...], ...]:
    """线性融合两个同维比分矩阵，并保持总概率为 1。"""

    size = min(len(model), len(market))
    width = min(min((len(row) for row in model[:size]), default=0), min((len(row) for row in market[:size]), default=0))
    rows = tuple(
        tuple((1 - market_weight) * model[i][j] + market_weight * market[i][j] for j in range(width))
        for i in range(size)
    )
    total = sum(sum(row) for row in rows) or 1.0
    return tuple(tuple(value / total for value in row) for row in rows)


def outcome_probabilities(matrix: tuple[tuple[float, ...], ...] | list[list[float]]) -> Probability3:
    home = sum(value for i, row in enumerate(matrix) for j, value in enumerate(row) if i > j)
    draw = sum(row[i] for i, row in enumerate(matrix) if i < len(row))
    away = sum(value for i, row in enumerate(matrix) for j, value in enumerate(row) if i < j)
    return Probability3.normalized((home, draw, away))


def tilt_matrix(
    matrix: tuple[tuple[float, ...], ...] | list[list[float]],
    final: Probability3,
) -> tuple[tuple[float, ...], ...]:
    """按主/平/客条件概率缩放矩阵，使衍生玩法与最终赛果概率保持一致。"""

    current = outcome_probabilities(matrix)
    scales = {
        "home": final.home / current.home if current.home > 0 else 0.0,
        "draw": final.draw / current.draw if current.draw > 0 else 0.0,
        "away": final.away / current.away if current.away > 0 else 0.0,
    }
    tilted = []
    for i, source_row in enumerate(matrix):
        row = []
        for j, value in enumerate(source_row):
            key = "home" if i > j else "draw" if i == j else "away"
            row.append(value * scales[key])
        tilted.append(row)
    total = sum(sum(row) for row in tilted) or 1.0
    return tuple(tuple(value / total for value in row) for row in tilted)


def matrix_expected_goals(matrix: tuple[tuple[float, ...], ...]) -> tuple[float, float]:
    home = sum(i * value for i, row in enumerate(matrix) for value in row)
    away = sum(j * value for row in matrix for j, value in enumerate(row))
    return home, away


def matrix_top_scores(
    matrix: tuple[tuple[float, ...], ...],
    limit: int = 5,
) -> tuple[ScoreProbability, ...]:
    scores = sorted(
        (ScoreProbability(i, j, value) for i, row in enumerate(matrix) for j, value in enumerate(row)),
        key=lambda item: item.probability,
        reverse=True,
    )
    return tuple(scores[:limit])
