"""每日预测端到端编排。"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import Settings
from .domain import BettingMarketOdds, DailyReport, MarketOutcomeOdds, Match, TeamFeatures, ThreeWayOdds
from .intelligence import load_intel
from .modeling import PredictionEngine
from .providers.features import LocalFeatureProvider
from .providers.market import LocalMarketProvider
from .providers.names import name_key
from .providers.sporttery import SportteryProvider
from .reporting import write_report
from .storage import read_json, write_json

POPULAR_LEAGUES = ("世界杯", "欧洲杯", "欧冠", "英超", "西甲", "德甲", "意甲", "法甲", "中超")


class DailyPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings.validate()

    def run(
        self,
        business_date: date,
        *,
        matches: Iterable[Match] | None = None,
        features_file: Path | None = None,
        market_file: Path | None = None,
        intel_file: Path | None = None,
        output_dir: Path | None = None,
    ) -> tuple[DailyReport, Path, Path]:
        warnings: list[str] = []
        sources = ["SportteryAPI / 中国体育彩票公开接口"]
        if matches is None:
            provider = SportteryProvider(
                api_url=self.settings.sporttery_api_url,
                api_key=self.settings.sporttery_api_key,
                timeout=self.settings.request_timeout,
                cache_dir=self.settings.paths.cache / "sporttery",
            )
            matches = provider.fetch_matches(business_date)
            warnings.extend(provider.warnings)
            sources[0] = provider.active_source
        match_list = self._assign_tiers(list(matches))
        if not match_list:
            raise ValueError(f"{business_date.isoformat()} 没有可预测的竞彩胜平负场次")

        feature_map = LocalFeatureProvider(features_file).load()
        market_map = LocalMarketProvider(market_file).load()
        intel_map = load_intel(intel_file) if intel_file else {}
        if feature_map:
            sources.append("本地 xG / Elo 特征快照")
        else:
            warnings.append("未提供球队特征快照，统计层使用联赛基线与中性先验")
        if market_map:
            sources.append("用户提供的赛前市场赔率快照")
        else:
            warnings.append("未提供实时锐角赔率，已进入免费降级模式")
        if intel_map:
            sources.append("智能体联网检索的有来源赛前情报")

        engine = PredictionEngine(self.settings)
        predictions = []
        for match in match_list:
            home = feature_map.get(name_key(match.home), TeamFeatures(match.home))
            away = feature_map.get(name_key(match.away), TeamFeatures(match.away))
            market = market_map.get(LocalMarketProvider.key(match.home, match.away))
            intel = intel_map.get(match.id)
            predictions.append(engine.predict(match, home, away, market_odds=market, intel=intel))

        generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        run_seed = f"{business_date.isoformat()}|{generated_at}|{'|'.join(match.id for match in match_list)}"
        run_id = hashlib.sha256(run_seed.encode("utf-8")).hexdigest()
        report = DailyReport(
            business_date=business_date.isoformat(),
            generated_at=generated_at,
            predictions=tuple(predictions),
            sources=tuple(sources),
            warnings=tuple(warnings),
            run_id=run_id,
        )
        target = output_dir or self.settings.paths.reports / business_date.isoformat()
        target.mkdir(parents=True, exist_ok=True)
        json_path = write_json(target / f"prediction_{business_date.isoformat()}.json", report)
        html_path = write_report(report, target / f"report_{business_date.isoformat()}.html")
        write_json(
            target / f"manifest_{run_id[:12]}.json",
            {
                "run_id": run_id,
                "business_date": business_date.isoformat(),
                "generated_at": generated_at,
                "match_count": len(match_list),
                "sources": sources,
                "warnings": warnings,
                "parameters": {
                    "market_weight": self.settings.market_weight,
                    "value_threshold": self.settings.value_threshold,
                    "max_intel_logit": self.settings.max_intel_logit,
                },
                "artifacts": {"json": str(json_path), "html": str(html_path)},
            },
        )
        return report, json_path, html_path

    @staticmethod
    def _assign_tiers(matches: list[Match]) -> list[Match]:
        result = []
        for match in matches:
            tier = "A" if any(league in match.league for league in POPULAR_LEAGUES) else match.intel_tier
            result.append(replace(match, intel_tier=tier))
        return result


def load_matches(path: Path, business_date: date) -> list[Match]:
    payload = read_json(path)
    # 允许直接使用 SportteryAPI 或竞彩官方原始响应作为离线输入。
    provider = SportteryProvider()
    if isinstance(payload, dict) and ("data" in payload or "matches" in payload):
        try:
            parsed = provider.parse_sporttery_api(payload, business_date.isoformat())
            if parsed:
                return parsed
        except Exception:
            pass
    if isinstance(payload, dict) and "value" in payload:
        return provider.parse_official(payload, business_date.isoformat())
    rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
    result: list[Match] = []
    for row in rows:
        raw_odds = row.get("sporttery_odds")
        odds = None
        if raw_odds:
            odds = ThreeWayOdds(
                float(raw_odds["home"]),
                float(raw_odds["draw"]),
                float(raw_odds["away"]),
                raw_odds.get("source", "input-json"),
                raw_odds.get("updated_at", ""),
            )
        markets = tuple(
            BettingMarketOdds(
                code=market["code"],
                label=market.get("label", market["code"]),
                outcomes=tuple(
                    MarketOutcomeOdds(
                        code=outcome.get("code", outcome["key"]),
                        key=outcome["key"],
                        label=outcome.get("label", outcome["key"]),
                        odds=float(outcome["odds"]),
                        trend=outcome.get("trend", "unknown"),
                    )
                    for outcome in market.get("outcomes", [])
                ),
                updated_at=market.get("updated_at", ""),
                line=market.get("line"),
            )
            for market in row.get("sporttery_markets", [])
        )
        result.append(
            Match(
                id=str(row["id"]),
                business_date=row.get("business_date", business_date.isoformat()),
                match_no=row.get("match_no", str(row["id"])),
                league=row["league"],
                home=row["home"],
                away=row["away"],
                kickoff_at=row["kickoff_at"],
                sale_close_at=row.get("sale_close_at"),
                sporttery_odds=odds,
                sporttery_markets=markets,
                handicap=row.get("handicap"),
                intel_tier=row.get("intel_tier", "B"),
                stage=row.get("stage", "league"),
                source_url=row.get("source_url"),
            )
        )
    return result
