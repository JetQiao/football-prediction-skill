"""SportteryAPI 与官方竞彩接口适配器。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..domain import Match, ThreeWayOdds
from .base import ProviderError, fetch_json, with_query

OFFICIAL_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _iso_date(value: str) -> str:
    value = value.strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def _kickoff(day: str, clock: str) -> str:
    day = _iso_date(day)
    value = f"{day}T{clock or '00:00:00'}"
    return value if len(value) > 10 else f"{day}T00:00:00"


class SportteryProvider:
    """优先调用 SportteryAPI；未配置时在本地网络直连官方上游。"""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 15,
        cache_dir: Path | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/") if api_url else None
        self.api_key = api_key
        self.timeout = timeout
        self.cache_dir = cache_dir
        self.warnings: list[str] = []
        self.active_source = "sporttery-api" if api_url else "sporttery-official"

    def fetch_matches(self, business_date: date) -> list[Match]:
        if self.api_url:
            try:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                payload = fetch_json(
                    with_query(f"{self.api_url}/api/matches", {"pools": "had,hhad"}),
                    timeout=self.timeout,
                    headers=headers,
                    cache_dir=self.cache_dir,
                )
                self.active_source = "sporttery-api"
                return self.parse_sporttery_api(payload, business_date.isoformat())
            except ProviderError as exc:
                self.warnings.append(f"SportteryAPI 不可用，尝试官方接口：{exc}")

        try:
            payload = fetch_json(
                with_query(OFFICIAL_URL, {"poolCode": "had,hhad,crs,ttg,hafu", "channel": "c"}),
                timeout=self.timeout,
                headers={"Referer": "https://m.sporttery.cn/", "Accept-Language": "zh-CN,zh;q=0.9"},
                cache_dir=self.cache_dir,
            )
            self.active_source = "sporttery-official"
            return self.parse_official(payload, business_date.isoformat())
        except ProviderError as exc:
            cached = self._latest_cache()
            if cached is not None:
                self.active_source = "stale-cache"
                self.warnings.append(f"实时竞彩源不可用，使用最近缓存：{exc}")
                if "value" in cached:
                    return self.parse_official(cached, business_date.isoformat())
                return self.parse_sporttery_api(cached, business_date.isoformat())
            message = str(exc)
            if "567" in message:
                message += "；上游存在地域限制，请本地运行 SportteryAPI 并设置 SPORTTERY_API_URL，或配置可达代理"
            raise ProviderError(message) from exc

    def _latest_cache(self) -> dict[str, Any] | None:
        if not self.cache_dir or not self.cache_dir.exists():
            return None
        for path in sorted(self.cache_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and ("value" in payload or "data" in payload or "matches" in payload):
                    return payload
            except (OSError, ValueError):
                continue
        return None

    @staticmethod
    def parse_sporttery_api(payload: dict[str, Any], business_date: str) -> list[Match]:
        data = payload.get("data", payload)
        raw_matches = data.get("matches")
        if not isinstance(raw_matches, list):
            raise ProviderError("SportteryAPI 响应缺少 data.matches")

        result: list[Match] = []
        for item in raw_matches:
            item_date = _iso_date(_text(item.get("businessDate") or item.get("matchNumDate")))
            if item_date and item_date != business_date:
                continue
            market = (item.get("markets") or {}).get("had") or {}
            odds = SportteryProvider._normalized_had(market)
            if odds is None:
                continue
            result.append(
                Match(
                    id=_text(item.get("matchId")),
                    business_date=business_date,
                    match_no=_text(item.get("matchNumStr")),
                    league=_text((item.get("league") or {}).get("abbName")),
                    home=_text((item.get("home") or {}).get("abbName")),
                    away=_text((item.get("away") or {}).get("abbName")),
                    kickoff_at=_kickoff(_text(item.get("matchDate")) or business_date, _text(item.get("matchTime"))),
                    sporttery_odds=odds,
                    handicap=((item.get("markets") or {}).get("hhad") or {}).get("goalLine"),
                    source_url="https://webapi.sporttery.cn/",
                )
            )
        return result

    @staticmethod
    def parse_official(payload: dict[str, Any], business_date: str) -> list[Match]:
        groups = (payload.get("value") or {}).get("matchInfoList")
        if not isinstance(groups, list):
            raise ProviderError("竞彩官方响应缺少 value.matchInfoList，接口契约可能已变化")

        result: list[Match] = []
        for group in groups:
            group_date = _iso_date(_text(group.get("businessDate") or group.get("matchNumDate")))
            for item in group.get("subMatchList") or []:
                item_date = _iso_date(
                    _text(item.get("businessDate") or group.get("businessDate") or group.get("matchNumDate"))
                )
                if item_date != business_date and group_date != business_date:
                    continue
                had = item.get("had") or {}
                try:
                    odds = ThreeWayOdds(
                        home=float(had["h"]),
                        draw=float(had["d"]),
                        away=float(had["a"]),
                        source="sporttery-official",
                        updated_at=_text(had.get("updateTime") or (payload.get("value") or {}).get("lastUpdateTime")),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                hhad = item.get("hhad") or {}
                handicap = hhad.get("goalLineValue")
                result.append(
                    Match(
                        id=_text(item.get("matchId")),
                        business_date=business_date,
                        match_no=_text(item.get("matchNumStr")),
                        league=_text(item.get("leagueAbbName") or item.get("leagueAllName")),
                        home=_text(item.get("homeTeamAbbName") or item.get("homeTeamAllName")),
                        away=_text(item.get("awayTeamAbbName") or item.get("awayTeamAllName")),
                        kickoff_at=_kickoff(
                            _text(item.get("matchDate")) or business_date, _text(item.get("matchTime"))
                        ),
                        sporttery_odds=odds,
                        handicap=float(handicap) if handicap not in (None, "") else None,
                        source_url=OFFICIAL_URL,
                    )
                )
        return result

    @staticmethod
    def _normalized_had(market: dict[str, Any]) -> ThreeWayOdds | None:
        by_key = {item.get("key"): item for item in market.get("outcomes") or []}
        try:
            return ThreeWayOdds(
                home=float(by_key["home"]["odds"]),
                draw=float(by_key["draw"]["odds"]),
                away=float(by_key["away"]["odds"]),
                source="sporttery-api",
                updated_at=_text(market.get("updateTime")),
            )
        except (KeyError, TypeError, ValueError):
            return None
