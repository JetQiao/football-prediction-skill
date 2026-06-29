"""football-predict 命令行入口。"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import webbrowser
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from . import __version__
from .backtest import rolling_backtest
from .config import Settings
from .demo import demo_matches
from .domain import DailyReport, Probability3
from .intelligence import load_intel
from .pipeline import DailyPipeline, load_matches
from .providers.features import ClubEloProvider, SoccerDataUnderstatProvider
from .providers.football_data import FootballDataProvider
from .providers.sporttery import SportteryProvider
from .reporting import write_report, write_tournament_report
from .storage import write_json
from .tournament import Fixture, TournamentSimulator


def _day(value: str) -> date:
    return date.today() if value in ("today", "今天") else date.fromisoformat(value)


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="football-predict", description="竞彩足球智能预测 Skill")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    daily = sub.add_parser("daily", help="生成指定日期的预测 JSON 与自包含 HTML")
    daily.add_argument("--date", default="today", help="YYYY-MM-DD，默认 today")
    daily.add_argument("--input", help="SportteryAPI/官方接口/标准比赛 JSON")
    daily.add_argument("--features", help="Elo/xG 特征 JSON")
    daily.add_argument("--market", help="赛前市场赔率 JSON")
    daily.add_argument("--intel", help="有来源情报 JSON")
    daily.add_argument("--out", help="输出目录")
    daily.add_argument("--demo", action="store_true", help="使用虚构离线数据验证完整链路")
    daily.add_argument("--no-open", action="store_true", help="不自动打开报告")

    prepare = sub.add_parser("prepare", help="拉取赛单并生成 A 级情报检索队列")
    prepare.add_argument("--date", default="today")
    prepare.add_argument("--input", help="离线比赛 JSON")
    prepare.add_argument("--out", help="输出目录")
    prepare.add_argument("--demo", action="store_true")

    backtest = sub.add_parser("backtest", help="对 football-data.co.uk CSV 做滚动回测")
    backtest.add_argument("csv", help="历史 CSV 文件")
    backtest.add_argument("--min-train", type=int, default=120)
    backtest.add_argument("--window", type=int, default=600)
    backtest.add_argument("--refit-every", type=int, default=30)
    backtest.add_argument("--out", help="输出目录")
    backtest.add_argument("--no-open", action="store_true")

    features = sub.add_parser("fetch-features", help="通过 soccerdata/ClubElo 生成 Elo+xG 特征快照")
    features.add_argument("--league", action="append", required=True, help="soccerdata 联赛 ID，可重复")
    features.add_argument("--season", action="append", required=True, help="赛季，可重复")
    features.add_argument("--date", default="today", help="Elo 快照日期")
    features.add_argument("--recent", type=int, default=10, help="xG 最近比赛数")
    features.add_argument("--out", required=True, help="特征 JSON 输出路径")
    features.add_argument("--no-clubelo", action="store_true")

    validate = sub.add_parser("validate-intel", help="校验情报来源、可信度和影响边界")
    validate.add_argument("file")

    tournament = sub.add_parser("tournament", help="运行小组赛蒙特卡洛排名模拟")
    tournament.add_argument("file", help="赛事 fixture JSON")
    tournament.add_argument("--runs", type=int, default=10_000)
    tournament.add_argument("--out", help="输出目录")
    tournament.add_argument("--no-open", action="store_true")

    doctor = sub.add_parser("doctor", help="检查运行环境和可选数据源配置")
    doctor.add_argument("--json", action="store_true")
    return parser


def command_daily(args: argparse.Namespace) -> int:
    day = _day(args.date)
    settings = Settings().validate()
    matches = demo_matches(day) if args.demo else load_matches(_path(args.input), day) if args.input else None
    report, json_path, html_path = DailyPipeline(settings).run(
        day,
        matches=matches,
        features_file=_path(args.features),
        market_file=_path(args.market),
        intel_file=_path(args.intel),
        output_dir=_path(args.out),
    )
    if not args.no_open:
        webbrowser.open(html_path.as_uri())
    print(f"已生成报告：{html_path}")
    print(f"预测数据：{json_path}")
    print(
        f"场次 {len(report.predictions)} · 高置信 {sum(p.confidence == 'high' for p in report.predictions)} · 价值信号 {sum(bool(p.value and p.value.flag == 'value') for p in report.predictions)}"
    )
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    day = _day(args.date)
    settings = Settings().validate()
    if args.demo:
        matches = demo_matches(day)
    elif args.input:
        matches = load_matches(_path(args.input), day)
    else:
        matches = SportteryProvider(
            api_url=settings.sporttery_api_url,
            api_key=settings.sporttery_api_key,
            timeout=settings.request_timeout,
            cache_dir=settings.paths.cache / "sporttery",
        ).fetch_matches(day)
    matches = DailyPipeline._assign_tiers(matches)
    target = _path(args.out) or settings.paths.snapshots / day.isoformat()
    target.mkdir(parents=True, exist_ok=True)
    match_path = write_json(target / f"matches_{day.isoformat()}.json", {"matches": matches})
    queue = {
        "business_date": day.isoformat(),
        "rules": {
            "cutoff": "仅使用 kickoff_at 之前发布的信息",
            "required": ["url", "published_at", "credibility", "impact", "outcome"],
            "impact_range": [-0.08, 0.08],
        },
        "matches": [
            {
                "match_id": match.id,
                "league": match.league,
                "home": match.home,
                "away": match.away,
                "kickoff_at": match.kickoff_at,
                "intel_tier": match.intel_tier,
                "search_topics": ["官方大名单", "伤病停赛", "预计首发", "主教练发布会", "可信体育媒体赛前消息"],
            }
            for match in matches
            if match.intel_tier == "A"
        ],
    }
    queue_path = write_json(target / f"intel_queue_{day.isoformat()}.json", queue)
    print(f"赛单快照：{match_path}")
    print(f"情报队列：{queue_path}")
    print(f"全部 {len(matches)} 场 · A 级 {len(queue['matches'])} 场")
    return 0


def command_backtest(args: argparse.Namespace) -> int:
    history = FootballDataProvider().read(_path(args.csv))
    summary, _ = rolling_backtest(history, min_train=args.min_train, window=args.window, refit_every=args.refit_every)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report = DailyReport(
        business_date="历史回测",
        generated_at=generated_at,
        predictions=(),
        sources=("football-data.co.uk",),
        backtest=summary,
        run_id=f"backtest-{int(datetime.now().timestamp())}",
    )
    target = _path(args.out) or Settings().paths.reports / "backtest"
    target.mkdir(parents=True, exist_ok=True)
    json_path = write_json(target / "backtest.json", summary)
    html_path = write_report(report, target / "backtest.html")
    if not args.no_open:
        webbrowser.open(html_path.as_uri())
    print(f"已生成报告：{html_path}")
    print(f"样本 {summary.matches} · 命中率 {summary.accuracy:.2%} · Brier {summary.brier:.4f} · ROI {summary.roi:.2%}")
    if summary.baseline_brier is not None:
        print(
            f"赔率基线 Brier {summary.baseline_brier:.4f} · 模型/基线 log-loss {summary.log_loss:.4f}/{summary.baseline_log_loss:.4f}"
        )
    print(f"指标数据：{json_path}")
    return 0


def command_validate_intel(args: argparse.Namespace) -> int:
    rows = load_intel(_path(args.file))
    evidence_count = sum(len(row.evidences) for row in rows.values())
    print(f"情报校验通过：{len(rows)} 场，{evidence_count} 条有来源证据")
    return 0


def command_fetch_features(args: argparse.Namespace) -> int:
    features = SoccerDataUnderstatProvider(args.league, args.season, args.recent).fetch()
    warnings = []
    if not args.no_clubelo:
        try:
            ratings = ClubEloProvider().fetch(_day(args.date))
            for key, current in list(features.items()):
                elo_row = ratings.get(key)
                if elo_row:
                    features[key] = replace(current, elo=elo_row.elo, source=f"{current.source}+clubelo")
        except RuntimeError as exc:
            warnings.append(str(exc))
    target = _path(args.out)
    write_json(target, {"teams": list(features.values()), "warnings": warnings})
    print(f"特征快照：{target}")
    print(f"球队 {len(features)} · 警告 {len(warnings)}")
    return 0


def command_tournament(args: argparse.Namespace) -> int:
    payload = json.loads(_path(args.file).read_text(encoding="utf-8"))
    fixtures = [
        Fixture(
            group=row["group"],
            home=row["home"],
            away=row["away"],
            probabilities=Probability3.normalized((row["home_prob"], row["draw_prob"], row["away_prob"])),
            played_score=tuple(row["played_score"]) if row.get("played_score") else None,
        )
        for row in payload["fixtures"]
    ]
    result = TournamentSimulator(seed=int(payload.get("seed", 42))).simulate(fixtures, runs=args.runs)
    target = _path(args.out) or Path.cwd() / "tournament-report"
    target.mkdir(parents=True, exist_ok=True)
    json_path = write_json(target / "tournament_result.json", result)
    html_path = write_tournament_report(result, target / "tournament_report.html", runs=args.runs)
    if not args.no_open:
        webbrowser.open(html_path.as_uri())
    print(f"已生成报告：{html_path}")
    print(f"模拟数据：{json_path}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    settings = Settings().validate()
    status = {
        "version": __version__,
        "python": platform.python_version(),
        "node": shutil.which("node") is not None,
        "sporttery_mode": "SportteryAPI REST" if settings.sporttery_api_url else "官方接口本地降级",
        "api_football": bool(settings.api_football_key),
        "paid_market": bool(settings.odds_api_key),
        "data_dir": str(settings.paths.data),
        "cache_dir": str(settings.paths.cache),
    }
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        for key, value in status.items():
            print(f"{key:16} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "daily": command_daily,
        "prepare": command_prepare,
        "backtest": command_backtest,
        "fetch-features": command_fetch_features,
        "validate-intel": command_validate_intel,
        "tournament": command_tournament,
        "doctor": command_doctor,
    }
    try:
        return commands[args.command](args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
