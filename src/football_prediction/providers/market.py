"""实时市场赔率 Provider；付费源是可选插件，不影响免费主流程。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import ThreeWayOdds
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
            )
        except (KeyError, TypeError, ValueError):
            return None
