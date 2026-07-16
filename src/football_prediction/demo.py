"""离线演示数据，不参与真实预测。"""

from __future__ import annotations

from datetime import date

from .domain import BettingMarketOdds, MarketOutcomeOdds, MarketRole, Match, ThreeWayOdds


def _market(
    code: str,
    label: str,
    rows: tuple[tuple[str, str, float], ...],
    stamp: str,
    line: float | None = None,
) -> BettingMarketOdds:
    """构造完整玩法的演示 SP；演示数据不会参与真实报告。"""

    return BettingMarketOdds(
        code=code,
        label=label,
        outcomes=tuple(MarketOutcomeOdds(key, key, outcome_label, odds) for key, outcome_label, odds in rows),
        updated_at=f"{stamp}T12:00:00+08:00",
        line=line,
    )


def _demo_markets(stamp: str, had: tuple[float, float, float], line: float | None) -> tuple[BettingMarketOdds, ...]:
    markets = [
        _market(
            "had",
            "胜平负",
            (("home", "主胜", had[0]), ("draw", "平", had[1]), ("away", "客胜", had[2])),
            stamp,
        ),
        _market(
            "crs",
            "比分",
            (("1:0", "1:0", 7.8), ("2:0", "2:0", 9.5), ("2:1", "2:1", 8.2), ("1:1", "1:1", 6.6), ("0:1", "0:1", 10.0)),
            stamp,
        ),
        _market(
            "ttg",
            "总进球",
            (("0", "0球", 12.0), ("1", "1球", 4.8), ("2", "2球", 3.6), ("3", "3球", 3.9), ("4", "4球", 5.8), ("5", "5球", 9.5), ("6", "6球", 18.0), ("7+", "7球+", 26.0)),
            stamp,
        ),
        _market(
            "hafu",
            "半全场",
            (("HH", "胜/胜", 3.1), ("HD", "胜/平", 13.0), ("HA", "胜/负", 28.0), ("DH", "平/胜", 4.8), ("DD", "平/平", 5.2), ("DA", "平/负", 6.8), ("AH", "负/胜", 22.0), ("AD", "负/平", 14.0), ("AA", "负/负", 6.1)),
            stamp,
        ),
    ]
    if line is not None:
        markets.insert(
            1,
            _market(
                "hhad",
                "让球胜平负",
                (("home", "让球主胜", 3.4), ("draw", "让球平", 3.55), ("away", "让球客胜", 1.82)),
                stamp,
                line,
            ),
        )
    return tuple(markets)


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
            sporttery_odds=ThreeWayOdds(
                1.92,
                3.35,
                3.62,
                "demo",
                f"{stamp}T12:00:00+08:00",
                MarketRole.TARGET,
            ),
            sporttery_markets=_demo_markets(stamp, (1.92, 3.35, 3.62), -1),
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
            sporttery_odds=ThreeWayOdds(
                2.38,
                3.15,
                2.68,
                "demo",
                f"{stamp}T12:00:00+08:00",
                MarketRole.TARGET,
            ),
            sporttery_markets=_demo_markets(stamp, (2.38, 3.15, 2.68), None),
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
            sporttery_odds=ThreeWayOdds(
                2.05,
                3.10,
                3.35,
                "demo",
                f"{stamp}T12:00:00+08:00",
                MarketRole.TARGET,
            ),
            sporttery_markets=_demo_markets(stamp, (2.05, 3.10, 3.35), -1),
            handicap=-1,
            intel_tier="A",
            stage="group",
        ),
    ]
