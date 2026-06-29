"""把结构化预测渲染成零网络依赖的单文件报告。"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain import DailyReport, to_dict

OUTCOME_LABELS = {"home": "主胜", "draw": "平", "away": "客胜"}
CONFIDENCE_LABELS = {"high": "高", "mid": "中", "low": "低"}


def render_report(report: DailyReport) -> str:
    template_dir = files("football_prediction.reporting").joinpath("templates")
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["pct"] = lambda value: f"{float(value):.1%}"
    environment.filters["num"] = lambda value: f"{float(value):.2f}"
    environment.globals.update(outcome_labels=OUTCOME_LABELS, confidence_labels=CONFIDENCE_LABELS)
    payload = to_dict(report)
    # 防止用户提供的字符串提前闭合 script 标签。
    report_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    selected = [
        prediction
        for prediction in report.predictions
        if prediction.confidence == "high" or (prediction.value and prediction.value.flag == "value")
    ]
    return environment.get_template("report.html").render(
        report=report,
        selected=selected,
        report_json=report_json,
    )


def write_report(report: DailyReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(report), encoding="utf-8")
    return path
