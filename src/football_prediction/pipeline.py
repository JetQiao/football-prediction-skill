"""每日预测端到端编排。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .config import Settings
from .domain import (
    BettingMarketOdds,
    DailyReport,
    MarketOutcomeOdds,
    MarketRole,
    Match,
    MatchIntel,
    TeamFeatures,
    ThreeWayOdds,
    to_dict,
)
from .intelligence import load_intel
from .prediction import PredictionContext, PredictionPipeline
from .providers.api_football import APIFootballProvider
from .providers.base import ProviderError
from .providers.features import ClubEloProvider, LocalFeatureProvider
from .providers.market import LocalMarketProvider, TheOddsAPIProvider
from .providers.names import name_key
from .providers.sporttery import SportteryProvider
from .reporting import write_report
from .snapshots import SnapshotEnvelope, SnapshotStore, parse_as_of, parse_timestamp
from .snapshots.contracts import canonical_payload_hash
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
        as_of: str | None = None,
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
            raise ValueError(f"{business_date.isoformat()} 没有获取到竞彩赛程")
        cutoff_dt = self._resolve_cutoff(as_of, match_list)
        cutoff = cutoff_dt.isoformat(timespec="seconds")
        prediction_matches = [
            match
            for match in match_list
            if cutoff_dt < parse_timestamp(match.kickoff_at, business_date=match.business_date)
        ]
        skipped_started = len(match_list) - len(prediction_matches)
        if skipped_started:
            warnings.append(f"{skipped_started} 场在预测截点前已开赛，已保留原始快照但不生成赛前预测")
        if not prediction_matches:
            raise ValueError("预测截点之后没有尚未开赛的比赛")

        feature_map = LocalFeatureProvider(features_file).load()
        market_map = LocalMarketProvider(market_file).load()
        intel_map = load_intel(intel_file) if intel_file else {}
        if (
            not feature_map
            and self.settings.auto_clubelo
            and not all(match.id.startswith("demo-") for match in prediction_matches)
        ):
            try:
                ratings = ClubEloProvider(timeout=self.settings.request_timeout).fetch(cutoff_dt.date())
                required_names = {
                    name_key(team)
                    for match in prediction_matches
                    for team in (match.home, match.away)
                }
                feature_map = {key: value for key, value in ratings.items() if key in required_names}
                if feature_map:
                    sources.append("ClubElo 自动赛前快照")
                    missing = len(required_names - set(feature_map))
                    if missing:
                        warnings.append(f"ClubElo 仅匹配到 {len(feature_map)} 支球队，另有 {missing} 支降级")
            except (ProviderError, RuntimeError, OSError, ValueError) as exc:
                warnings.append(f"ClubElo 自动增强失败：{exc}")

        if self.settings.api_football_key:
            now = datetime.now().astimezone()
            if abs((now - cutoff_dt).total_seconds()) <= 86_400:
                api_intel, api_warnings = APIFootballProvider(
                    self.settings.api_football_key,
                    timeout=self.settings.request_timeout,
                ).fetch_for_matches(prediction_matches, as_of=cutoff)
                warnings.extend(api_warnings)
                for match_id, current in api_intel.items():
                    intel_map[match_id] = self._merge_intel(intel_map.get(match_id), current)
                if api_intel:
                    sources.append("API-Football 结构化阵容事实")
            else:
                warnings.append("历史/远期截点不调用实时 API-Football，避免事件时间泄漏")
        if feature_map:
            sources.append("本地 xG / Elo 特征快照")
        else:
            warnings.append("未提供球队特征快照，统计层使用联赛基线与中性先验")
        if market_map:
            sources.append("用户提供的赛前市场赔率快照")
        elif self.settings.odds_api_key:
            market_map, market_warnings = TheOddsAPIProvider(
                self.settings.odds_api_key,
                timeout=self.settings.request_timeout,
            ).fetch_for_matches(match_list)
            warnings.extend(market_warnings)
            if market_map:
                sources.append("The Odds API 独立参考市场")
            else:
                warnings.append("已配置外部市场 Key，但没有匹配到同一预测截点的比赛")
        else:
            warnings.append("未提供实时锐角赔率，已进入免费降级模式")
        if intel_map:
            sources.append("智能体联网检索的有来源赛前情报")

        snapshot_payload = {
            "matches": [to_dict(match) for match in match_list],
            "meta": {
                "source_match_count": len(match_list),
                "parsed_match_count": len(match_list),
                "as_of": cutoff,
            },
        }
        store = SnapshotStore(self.settings.paths.snapshots)
        snapshot = SnapshotEnvelope(
            dataset="sporttery-fixtures",
            business_date=business_date.isoformat(),
            as_of=cutoff,
            observed_at=cutoff,
            source=sources[0],
            source_event_id=f"{business_date.isoformat()}-{len(match_list)}",
            payload=snapshot_payload,
        )
        parquet_snapshot, json_snapshot = store.write(snapshot)
        snapshot_records = {
            "fixtures": {
                "snapshot_id": snapshot.snapshot_id,
                "payload_hash": snapshot.payload_hash,
                "parquet": str(parquet_snapshot),
                "json": str(json_snapshot),
            }
        }
        sources.append("本地 DuckDB/Parquet 不可变赛前快照")

        optional_snapshots = (
            (
                "team-features",
                "local-features",
                [to_dict(feature) for feature in feature_map.values()],
            ),
            (
                "reference-markets",
                "local-or-api-market",
                [
                    {"match_key": key, "odds": to_dict(odds)}
                    for key, odds in market_map.items()
                ],
            ),
            (
                "prematch-intelligence",
                "sourced-intelligence",
                [to_dict(item) for item in intel_map.values()],
            ),
        )
        for dataset, source, payload in optional_snapshots:
            if not payload:
                continue
            envelope = SnapshotEnvelope(
                dataset=dataset,
                business_date=business_date.isoformat(),
                as_of=cutoff,
                observed_at=cutoff,
                source=source,
                source_event_id=f"{business_date.isoformat()}-{dataset}-{len(payload)}",
                payload=payload,
            )
            parquet_path, envelope_path = store.write(envelope)
            snapshot_records[dataset] = {
                "snapshot_id": envelope.snapshot_id,
                "payload_hash": envelope.payload_hash,
                "parquet": str(parquet_path),
                "json": str(envelope_path),
            }

        prediction_pipeline = PredictionPipeline(self.settings)
        predictions = []
        for match in prediction_matches:
            home = feature_map.get(name_key(match.home), TeamFeatures(match.home))
            away = feature_map.get(name_key(match.away), TeamFeatures(match.away))
            market = market_map.get(LocalMarketProvider.key(match.home, match.away))
            intel = intel_map.get(match.id)
            predictions.append(
                prediction_pipeline.predict(
                    PredictionContext(
                        match=match,
                        home_features=home,
                        away_features=away,
                        reference_market_odds=market,
                        target_market_odds=match.sporttery_odds,
                        intel=intel,
                        as_of=cutoff,
                        use_target_market_as_signal=False,
                    )
                )
            )

        generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        model_versions = sorted({row.model_version for row in predictions})
        calibration_statuses = sorted({row.calibration_status for row in predictions})
        trained_until_values = sorted(
            {row.model_trained_until for row in predictions if row.model_trained_until}
        )
        run_id = canonical_payload_hash(
            {
                "business_date": business_date.isoformat(),
                "as_of": cutoff,
                "snapshot_ids": sorted(item["snapshot_id"] for item in snapshot_records.values()),
                "models": model_versions,
                "settings": {
                    "market_weight": self.settings.market_weight,
                    "official_market_weight": self.settings.official_market_weight,
                    "value_threshold": self.settings.value_threshold,
                    "max_intel_logit": self.settings.max_intel_logit,
                },
            }
        )
        report = DailyReport(
            business_date=business_date.isoformat(),
            generated_at=generated_at,
            predictions=tuple(predictions),
            sources=tuple(sources),
            warnings=tuple(warnings),
            run_id=run_id,
            as_of=cutoff,
            model_version=model_versions[0] if len(model_versions) == 1 else f"mixed:{len(model_versions)}",
            model_trained_until=trained_until_values[-1] if trained_until_values else None,
            calibration_status=(
                calibration_statuses[0] if len(calibration_statuses) == 1 else "mixed"
            ),
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
                "match_count": len(predictions),
                "source_match_count": len(match_list),
                "sources": sources,
                "warnings": warnings,
                "parameters": {
                    "market_weight": self.settings.market_weight,
                    "official_market_weight": self.settings.official_market_weight,
                    "value_threshold": self.settings.value_threshold,
                    "max_intel_logit": self.settings.max_intel_logit,
                },
                "as_of": cutoff,
                "schema_version": report.schema_version,
                "model_versions": model_versions,
                "calibration_statuses": calibration_statuses,
                "decision_counts": {
                    state: sum(str(row.decision_state) == state or getattr(row.decision_state, "value", None) == state for row in predictions)
                    for state in ("candidate", "lean", "no_edge", "abstain")
                },
                "snapshots": snapshot_records,
                "artifacts": {"json": str(json_path), "html": str(html_path)},
            },
        )
        return report, json_path, html_path

    @staticmethod
    def _resolve_cutoff(as_of: str | None, matches: list[Match]) -> datetime:
        if as_of:
            return parse_as_of(as_of)
        now = parse_as_of(None)
        kickoffs = [
            parse_timestamp(match.kickoff_at, business_date=match.business_date)
            for match in matches
        ]
        if kickoffs and max(kickoffs) <= now:
            # 对历史赛单使用统一的安全赛前截点，避免默认“当前时间”落在赛后。
            return min(kickoffs) - timedelta(minutes=90)
        return now

    @staticmethod
    def _merge_intel(left: MatchIntel | None, right: MatchIntel) -> MatchIntel:
        if left is None:
            return right
        evidences = {f"{item.url}|{item.title}": item for item in (*left.evidences, *right.evidences)}
        facts = {
            item.event_fingerprint: item
            for item in (*left.facts, *right.facts)
        }
        return MatchIntel(
            match_id=left.match_id,
            evidences=tuple(evidences.values()),
            facts=tuple(facts.values()),
            completeness=max(left.completeness, right.completeness),
            missing=tuple(dict.fromkeys((*left.missing, *right.missing))),
        )

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
                MarketRole(raw_odds.get("role", MarketRole.TARGET.value)),
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
                role=MarketRole(market.get("role", MarketRole.TARGET.value)),
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
                match_status=row.get("match_status", ""),
                sale_status=row.get("sale_status"),
                competition_id=row.get("competition_id"),
                home_team_id=row.get("home_team_id"),
                away_team_id=row.get("away_team_id"),
                season_id=row.get("season_id"),
                provider_fixture_id=(
                    int(row["provider_fixture_id"])
                    if row.get("provider_fixture_id") is not None
                    else None
                ),
            )
        )
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    source_count = meta.get("source_match_count")
    if source_count is not None and int(source_count) != len(result):
        raise ValueError(f"赛单快照声明 {source_count} 场，但文件内仅有 {len(result)} 场")
    return result
