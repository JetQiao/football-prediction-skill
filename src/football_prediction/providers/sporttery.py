"""SportteryAPI 与官方竞彩接口适配器。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..domain import BettingMarketOdds, MarketOutcomeOdds, Match, ThreeWayOdds
from .base import ProviderError, fetch_json, with_query

OFFICIAL_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
POOL_CODES = ("had", "hhad", "crs", "ttg", "hafu")
POOL_LABELS = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "crs": "比分",
    "ttg": "总进球",
    "hafu": "半全场",
}
CANONICAL_CODES = {
    "had": ("h", "d", "a"),
    "hhad": ("h", "d", "a"),
    "crs": (
        "s01s00", "s02s00", "s02s01", "s03s00", "s03s01", "s03s02",
        "s04s00", "s04s01", "s04s02", "s05s00", "s05s01", "s05s02", "s1sh",
        "s00s00", "s01s01", "s02s02", "s03s03", "s1sd",
        "s00s01", "s00s02", "s01s02", "s00s03", "s01s03", "s02s03",
        "s00s04", "s01s04", "s02s04", "s00s05", "s01s05", "s02s05", "s1sa",
    ),
    "ttg": ("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"),
    "hafu": ("hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa"),
}
META_KEYS = {"goalLine", "goalLineValue", "updateDate", "updateTime", "id"}


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


def _decode_outcome(pool: str, code: str) -> tuple[str, str]:
    if pool in ("had", "hhad"):
        return {
            "h": ("home", "主胜"),
            "d": ("draw", "平"),
            "a": ("away", "客胜"),
        }.get(code, (code, code))
    if pool == "crs":
        if code.startswith("s") and "s" in code[1:]:
            parts = code[1:].split("s", 1)
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                home, away = int(parts[0]), int(parts[1])
                return f"{home}:{away}", f"{home}:{away}"
        return {
            "s1sh": ("win-other", "胜其它"),
            "s1sd": ("draw-other", "平其它"),
            "s1sa": ("loss-other", "负其它"),
        }.get(code, (code, code))
    if pool == "ttg" and len(code) == 2 and code[0] == "s" and code[1].isdigit():
        value = int(code[1])
        return ("7+", "7球+") if value >= 7 else (str(value), f"{value}球")
    if pool == "hafu" and len(code) == 2:
        labels = {"h": "胜", "d": "平", "a": "负"}
        if code[0] in labels and code[1] in labels:
            return code.upper(), f"{labels[code[0]]}/{labels[code[1]]}"
    return code, code


def _trend(value: Any) -> str:
    return {"1": "up", "0": "flat", "-1": "down"}.get(_text(value), "unknown")


def _official_market(pool: str, raw: dict[str, Any], updated_at: str) -> BettingMarketOdds | None:
    present = [
        key for key in raw
        if key not in META_KEYS and not key.endswith("f")
    ]
    canonical = list(CANONICAL_CODES.get(pool, ()))
    codes = [code for code in canonical if code in present] + [code for code in present if code not in canonical]
    outcomes: list[MarketOutcomeOdds] = []
    for code in codes:
        try:
            odds = float(raw[code])
            if odds <= 1:
                continue
        except (TypeError, ValueError):
            continue
        key, label = _decode_outcome(pool, code)
        outcomes.append(MarketOutcomeOdds(code, key, label, odds, _trend(raw.get(f"{code}f"))))
    if not outcomes:
        return None
    raw_line = raw.get("goalLineValue", raw.get("goalLine"))
    try:
        line = float(raw_line) if raw_line not in (None, "") else None
    except (TypeError, ValueError):
        line = None
    return BettingMarketOdds(
        code=pool,
        label=POOL_LABELS[pool],
        outcomes=tuple(outcomes),
        updated_at=_text(raw.get("updateTime") or updated_at),
        line=line,
    )


def _api_market(pool: str, raw: dict[str, Any]) -> BettingMarketOdds | None:
    outcomes: list[MarketOutcomeOdds] = []
    for item in raw.get("outcomes") or []:
        try:
            odds = float(item["odds"])
            if odds <= 1:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        code = _text(item.get("code") or item.get("key"))
        decoded_key, decoded_label = _decode_outcome(pool, code)
        key = _text(item.get("key")) or decoded_key
        label = _text(item.get("labelZh")) or decoded_label
        outcomes.append(MarketOutcomeOdds(code, key, label, odds, _text(item.get("trend")) or "unknown"))
    if not outcomes:
        return None
    raw_line = raw.get("goalLine")
    try:
        line = float(raw_line) if raw_line not in (None, "") else None
    except (TypeError, ValueError):
        line = None
    return BettingMarketOdds(
        code=pool,
        label=_text(raw.get("poolNameZh")) or POOL_LABELS[pool],
        outcomes=tuple(outcomes),
        updated_at=_text(raw.get("updateTime")),
        line=line,
    )


def _had_odds(market: BettingMarketOdds | None, source: str) -> ThreeWayOdds | None:
    if market is None:
        return None
    home, draw, away = market.get("home"), market.get("draw"), market.get("away")
    if not all((home, draw, away)):
        return None
    return ThreeWayOdds(home.odds, draw.odds, away.odds, source, market.updated_at)


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
                    with_query(f"{self.api_url}/api/matches", {"pools": ",".join(POOL_CODES)}),
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
            raw_markets = item.get("markets") or {}
            markets = tuple(
                market
                for pool in POOL_CODES
                if (market := _api_market(pool, raw_markets.get(pool) or {})) is not None
            )
            had_market = next((market for market in markets if market.code == "had"), None)
            odds = _had_odds(had_market, "sporttery-api")
            if odds is None:
                continue
            hhad_market = next((market for market in markets if market.code == "hhad"), None)
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
                    sporttery_markets=markets,
                    handicap=hhad_market.line if hhad_market else None,
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
                updated_at = _text((payload.get("value") or {}).get("lastUpdateTime"))
                markets = tuple(
                    market
                    for pool in POOL_CODES
                    if (market := _official_market(pool, item.get(pool) or {}, updated_at)) is not None
                )
                had_market = next((market for market in markets if market.code == "had"), None)
                odds = _had_odds(had_market, "sporttery-official")
                if odds is None:
                    continue
                hhad_market = next((market for market in markets if market.code == "hhad"), None)
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
                        sporttery_markets=markets,
                        handicap=hhad_market.line if hhad_market else None,
                        source_url=OFFICIAL_URL,
                    )
                )
        return result
