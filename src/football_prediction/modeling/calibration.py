"""多分类温度校准；训练时仅允许使用预测时点之前的数据。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.optimize import minimize_scalar

from ..domain import Outcome, Probability3


@dataclass(frozen=True)
class TemperatureCalibrator:
    temperature: float = 1.0
    trained_until: str | None = None

    def transform(self, probabilities: Probability3) -> Probability3:
        logits = np.log(np.clip(np.asarray(probabilities.vector()), 1e-12, 1)) / self.temperature
        logits -= np.max(logits)
        values = np.exp(logits)
        return Probability3.normalized(values / values.sum())

    @classmethod
    def fit(
        cls,
        probabilities: Sequence[Probability3],
        outcomes: Sequence[Outcome],
        *,
        trained_until: str | None = None,
    ) -> "TemperatureCalibrator":
        if len(probabilities) != len(outcomes) or len(probabilities) < 30:
            raise ValueError("温度校准至少需要 30 条概率与彩果")
        matrix = np.asarray([row.vector() for row in probabilities], dtype=float)
        labels = np.asarray([{Outcome.HOME: 0, Outcome.DRAW: 1, Outcome.AWAY: 2}[row] for row in outcomes])

        def loss(temperature: float) -> float:
            logits = np.log(np.clip(matrix, 1e-12, 1)) / temperature
            logits -= logits.max(axis=1, keepdims=True)
            calibrated = np.exp(logits)
            calibrated /= calibrated.sum(axis=1, keepdims=True)
            return float(-np.log(np.clip(calibrated[np.arange(len(labels)), labels], 1e-12, 1)).mean())

        result = minimize_scalar(loss, bounds=(0.35, 3.0), method="bounded")
        return cls(float(result.x), trained_until)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"temperature": self.temperature, "trained_until": self.trained_until}, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "TemperatureCalibrator":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(float(payload["temperature"]), payload.get("trained_until"))
