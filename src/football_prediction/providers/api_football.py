"""API-Football 伤病数据适配器。"""

from __future__ import annotations

from typing import Any, Iterable

from ..domain import AvailabilityFact, Match, MatchIntel
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
                "player_id": (row.get("player") or {}).get("id"),
                "team": (row.get("team") or {}).get("name", ""),
                "team_id": (row.get("team") or {}).get("id"),
                "type": (row.get("player") or {}).get("type", ""),
                "reason": (row.get("player") or {}).get("reason", ""),
                "source": "api-football",
            }
            for row in rows
        ]

    def fixture_teams(self, fixture_id: int) -> tuple[int | None, int | None]:
        payload = fetch_json(
            with_query(f"{self.URL}/fixtures", {"id": fixture_id}),
            timeout=self.timeout,
            headers={"x-apisports-key": self.api_key},
            cache_ttl=300,
        )
        rows = payload.get("response")
        if not isinstance(rows, list) or not rows:
            raise ProviderError(f"API-Football 未找到 fixture {fixture_id}")
        teams = rows[0].get("teams") or {}
        return (teams.get("home") or {}).get("id"), (teams.get("away") or {}).get("id")

    def intelligence(self, match: Match, *, as_of: str) -> MatchIntel:
        if match.provider_fixture_id is None:
            raise ValueError(f"{match.match_no} 缺少 API-Football fixture ID")
        fixture_id = int(match.provider_fixture_id)
        home_id, away_id = self.fixture_teams(fixture_id)
        rows = self.injuries(fixture_id)
        facts: list[AvailabilityFact] = []
        source_url = with_query(f"{self.URL}/injuries", {"fixture": fixture_id})
        for row in rows:
            team = (
                match.home
                if row.get("team_id") == home_id
                else match.away
                if row.get("team_id") == away_id
                else row.get("team", "")
            )
            player = str(row.get("player") or "").strip()
            if not team or not player:
                continue
            facts.append(
                AvailabilityFact(
                    event_type="player_unavailable",
                    team=team,
                    player=player,
                    status=str(row.get("type") or "reported"),
                    observed_at=as_of,
                    source_url=source_url,
                    credibility=0.82,
                    expected_minutes_delta=-45,
                    reason=str(row.get("reason") or ""),
                )
            )
        return MatchIntel(
            match_id=match.id,
            facts=tuple(facts),
            completeness=0.65,
            missing=("预计首发/确认首发",),
        )

    def fetch_for_matches(
        self,
        matches: Iterable[Match],
        *,
        as_of: str,
    ) -> tuple[dict[str, MatchIntel], list[str]]:
        result: dict[str, MatchIntel] = {}
        warnings: list[str] = []
        eligible = [match for match in matches if match.provider_fixture_id is not None]
        if not eligible:
            return {}, ["已配置 API-Football，但赛单没有 provider_fixture_id，阵容增强已降级"]
        for match in eligible:
            try:
                result[match.id] = self.intelligence(match, as_of=as_of)
            except (ProviderError, OSError, ValueError) as exc:
                warnings.append(f"{match.match_no} API-Football 阵容获取失败：{exc}")
        return result, warnings
