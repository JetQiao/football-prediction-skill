"""把结构化预测渲染成零网络依赖的单文件研究工作台。"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain import DailyReport, to_dict
from .flags import flag_data_uri
from .view_models import CONFIDENCE_LABELS, OUTCOME_LABELS, build_match_view


def _resource_text(relative: str) -> str:
    return files("football_prediction.reporting").joinpath(relative).read_text(encoding="utf-8")


def render_report(report: DailyReport) -> str:
    template_dir = files("football_prediction.reporting").joinpath("templates")
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["pct"] = lambda value: f"{float(value):.1%}" if value is not None else "—"
    environment.filters["pct0"] = lambda value: f"{float(value):.0%}" if value is not None else "—"
    environment.filters["num"] = lambda value: f"{float(value):.2f}" if value is not None else "—"
    environment.filters["signed_pct"] = (
        lambda value: f"{float(value):+.1%}" if value is not None else "—"
    )
    environment.filters["json"] = lambda value: json.dumps(
        to_dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    environment.globals.update(
        outcome_labels=OUTCOME_LABELS,
        confidence_labels=CONFIDENCE_LABELS,
    )

    cards = [build_match_view(prediction) for prediction in report.predictions]
    leagues = sorted({card["league"] for card in cards})
    used_flag_codes = sorted(
        {code for card in cards for code in (card["home_flag"], card["away_flag"]) if code}
    )
    flag_styles = "\n".join(
        f".flag-{code}{{background-image:url('{flag_data_uri(code)}')}}"
        for code in used_flag_codes
    )
    payload = to_dict(report)
    report_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    counts = {
        "candidate": sum(card["decision_state"] == "candidate" for card in cards),
        "lean": sum(card["decision_state"] == "lean" for card in cards),
        "no_edge": sum(card["decision_state"] == "no_edge" for card in cards),
        "abstain": sum(card["decision_state"] == "abstain" for card in cards),
        "complete": sum(card["data_quality"] == "complete" for card in cards),
        "degraded": sum(card["is_degraded"] for card in cards),
    }
    return environment.get_template("report.html").render(
        report=report,
        cards=cards,
        leagues=leagues,
        counts=counts,
        styles=_resource_text("static/report.css"),
        scripts=_resource_text("static/report.js"),
        flag_styles=flag_styles,
        report_json=report_json,
        demo_count=sum(card["is_demo"] for card in cards),
    )


def write_report(report: DailyReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(report), encoding="utf-8")
    return path
