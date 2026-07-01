"""把结构化预测渲染成零网络依赖的单文件报告。"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..domain import DailyReport, MatchPrediction, TeamFeatures, to_dict
from ..modeling.odds import remove_vig
from .analysis import derive_markets, plain_summary
from .flags import flag_data_uri, flag_for

OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
CONFIDENCE_LABELS = {"high": "高", "mid": "中", "low": "低"}
VALUE_LABELS = {"value": "值得", "fair": "合理", "risk": "规避"}
SOURCE_LABELS = {
    "sporttery-official": "中国体育彩票官方接口",
    "sporttery-api": "SportteryAPI",
    "stale-cache": "历史缓存",
    "local-market": "本地市场快照",
    "fallback": "中性先验",
}


def _source_label(value: str | None) -> str:
    if not value:
        return "未提供"
    return SOURCE_LABELS.get(value, value.replace("the-odds-api:", "The Odds API · "))


def _timestamp(day: str, value: str | None) -> str:
    """把只有时分秒的竞彩时间补成可读日期，避免在界面里失去时间语境。"""

    if not value:
        return "未提供"
    normalized = value.replace("T", " ")
    return f"{day} {normalized}" if len(normalized) <= 8 else normalized


def _feature_payload(feature: TeamFeatures | None, fallback_team: str) -> dict:
    row = feature or TeamFeatures(fallback_team)
    available = row.source != "fallback" and any(
        value is not None for value in (row.elo, row.xg_for, row.xg_against)
    )
    return {
        "team": row.team,
        "available": available,
        "source": _source_label(row.source),
        "sample_size": row.sample_size,
        "elo": row.elo,
        "xg_for": row.xg_for,
        "xg_against": row.xg_against,
    }


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
    official_probs = remove_vig(odds) if odds else None
    external_odds = prediction.reference_market_odds
    home_features = _feature_payload(prediction.home_features, match.home)
    away_features = _feature_payload(prediction.away_features, match.away)
    feature_available = home_features["available"] and away_features["available"]
    intel_evidence_count = len(prediction.intel.evidences) if prediction.intel else 0
    intel_completeness = prediction.intel.completeness if prediction.intel else 0.0
    official_update = _timestamp(match.business_date, odds.updated_at if odds else None)
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
    layers = [
        {
            "code": "fixture",
            "label": "官方赛程",
            "available": bool(match.source_url),
            "source": "中国体育彩票公开接口" if match.source_url else "未提供",
            "updated_at": match.business_date,
            "note": "比赛编号、对阵与开赛时间",
        },
        {
            "code": "sporttery",
            "label": "官方 SP",
            "available": odds is not None,
            "source": _source_label(odds.source if odds else None),
            "updated_at": official_update,
            "note": f"已获取 {len(official_markets)}/5 类竞彩玩法",
        },
        {
            "code": "features",
            "label": "实力特征",
            "available": feature_available,
            "source": home_features["source"] if feature_available else "中性先验",
            "updated_at": "快照未提供" if not feature_available else "随输入快照",
            "note": "Elo / xG" if feature_available else "未注入国家队 Elo / xG 快照",
        },
        {
            "code": "market",
            "label": "外部市场",
            "available": external_odds is not None,
            "source": _source_label(external_odds.source if external_odds else None),
            "updated_at": _timestamp(match.business_date, external_odds.updated_at if external_odds else None),
            "note": "锐角市场去水概率" if external_odds else "未提供同一预测时点的外部赔率",
        },
        {
            "code": "intel",
            "label": "赛前情报",
            "available": intel_evidence_count > 0,
            "source": f"{intel_evidence_count} 条可核验证据" if intel_evidence_count else "未提供",
            "updated_at": f"完整度 {intel_completeness:.0%}",
            "note": "只纳入开赛前发布的有来源信息",
        },
    ]
    coverage_count = sum(layer["available"] for layer in layers)
    is_demo = match.id.startswith("demo-") or bool(odds and odds.source == "demo")
    probability_delta = (
        {
            key: prediction.final_probs.get(key) - official_probs.get(key)
            for key in ("home", "draw", "away")
        }
        if official_probs
        else None
    )
    return {
        "match_no": match.match_no,
        "league": match.league,
        "home": match.home,
        "away": match.away,
        "home_flag": flag_for(match.home),
        "away_flag": flag_for(match.away),
        "kickoff": match.kickoff_at[11:16] if len(match.kickoff_at) >= 16 else match.kickoff_at,
        "kickoff_full": match.kickoff_at.replace("T", " "),
        "handicap": match.handicap,
        "intel_tier": match.intel_tier,
        "odds": {"home": odds.home, "draw": odds.draw, "away": odds.away} if odds else None,
        "official_probs": official_probs,
        "official_update": official_update,
        "official_source": _source_label(odds.source if odds else None),
        "source_url": match.source_url,
        "official_markets": official_markets,
        "official_market_count": len(official_markets),
        "final": prediction.final_probs,
        "model": prediction.model_probs,
        "market": prediction.market_probs,
        "probability_delta": probability_delta,
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
        "intel_evidence_count": intel_evidence_count,
        "intel_completeness": intel_completeness,
        "intel_missing": list(prediction.intel.missing) if prediction.intel else ["未提供赛前情报"],
        "home_features": home_features,
        "away_features": away_features,
        "data_layers": layers,
        "coverage_count": coverage_count,
        "coverage_pct": coverage_count / len(layers),
        "is_degraded": coverage_count < len(layers) or bool(prediction.warnings),
        "data_status_label": "数据完整" if coverage_count == len(layers) else f"{len(layers) - coverage_count} 层降级",
        "is_demo": is_demo,
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

    # 只为本报告实际用到的国旗内联一次 data-URI（每面旗一条 CSS 规则，避免重复膨胀）。
    used_flag_codes = sorted(
        {code for card in cards for code in (card["home_flag"], card["away_flag"]) if code}
    )
    flag_styles = [(code, flag_data_uri(code)) for code in used_flag_codes]

    payload = to_dict(report)
    report_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    return environment.get_template("report.html").render(
        report=report,
        cards=cards,
        picks=picks,
        leagues=leagues,
        flag_styles=flag_styles,
        high_count=sum(1 for card in cards if card["confidence"] == "high"),
        value_count=sum(1 for card in cards if card["value"] and card["value"]["flag"] == "value"),
        official_sp_count=sum(1 for card in cards if card["odds"]),
        intel_evidence_count=sum(card["intel_evidence_count"] for card in cards),
        degraded_count=sum(1 for card in cards if card["is_degraded"]),
        average_coverage=(sum(card["coverage_pct"] for card in cards) / len(cards)) if cards else 0,
        demo_count=sum(1 for card in cards if card["is_demo"]),
        report_json=report_json,
    )


def write_report(report: DailyReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(report), encoding="utf-8")
    return path
