"""实时市场赔率 Provider；付费源是可选插件，不影响免费主流程。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import MarketRole, Match, ThreeWayOdds
from .base import ProviderError, fetch_json, with_query
from .names import name_key


class LocalMarketProvider:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def load(self) -> dict[str, ThreeWayOdds]:
        if not self.path:
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("matches", payload)
        return {
            self.key(row["home"], row["away"]): ThreeWayOdds(
                home=float(row["home_odds"]),
                draw=float(row["draw_odds"]),
                away=float(row["away_odds"]),
                source=row.get("source", "local-market"),
                updated_at=row.get("updated_at", ""),
                role=MarketRole(row.get("role", MarketRole.REFERENCE.value)),
            )
            for row in rows
        }

    @staticmethod
    def key(home: str, away: str) -> str:
        return f"{name_key(home)}::{name_key(away)}"


class TheOddsAPIProvider:
    URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"

    def __init__(self, api_key: str, timeout: float = 15) -> None:
        if not api_key:
            raise ValueError("The Odds API 需要 API Key")
        self.api_key = api_key
        self.timeout = timeout

    def fetch(self, sport: str) -> dict[str, ThreeWayOdds]:
        url = with_query(
            self.URL.format(sport=sport),
            {"apiKey": self.api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
        )
        payload = fetch_json(url, timeout=self.timeout, cache_ttl=20)
        if not isinstance(payload, list):
            raise ProviderError("The Odds API 响应不是比赛列表")
        result: dict[str, ThreeWayOdds] = {}
        for item in payload:
            market = self._pick_market(item)
            if market:
                result[LocalMarketProvider.key(item["home_team"], item["away_team"])] = market
        return result

    def fetch_for_matches(self, matches: list[Match]) -> tuple[dict[str, ThreeWayOdds], list[str]]:
        """按竞彩联赛映射批量抓取；未知联赛明确降级，不静默猜测。"""

        sport_keys = {
            "英超": "soccer_epl",
            "西甲": "soccer_spain_la_liga",
            "德甲": "soccer_germany_bundesliga",
            "意甲": "soccer_italy_serie_a",
            "法甲": "soccer_france_ligue_one",
            "欧冠": "soccer_uefa_champs_league",
            "欧联": "soccer_uefa_europa_league",
            "欧协联": "soccer_uefa_europa_conference_league",
            "中超": "soccer_china_superleague",
            "日职": "soccer_japan_j_league",
            "美职": "soccer_usa_mls",
        }
        requested: set[str] = set()
        warnings: list[str] = []
        for match in matches:
            sport = next((key for label, key in sport_keys.items() if label in match.league), None)
            if sport:
                requested.add(sport)
            else:
                warnings.append(f"{match.league} 未配置 The Odds API sport key，参考市场降级")
        result: dict[str, ThreeWayOdds] = {}
        for sport in sorted(requested):
            try:
                result.update(self.fetch(sport))
            except (ProviderError, OSError, ValueError) as exc:
                warnings.append(f"{sport} 参考市场获取失败：{exc}")
        return result, warnings

    @staticmethod
    def _pick_market(item: dict[str, Any]) -> ThreeWayOdds | None:
        bookmakers = item.get("bookmakers") or []
        preferred = next((book for book in bookmakers if book.get("key") == "pinnacle"), None)
        book = preferred or (bookmakers[0] if bookmakers else None)
        if not book:
            return None
        market = next((market for market in book.get("markets") or [] if market.get("key") == "h2h"), None)
        if not market:
            return None
        prices = {row["name"]: row["price"] for row in market.get("outcomes") or []}
        try:
            return ThreeWayOdds(
                home=float(prices[item["home_team"]]),
                draw=float(prices["Draw"]),
                away=float(prices[item["away_team"]]),
                source=f"the-odds-api:{book.get('key', 'unknown')}",
                updated_at=book.get("last_update", ""),
                role=MarketRole.REFERENCE,
            )
        except (KeyError, TypeError, ValueError):
            return None
