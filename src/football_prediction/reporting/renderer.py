"""把结构化预测渲染成零网络依赖的单文件报告。"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain import DailyReport, MatchPrediction, to_dict
from .analysis import derive_markets, plain_summary

OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
CONFIDENCE_LABELS = {"high": "高", "mid": "中", "low": "低"}
VALUE_LABELS = {"value": "值得", "fair": "合理", "risk": "规避"}


def _build_card(prediction: MatchPrediction) -> dict:
    match = prediction.match
    markets = derive_markets(
        prediction.score_matrix,
        prediction.final_probs,
        prediction.expected_home_goals,
        prediction.expected_away_goals,
        match.handicap,
    )
    top_label = prediction.top_scores[0].label if prediction.top_scores else "—"
    summary = plain_summary(
        match.home,
        match.away,
        prediction.final_probs,
        prediction.expected_home_goals,
        prediction.expected_away_goals,
        top_label,
        markets,
    )
    value = None
    if prediction.value:
        value = {
            "flag": prediction.value.flag,
            "flag_label": VALUE_LABELS.get(prediction.value.flag, prediction.value.flag),
            "pick_label": OUTCOME_LABELS[prediction.value.pick.value],
            "odds": prediction.value.odds,
            "expected_value": prediction.value.expected_value,
            "edge": prediction.value.edge,
        }
    odds = match.sporttery_odds
    official_markets = {
        market.code: {
            "code": market.code,
            "label": market.label,
            "line": market.line,
            "updated_at": market.updated_at,
            "outcomes": [
                {
                    "code": outcome.code,
                    "key": outcome.key,
                    "label": outcome.label,
                    "odds": outcome.odds,
                    "trend": outcome.trend,
                }
                for outcome in market.outcomes
            ],
        }
        for market in match.sporttery_markets
    }
    return {
        "match_no": match.match_no,
        "league": match.league,
        "home": match.home,
        "away": match.away,
        "kickoff": match.kickoff_at[11:16] if len(match.kickoff_at) >= 16 else match.kickoff_at,
        "handicap": match.handicap,
        "intel_tier": match.intel_tier,
        "odds": {"home": odds.home, "draw": odds.draw, "away": odds.away} if odds else None,
        "official_markets": official_markets,
        "official_market_count": len(official_markets),
        "final": prediction.final_probs,
        "model": prediction.model_probs,
        "market": prediction.market_probs,
        "recommended": prediction.recommended.value,
        "recommended_label": OUTCOME_LABELS[prediction.recommended.value],
        "confidence": prediction.confidence,
        "confidence_label": CONFIDENCE_LABELS.get(prediction.confidence, prediction.confidence),
        "value": value,
        "value_flag": value["flag"] if value else "fair",
        "xg_home": prediction.expected_home_goals,
        "xg_away": prediction.expected_away_goals,
        "top_scores": [{"label": score.label, "p": score.probability} for score in prediction.top_scores],
        "summary": summary,
        "markets": markets,
        "reasons": list(prediction.reasons),
        "warnings": list(prediction.warnings),
        "intel": prediction.intel,
    }


def render_report(report: DailyReport) -> str:
    template_dir = files("football_prediction.reporting").joinpath("templates")
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["pct"] = lambda value: f"{float(value):.1%}"
    environment.filters["pct0"] = lambda value: f"{float(value):.0%}"
    environment.filters["num"] = lambda value: f"{float(value):.2f}"
    environment.globals.update(outcome_labels=OUTCOME_LABELS, confidence_labels=CONFIDENCE_LABELS)

    cards = [_build_card(prediction) for prediction in report.predictions]
    picks = [
        card
        for card in cards
        if card["confidence"] == "high" or (card["value"] and card["value"]["flag"] == "value")
    ]
    leagues = sorted({card["league"] for card in cards})

    payload = to_dict(report)
    report_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    return environment.get_template("report.html").render(
        report=report,
        cards=cards,
        picks=picks,
        leagues=leagues,
        high_count=sum(1 for card in cards if card["confidence"] == "high"),
        value_count=sum(1 for card in cards if card["value"] and card["value"]["flag"] == "value"),
        report_json=report_json,
    )


def write_report(report: DailyReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(report), encoding="utf-8")
    return path
