"""滚动回测与概率质量评估（延迟导入避免训练循环依赖）。"""

from __future__ import annotations

from typing import Any

__all__ = ["BacktestObservation", "evaluate", "evaluate_daily_files", "rolling_backtest"]


def __getattr__(name: str) -> Any:
    if name in {"BacktestObservation", "evaluate"}:
        from .metrics import BacktestObservation, evaluate

        return {"BacktestObservation": BacktestObservation, "evaluate": evaluate}[name]
    if name == "evaluate_daily_files":
        from .daily import evaluate_daily_files

        return evaluate_daily_files
    if name == "rolling_backtest":
        from .rolling import rolling_backtest

        return rolling_backtest
    raise AttributeError(name)
