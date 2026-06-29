"""可配置小组排名、蒙特卡洛模拟与避强启发式。"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..domain import Probability3


@dataclass(frozen=True)
class Fixture:
    group: str
    home: str
    away: str
    probabilities: Probability3
    played_score: tuple[int, int] | None = None


@dataclass
class TeamStanding:
    team: str
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


@dataclass
class GroupTable:
    group: str
    standings: list[TeamStanding] = field(default_factory=list)

    def ranked(self) -> list[TeamStanding]:
        return sorted(self.standings, key=lambda row: (row.points, row.goal_difference, row.goals_for), reverse=True)


class TournamentSimulator:
    def __init__(self, seed: int = 42) -> None:
        self.random = random.Random(seed)

    def simulate(self, fixtures: Sequence[Fixture], runs: int = 10_000) -> dict[str, dict[str, dict[int, float]]]:
        if runs <= 0:
            raise ValueError("模拟次数必须大于 0")
        rank_counts: dict[str, dict[str, Counter[int]]] = defaultdict(lambda: defaultdict(Counter))
        groups = sorted({fixture.group for fixture in fixtures})
        for _ in range(runs):
            tables = self._play(fixtures)
            for group in groups:
                for rank, standing in enumerate(tables[group].ranked(), start=1):
                    rank_counts[group][standing.team][rank] += 1
        return {
            group: {
                team: {rank: count / runs for rank, count in sorted(counter.items())} for team, counter in teams.items()
            }
            for group, teams in rank_counts.items()
        }

    def _play(self, fixtures: Sequence[Fixture]) -> dict[str, GroupTable]:
        standings: dict[str, dict[str, TeamStanding]] = defaultdict(dict)
        for fixture in fixtures:
            for team in (fixture.home, fixture.away):
                standings[fixture.group].setdefault(team, TeamStanding(team))
            score = fixture.played_score or self._sample_score(fixture.probabilities)
            home = standings[fixture.group][fixture.home]
            away = standings[fixture.group][fixture.away]
            home.goals_for += score[0]
            home.goals_against += score[1]
            away.goals_for += score[1]
            away.goals_against += score[0]
            if score[0] > score[1]:
                home.points += 3
            elif score[0] < score[1]:
                away.points += 3
            else:
                home.points += 1
                away.points += 1
        return {group: GroupTable(group, list(rows.values())) for group, rows in standings.items()}

    def strategic_adjustment(
        self,
        first_path_strength: float,
        second_path_strength: float,
        *,
        qualification_locked: bool,
        max_adjustment: float = 0.07,
    ) -> float:
        """返回争第一意愿修正；负数表示第二名路径明显更轻。"""

        if not qualification_locked:
            return 0.0
        advantage = first_path_strength - second_path_strength
        return -min(max_adjustment, max(0.0, advantage / 1000))

    def first_round_pairings(
        self,
        qualifiers: Mapping[str, tuple[str, str]],
        bracket: Sequence[tuple[str, int, str, int]],
    ) -> list[tuple[str, str]]:
        result = []
        for left_group, left_rank, right_group, right_rank in bracket:
            result.append((qualifiers[left_group][left_rank - 1], qualifiers[right_group][right_rank - 1]))
        return result

    def _sample_score(self, probabilities: Probability3) -> tuple[int, int]:
        value = self.random.random()
        if value < probabilities.home:
            return self.random.choice(((1, 0), (2, 0), (2, 1), (3, 1)))
        if value < probabilities.home + probabilities.draw:
            return self.random.choice(((0, 0), (1, 1), (2, 2)))
        return self.random.choice(((0, 1), (0, 2), (1, 2), (1, 3)))
