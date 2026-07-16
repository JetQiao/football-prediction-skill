"""Elo、xG 与本地特征 Provider。"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from ..domain import TeamFeatures
from .base import USER_AGENT, ProviderError
from .names import TeamNameResolver, name_key


class LocalFeatureProvider:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def load(self) -> dict[str, TeamFeatures]:
        if not self.path:
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("teams", payload)
        iterable = rows.values() if isinstance(rows, dict) else rows
        return {
            name_key(row["team"]): TeamFeatures(
                team=row["team"],
                team_id=str(row["team_id"]) if row.get("team_id") is not None else None,
                elo=float(row["elo"]) if row.get("elo") is not None else None,
                xg_for=float(row["xg_for"]) if row.get("xg_for") is not None else None,
                xg_against=float(row["xg_against"]) if row.get("xg_against") is not None else None,
                form_index=float(row.get("form_index", 0)),
                sample_size=int(row.get("sample_size", 0)),
                source=row.get("source", "local-json"),
                observed_at=row.get("observed_at", ""),
                competition_id=row.get("competition_id"),
            )
            for row in iterable
        }


class ClubEloProvider:
    URL = "http://api.clubelo.com/{day}"

    def __init__(self, resolver: TeamNameResolver | None = None, timeout: float = 15) -> None:
        self.resolver = resolver or TeamNameResolver()
        self.timeout = timeout

    def fetch(self, day: date) -> dict[str, TeamFeatures]:
        request = urllib.request.Request(self.URL.format(day=day.isoformat()), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content = response.read().decode("utf-8-sig")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"ClubElo 获取失败：{exc}") from exc

        result: dict[str, TeamFeatures] = {}
        for row in csv.DictReader(io.StringIO(content)):
            team = row.get("Club") or row.get("Team")
            elo = row.get("Elo")
            if not team or not elo:
                continue
            canonical = self.resolver.resolve(team)
            result[name_key(canonical)] = TeamFeatures(
                team=canonical,
                elo=float(elo),
                source="clubelo",
                observed_at=day.isoformat(),
            )
        return result


class SoccerDataUnderstatProvider:
    """复用 soccerdata 的 Understat 读取器，聚合最近比赛 xG。"""

    def __init__(self, leagues: list[str], seasons: list[str], recent_matches: int = 10) -> None:
        self.leagues = leagues
        self.seasons = seasons
        self.recent_matches = recent_matches

    def fetch(self) -> dict[str, TeamFeatures]:
        try:
            import soccerdata as sd
        except ImportError as exc:
            raise ProviderError("未安装 xG 可选依赖，请运行 pip install 'football-prediction-skill[xg]'") from exc
        frame = sd.Understat(leagues=self.leagues, seasons=self.seasons).read_team_match_stats()
        records = frame.reset_index().to_dict(orient="records")
        return self.aggregate_records(records, recent_matches=self.recent_matches)

    @staticmethod
    def aggregate_records(records: list[dict], *, recent_matches: int = 10) -> dict[str, TeamFeatures]:
        grouped: dict[str, list[tuple[float, float | None]]] = {}
        names: dict[str, str] = {}
        for raw in records:
            row = {}
            for raw_key, value in raw.items():
                parts = raw_key if isinstance(raw_key, tuple) else (raw_key,)
                key = next((str(part) for part in reversed(parts) if str(part).strip()), "")
                row[key.lower().replace(" ", "_")] = value
            team = row.get("team") or row.get("squad")
            xg = row.get("xg") or row.get("expected_goals")
            xga = row.get("xga") or row.get("expected_goals_against")
            if not team or xg is None:
                continue
            key = name_key(str(team))
            names[key] = str(team)
            try:
                grouped.setdefault(key, []).append((float(xg), float(xga) if xga is not None else None))
            except (TypeError, ValueError):
                continue
        result: dict[str, TeamFeatures] = {}
        for key, rows in grouped.items():
            sample = rows[-recent_matches:]
            xga_values = [row[1] for row in sample if row[1] is not None]
            result[key] = TeamFeatures(
                team=names[key],
                xg_for=sum(row[0] for row in sample) / len(sample),
                xg_against=sum(xga_values) / len(xga_values) if xga_values else None,
                sample_size=len(sample),
                source="soccerdata-understat",
            )
        if not result:
            raise ProviderError("soccerdata Understat 返回结构中未找到 team/xG 字段")
        return result
