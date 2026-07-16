"""把已保存的每日预测与赛后比分对齐，生成可重复的真实表现评估。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..domain import MarketRole, Outcome, Probability3, ThreeWayOdds, to_dict
from ..storage import read_json
from .metrics import BacktestObservation, evaluate


def _score(row: dict[str, Any]) -> tuple[int, int]:
    if row.get("score"):
        parts = str(row["score"]).replace("-", ":").split(":", 1)
        return int(parts[0]), int(parts[1])
    home = row.get("home_goals", row.get("home_score"))
    away = row.get("away_goals", row.get("away_score"))
    if home is None or away is None:
        raise ValueError("赛果必须提供 score 或 home_goals/away_goals")
    return int(home), int(away)


def _result_key(row: dict[str, Any]) -> str:
    return str(row.get("match_id") or row.get("id") or row.get("match_no") or "").strip()


def _summary(rows: list[tuple[BacktestObservation, dict[str, str]]]) -> dict[str, Any]:
    return to_dict(evaluate([observation for observation, _ in rows]))


def evaluate_daily_files(prediction_file: Path, results_file: Path) -> dict[str, Any]:
    prediction_payload = read_json(prediction_file)
    result_payload = read_json(results_file)
    result_rows = result_payload.get("results", result_payload) if isinstance(result_payload, dict) else result_payload
    results = {_result_key(row): row for row in result_rows if _result_key(row)}
    matched: list[tuple[BacktestObservation, dict[str, str]]] = []
    pending: list[dict[str, str]] = []

    for row in prediction_payload.get("predictions", []):
        match = row["match"]
        result = results.get(str(match["id"])) or results.get(str(match["match_no"]))
        if not result:
            pending.append({"match_id": str(match["id"]), "match_no": str(match["match_no"])})
            continue
        home_goals, away_goals = _score(result)
        actual = Outcome.HOME if home_goals > away_goals else Outcome.AWAY if home_goals < away_goals else Outcome.DRAW
        probabilities = Probability3(**row["final_probs"])
        raw_odds = match.get("sporttery_odds")
        odds = (
            ThreeWayOdds(
                float(raw_odds["home"]),
                float(raw_odds["draw"]),
                float(raw_odds["away"]),
                raw_odds.get("source", "prediction-snapshot"),
                raw_odds.get("updated_at", ""),
                MarketRole.TARGET,
            )
            if raw_odds
            else None
        )
        matched.append(
            (
                BacktestObservation(
                    probabilities,
                    actual,
                    odds,
                    decision_state=row.get("decision_state"),
                    direction_state=row.get("direction_state"),
                    value_state=row.get("value_state"),
                    target_used_as_signal=bool(row.get("target_used_as_signal", False)),
                ),
                {
                    "league": str(match.get("league", "未知联赛")),
                    "confidence": str(row.get("confidence", "unknown")),
                    "analysis_mode": str(row.get("analysis_mode", "unknown")),
                },
            )
        )

    if not matched:
        raise ValueError("赛果文件没有与预测快照匹配的已完赛场次")

    def grouped(field: str) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[tuple[BacktestObservation, dict[str, str]]]] = defaultdict(list)
        for item in matched:
            groups[item[1][field]].append(item)
        return {key: _summary(rows) for key, rows in sorted(groups.items())}

    return {
        "business_date": prediction_payload.get("business_date", ""),
        "prediction_run_id": prediction_payload.get("run_id", ""),
        "matched": len(matched),
        "pending": pending,
        "overall": _summary(matched),
        "by_league": grouped("league"),
        "by_confidence": grouped("confidence"),
        "by_analysis_mode": grouped("analysis_mode"),
    }
