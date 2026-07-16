"""统计模型、概率融合和校准。

使用延迟导入，避免赔率工具、决策策略和融合引擎之间形成包级循环依赖。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DixonColesEstimator",
    "DixonColesModel",
    "PredictionEngine",
    "predict_from_features",
]


def __getattr__(name: str) -> Any:
    if name in {"DixonColesEstimator", "DixonColesModel", "predict_from_features"}:
        from .dixon_coles import DixonColesEstimator, DixonColesModel, predict_from_features

        return {
            "DixonColesEstimator": DixonColesEstimator,
            "DixonColesModel": DixonColesModel,
            "predict_from_features": predict_from_features,
        }[name]
    if name == "PredictionEngine":
        from .fusion import PredictionEngine

        return PredictionEngine
    raise AttributeError(name)
