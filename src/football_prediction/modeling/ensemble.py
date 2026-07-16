"""基于样本外概率学习市场融合权重。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from ..domain import Outcome, Probability3


def logarithmic_pool(model: Probability3, market: Probability3, market_weight: float) -> Probability3:
    values = [
        math.exp(
            (1 - market_weight) * math.log(max(1e-12, p_model))
            + market_weight * math.log(max(1e-12, p_market))
        )
        for p_model, p_market in zip(model.vector(), market.vector(), strict=True)
    ]
    return Probability3.normalized(values)


@dataclass(frozen=True)
class LogPoolEnsemble:
    market_weight: float = 0.0
    trained_until: str | None = None
    sample_size: int = 0
    outcome_biases: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def transform(self, model: Probability3, market: Probability3 | None) -> Probability3:
        if market is None:
            base = model
        elif self.market_weight <= 0:
            base = model
        else:
            base = logarithmic_pool(model, market, self.market_weight)
        logits = [
            math.log(max(1e-12, probability)) + bias
            for probability, bias in zip(base.vector(), self.outcome_biases, strict=True)
        ]
        peak = max(logits)
        return Probability3.normalized(math.exp(value - peak) for value in logits)

    @classmethod
    def fit(
        cls,
        model_probabilities: Sequence[Probability3],
        market_probabilities: Sequence[Probability3],
        outcomes: Sequence[Outcome],
        *,
        trained_until: str | None = None,
    ) -> "LogPoolEnsemble":
        if not (
            len(model_probabilities) == len(market_probabilities) == len(outcomes)
            and len(outcomes) >= 30
        ):
            raise ValueError("融合器至少需要 30 条对齐的模型、市场概率和赛果")

        def loss(params: np.ndarray) -> float:
            weight = float(params[0])
            raw_biases = np.asarray(params[1:4], dtype=float)
            biases = raw_biases - raw_biases.mean()
            total = 0.0
            for model, market, actual in zip(
                model_probabilities,
                market_probabilities,
                outcomes,
                strict=True,
            ):
                pooled = logarithmic_pool(model, market, weight)
                logits = np.log(np.clip(np.asarray(pooled.vector()), 1e-12, 1)) + biases
                logits -= logits.max()
                probabilities = np.exp(logits)
                probabilities /= probabilities.sum()
                index = {Outcome.HOME: 0, Outcome.DRAW: 1, Outcome.AWAY: 2}[actual]
                total -= math.log(max(1e-12, float(probabilities[index])))
            # 轻量 L2 防止小样本把赛果偏置拉得过大。
            regularization = 0.01 * float(np.sum(biases**2))
            return total / len(outcomes) + regularization

        result = minimize(
            loss,
            np.asarray([0.5, 0.0, 0.0, 0.0]),
            method="L-BFGS-B",
            bounds=((0.0, 1.0), (-0.5, 0.5), (-0.5, 0.5), (-0.5, 0.5)),
        )
        if not result.success:
            raise RuntimeError(f"融合器拟合失败：{result.message}")
        biases = np.asarray(result.x[1:4], dtype=float)
        biases -= biases.mean()
        return cls(
            market_weight=float(result.x[0]),
            outcome_biases=tuple(float(value) for value in biases),
            trained_until=trained_until,
            sample_size=len(outcomes),
        )
