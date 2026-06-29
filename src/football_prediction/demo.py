"""离线演示数据，不参与真实预测。"""

from __future__ import annotations

from datetime import date

from .domain import Match, ThreeWayOdds


def demo_matches(day: date) -> list[Match]:
    stamp = day.isoformat()
    return [
        Match(
            id="demo-001",
            business_date=stamp,
            match_no="周一001",
            league="英超",
            home="海港城",
            away="北境联",
            kickoff_at=f"{stamp}T20:00:00+08:00",
            sporttery_odds=ThreeWayOdds(1.92, 3.35, 3.62, "demo", f"{stamp}T12:00:00+08:00"),
            handicap=-1,
            intel_tier="A",
        ),
        Match(
            id="demo-002",
            business_date=stamp,
            match_no="周一002",
            league="挪超",
            home="峡湾竞技",
            away="极光队",
            kickoff_at=f"{stamp}T22:30:00+08:00",
            sporttery_odds=ThreeWayOdds(2.38, 3.15, 2.68, "demo", f"{stamp}T12:00:00+08:00"),
            intel_tier="B",
        ),
        Match(
            id="demo-003",
            business_date=stamp,
            match_no="周一003",
            league="世界杯",
            home="蓝队",
            away="金队",
            kickoff_at=f"{stamp}T23:00:00+08:00",
            sporttery_odds=ThreeWayOdds(2.05, 3.10, 3.35, "demo", f"{stamp}T12:00:00+08:00"),
            intel_tier="A",
            stage="group",
        ),
    ]
