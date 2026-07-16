#!/usr/bin/env python3
"""批量运行多联赛赛季的统一生产管线回放。"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from football_prediction.backtest import rolling_backtest
from football_prediction.config import Settings
from football_prediction.domain import to_dict
from football_prediction.providers.football_data import FootballDataProvider


def _run(path_text: str, pipeline: str) -> tuple[str, dict]:
    path = Path(path_text)
    history = FootballDataProvider().read(path)
    summary, _ = rolling_backtest(
        history,
        min_train=120,
        window=600,
        refit_every=30,
        pipeline_mode=pipeline,
        settings=Settings(),
    )
    return path.name, to_dict(summary)


def _weighted(rows: list[dict], key: str, *, weight_key: str = "matches") -> float | None:
    usable = [row for row in rows if row.get(key) is not None and row.get(weight_key, 0)]
    denominator = sum(int(row[weight_key]) for row in usable)
    if denominator == 0:
        return None
    return sum(float(row[key]) * int(row[weight_key]) for row in usable) / denominator


def aggregate(rows: list[dict]) -> dict:
    matches = sum(int(row["matches"]) for row in rows)
    bets = sum(int(row["bets"]) for row in rows)

    def aggregate_counts(field: str) -> list[dict[str, str | int]]:
        counts: dict[str, int] = {}
        for row in rows:
            for item in row.get(field, []):
                state = str(item["state"])
                counts[state] = counts.get(state, 0) + int(item["count"])
        return [
            {"state": state, "count": count}
            for state, count in sorted(counts.items())
        ]

    return {
        "files": len(rows),
        "matches": matches,
        "accuracy": _weighted(rows, "accuracy"),
        "brier": _weighted(rows, "brier"),
        "baseline_brier": _weighted(rows, "baseline_brier"),
        "log_loss": _weighted(rows, "log_loss"),
        "baseline_log_loss": _weighted(rows, "baseline_log_loss"),
        "rps": _weighted(rows, "rps"),
        "baseline_rps": _weighted(rows, "baseline_rps"),
        "ece": _weighted(rows, "ece"),
        "bets": bets,
        "coverage": bets / matches if matches else 0.0,
        "roi": (
            sum(float(row["roi"]) * int(row["bets"]) for row in rows) / bets
            if bets
            else 0.0
        ),
        "max_drawdown": max((float(row["max_drawdown"]) for row in rows), default=0.0),
        "decision_counts": aggregate_counts("decision_counts"),
        "direction_counts": aggregate_counts("direction_counts"),
        "value_counts": aggregate_counts("value_counts"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--pipeline",
        choices=("production", "independent-value"),
        default="production",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    paths = sorted(args.directory.glob("*.csv"))
    if not paths:
        raise SystemExit("没有找到 CSV")
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(_run, str(path), args.pipeline): path.name
            for path in paths
        }
        for future in as_completed(futures):
            name, summary = future.result()
            results[name] = summary
            print(
                f"{name}: Brier {summary['brier']:.4f}/{summary['baseline_brier']:.4f}, "
                f"ECE {summary['ece']:.4f}, bets {summary['bets']}",
                file=sys.stderr,
                flush=True,
            )

    ordered = [{"file": name, **results[name]} for name in sorted(results)]
    payload = {
        "pipeline": args.pipeline,
        "aggregate": aggregate(ordered),
        "runs": ordered,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
