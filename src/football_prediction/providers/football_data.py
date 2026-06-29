"""football-data.co.uk 历史数据读取器。"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .base import USER_AGENT, ProviderError


@dataclass(frozen=True)
class HistoricalMatch:
    date: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    result: str
    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None
    odds_source: str | None = None


class FootballDataProvider:
    def __init__(self, timeout: float = 30) -> None:
        self.timeout = timeout

    def download(self, url: str, target: Path) -> Path:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"football-data.co.uk 下载失败：{exc}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def read(self, path: Path) -> list[HistoricalMatch]:
        content = path.read_bytes().decode("utf-8-sig", errors="replace")
        return self.parse(content)

    @staticmethod
    def parse(content: str) -> list[HistoricalMatch]:
        result: list[HistoricalMatch] = []
        for row in csv.DictReader(io.StringIO(content)):
            if not row.get("HomeTeam") or row.get("FTHG") in (None, ""):
                continue
            day = FootballDataProvider._date(row.get("Date", ""))
            odds = FootballDataProvider._odds(row, day)
            result.append(
                HistoricalMatch(
                    date=day,
                    home=row["HomeTeam"],
                    away=row["AwayTeam"],
                    home_goals=int(row["FTHG"]),
                    away_goals=int(row["FTAG"]),
                    result=row.get("FTR")
                    or (
                        "H"
                        if int(row["FTHG"]) > int(row["FTAG"])
                        else "A"
                        if int(row["FTHG"]) < int(row["FTAG"])
                        else "D"
                    ),
                    home_odds=odds[0],
                    draw_odds=odds[1],
                    away_odds=odds[2],
                    odds_source=odds[3],
                )
            )
        return result

    @staticmethod
    def _date(value: str) -> str:
        for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                continue
        return value

    @staticmethod
    def _odds(row: dict[str, str], match_date: str) -> tuple[float | None, float | None, float | None, str | None]:
        # 2025-07 后 football-data.co.uk 明确提示 Pinnacle 数据可能系统性滞后，
        # 因此新数据优先市场平均收盘；早期数据仍优先 Pinnacle 收盘。
        recent = bool(match_date and match_date >= "2025-07-01")
        prefixes = ("AvgC", "MaxC", "PSC", "B365C", "PS", "B365") if recent else ("PSC", "AvgC", "B365C", "PS", "B365")
        for prefix in prefixes:
            keys = (f"{prefix}H", f"{prefix}D", f"{prefix}A")
            if all(row.get(key) not in (None, "") for key in keys):
                values = tuple(float(row[key]) for key in keys)
                return values[0], values[1], values[2], prefix
        return None, None, None, None
