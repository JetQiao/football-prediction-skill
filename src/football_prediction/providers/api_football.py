"""API-Football 伤病数据适配器。"""

from __future__ import annotations

from typing import Any

from .base import ProviderError, fetch_json, with_query


class APIFootballProvider:
    URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str, timeout: float = 15) -> None:
        if not api_key:
            raise ValueError("API-Football 需要 API Key")
        self.api_key = api_key
        self.timeout = timeout

    def injuries(self, fixture_id: int) -> list[dict[str, Any]]:
        payload = fetch_json(
            with_query(f"{self.URL}/injuries", {"fixture": fixture_id}),
            timeout=self.timeout,
            headers={"x-apisports-key": self.api_key},
            cache_ttl=300,
        )
        rows = payload.get("response")
        if not isinstance(rows, list):
            raise ProviderError("API-Football 响应缺少 response")
        return [
            {
                "player": (row.get("player") or {}).get("name", ""),
                "team": (row.get("team") or {}).get("name", ""),
                "type": (row.get("player") or {}).get("type", ""),
                "reason": (row.get("player") or {}).get("reason", ""),
                "source": "api-football",
            }
            for row in rows
        ]
