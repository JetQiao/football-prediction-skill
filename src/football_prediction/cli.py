"""football-predict 命令行入口。"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import webbrowser
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from . import __version__
from .backtest import evaluate_daily_files, rolling_backtest
from .config import Settings
from .demo import demo_matches
from .domain import BacktestSummary, DailyReport, Probability3, to_dict
from .intelligence import load_intel
from .modeling.registry import ModelRegistry
from .modeling.training import train_model_bundle
from .pipeline import DailyPipeline, load_matches
from .providers.features import ClubEloProvider, SoccerDataUnderstatProvider
from .providers.football_data import FootballDataProvider
from .providers.sporttery import SportteryProvider
from .reporting import write_report, write_tournament_report
from .snapshots import SnapshotEnvelope, SnapshotStore
from .storage import write_json
from .tournament import Fixture, TournamentSimulator


def _day(value: str) -> date:
    return date.today() if value in ("today", "今天") else date.fromisoformat(value)


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


def _open_report(path: Path, *, disabled: bool) -> None:
    """只在交互式终端自动打开，避免 CI/Agent 环境触发 AppleScript 噪声。"""

    if disabled or not sys.stdout.isatty():
        return
    webbrowser.open(path.as_uri())


def _metric_pair(value: object, baseline: object) -> str:
    left = f"{float(value):.4f}" if value is not None else "—"
    right = f"{float(baseline):.4f}" if baseline is not None else "—"
    return f"{left}/{right}"


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
    daily.add_argument("--as-of", help="预测截点 ISO 8601，默认当前时间")
    daily.add_argument("--demo", action="store_true", help="使用虚构离线数据验证完整链路")
    daily.add_argument("--no-open", action="store_true", help="不自动打开报告")

    prepare = sub.add_parser("prepare", help="拉取赛单并生成 A 级情报检索队列")
    prepare.add_argument("--date", default="today")
    prepare.add_argument("--input", help="离线比赛 JSON")
    prepare.add_argument("--out", help="输出目录")
    prepare.add_argument("--as-of", help="快照截点 ISO 8601，默认当前时间")
    prepare.add_argument("--demo", action="store_true")

    sync = sub.add_parser("sync", help="拉取赛单并写入不可变 DuckDB/Parquet 快照")
    sync.add_argument("--date", default="today")
    sync.add_argument("--input", help="离线比赛 JSON")
    sync.add_argument("--out", help="输出目录")
    sync.add_argument("--as-of", help="快照截点 ISO 8601，默认当前时间")
    sync.add_argument("--demo", action="store_true")

    backtest = sub.add_parser("backtest", help="对 football-data.co.uk CSV 做滚动回测")
    backtest.add_argument("csv", help="历史 CSV 文件")
    backtest.add_argument("--min-train", type=int, default=120)
    backtest.add_argument("--window", type=int, default=600)
    backtest.add_argument("--refit-every", type=int, default=30)
    backtest.add_argument(
        "--pipeline",
        choices=("production", "independent-value"),
        default="production",
        help="production 使用市场作为参考；independent-value 只把市场作为目标价格",
    )
    backtest.add_argument("--out", help="输出目录")
    backtest.add_argument("--no-open", action="store_true")

    train = sub.add_parser("train", help="训练同日无泄漏 Dixon-Coles、融合器和校准器")
    train.add_argument("csv", help="football-data.co.uk 历史 CSV")
    train.add_argument("--competition", required=True, help="模型对应联赛名称，例如 英超")
    train.add_argument("--alias", action="append", default=[], help="联赛别名，可重复")
    train.add_argument("--until", help="训练截止日期 YYYY-MM-DD")
    train.add_argument("--min-train", type=int, default=120)
    train.add_argument("--window", type=int, default=600)
    train.add_argument("--refit-every", type=int, default=30)
    train.add_argument("--version", help="模型版本；默认自动生成")
    train.add_argument("--promote", action="store_true", help="通过门槛后设为生产模型")
    train.add_argument("--force-promote", action="store_true", help="即使门槛未通过也强制晋级")
    train.add_argument("--out", help="额外导出模型 JSON 的目录")

    models = sub.add_parser("models", help="查看或晋级本地模型注册表")
    models.add_argument("--promote", metavar="VERSION", help="晋级指定模型版本")
    models.add_argument("--json", action="store_true")

    snapshots = sub.add_parser("snapshots", help="查看本地不可变快照目录")
    snapshots.add_argument("--dataset")
    snapshots.add_argument("--json", action="store_true")

    evaluate_daily = sub.add_parser("evaluate-daily", help="用赛后比分评估已保存的每日预测")
    evaluate_daily.add_argument("prediction", help="prediction_YYYY-MM-DD.json")
    evaluate_daily.add_argument("results", help="赛果 JSON，支持 match_id/match_no + score")
    evaluate_daily.add_argument("--out", help="输出目录")
    evaluate_daily.add_argument("--no-open", action="store_true")

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
    doctor.add_argument("--strict", action="store_true", help="关键依赖或生产模型缺失时返回失败")
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
        as_of=args.as_of,
    )
    _open_report(html_path, disabled=args.no_open)
    print(f"已生成报告：{html_path}")
    print(f"预测数据：{json_path}")
    direction_counts = Counter(
        getattr(prediction.direction_state, "value", prediction.direction_state)
        for prediction in report.predictions
    )
    value_counts = Counter(
        getattr(prediction.value_state, "value", prediction.value_state)
        for prediction in report.predictions
    )
    print(
        f"场次 {len(report.predictions)} · "
        f"明确方向 {direction_counts['strong']} · "
        f"中等方向 {direction_counts['moderate']} · "
        f"轻微方向 {direction_counts['slight']} · "
        f"价值候选 {value_counts['candidate']} · "
        f"数据不可用 {direction_counts['unavailable']}"
    )
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    day = _day(args.date)
    settings = Settings().validate()
    warnings: list[str] = []
    source_match_count: int | None = None
    active_source = "input-json"
    if args.demo:
        matches = demo_matches(day)
        active_source = "demo"
    elif args.input:
        matches = load_matches(_path(args.input), day)
    else:
        provider = SportteryProvider(
            api_url=settings.sporttery_api_url,
            api_key=settings.sporttery_api_key,
            timeout=settings.request_timeout,
            cache_dir=settings.paths.cache / "sporttery",
        )
        matches = provider.fetch_matches(day)
        warnings.extend(provider.warnings)
        source_match_count = provider.source_match_count
        active_source = provider.active_source
    matches = DailyPipeline._assign_tiers(matches)
    target = _path(args.out) or settings.paths.snapshots / day.isoformat()
    target.mkdir(parents=True, exist_ok=True)
    match_path = write_json(
        target / f"matches_{day.isoformat()}.json",
        {
            "matches": matches,
            "meta": {
                "source_match_count": source_match_count if source_match_count is not None else len(matches),
                "parsed_match_count": len(matches),
                "warnings": warnings,
            },
        },
    )
    cutoff = DailyPipeline._resolve_cutoff(args.as_of, matches).isoformat(timespec="seconds")
    queue = {
        "business_date": day.isoformat(),
        "rules": {
            "cutoff": f"仅使用 observed_at <= {cutoff} 且早于 kickoff_at 的信息",
            "preferred_schema": "facts",
            "required_fact_fields": [
                "event_type",
                "team",
                "player",
                "status",
                "observed_at",
                "source_url",
                "credibility",
            ],
            "optional_fact_fields": [
                "position",
                "expected_minutes_delta",
                "reason",
                "event_fingerprint",
            ],
            "legacy_evidences": "仅兼容旧输入；不要优先让智能体填写 outcome/impact",
        },
        "matches": [
            {
                "match_id": match.id,
                "league": match.league,
                "home": match.home,
                "away": match.away,
                "kickoff_at": match.kickoff_at,
                "intel_tier": match.intel_tier,
                "provider_fixture_id": match.provider_fixture_id,
                "search_topics": ["官方大名单", "伤病停赛", "预计首发", "主教练发布会", "可信体育媒体赛前消息"],
            }
            for match in matches
            if match.intel_tier == "A"
        ],
    }
    queue_path = write_json(target / f"intel_queue_{day.isoformat()}.json", queue)
    envelope = SnapshotEnvelope(
        dataset="sporttery-fixtures",
        business_date=day.isoformat(),
        as_of=cutoff,
        observed_at=cutoff,
        source=active_source,
        source_event_id=f"{day.isoformat()}-{len(matches)}",
        payload={
            "matches": [to_dict(match) for match in matches],
            "meta": {
                "source_match_count": source_match_count if source_match_count is not None else len(matches),
                "parsed_match_count": len(matches),
                "warnings": warnings,
            },
        },
    )
    parquet_path, snapshot_json_path = SnapshotStore(settings.paths.snapshots).write(envelope)
    print(f"赛单快照：{match_path}")
    print(f"情报队列：{queue_path}")
    print(f"Parquet 快照：{parquet_path}")
    print(f"快照信封：{snapshot_json_path}")
    print(f"快照标识：{envelope.snapshot_id}")
    print(f"全部 {len(matches)} 场 · A 级 {len(queue['matches'])} 场")
    for warning in warnings:
        print(f"警告：{warning}")
    return 0


def command_backtest(args: argparse.Namespace) -> int:
    history = FootballDataProvider().read(_path(args.csv))
    settings = Settings().validate()
    summary, _ = rolling_backtest(
        history,
        min_train=args.min_train,
        window=args.window,
        refit_every=args.refit_every,
        pipeline_mode=args.pipeline,
        settings=settings,
    )
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report = DailyReport(
        business_date="历史回测",
        generated_at=generated_at,
        predictions=(),
        sources=("football-data.co.uk",),
        backtest=summary,
        run_id=f"backtest-{int(datetime.now().timestamp())}",
        as_of="historical-event-time",
        model_version=f"rolling-{args.pipeline}",
        calibration_status="rolling-oof",
    )
    target = _path(args.out) or settings.paths.reports / "backtest"
    target.mkdir(parents=True, exist_ok=True)
    json_path = write_json(target / "backtest.json", summary)
    html_path = write_report(report, target / "backtest.html")
    _open_report(html_path, disabled=args.no_open)
    print(f"已生成报告：{html_path}")
    print(
        f"样本 {summary.matches} · 命中率 {summary.accuracy:.2%} · "
        f"Brier {summary.brier:.4f} · RPS {summary.rps:.4f} · ECE {summary.ece:.4f}"
    )
    if summary.baseline_brier is not None:
        print(
            f"赔率基线 Brier {summary.baseline_brier:.4f} · 模型/基线 log-loss {summary.log_loss:.4f}/{summary.baseline_log_loss:.4f}"
        )
    if args.pipeline == "independent-value":
        print(f"独立价值策略 ROI {summary.roi:.2%} · 覆盖率 {summary.coverage:.2%}")
    else:
        print("production 模式把历史市场作为参考/基准，不对同源价格模拟价值下注")
    print(f"指标数据：{json_path}")
    return 0


def command_train(args: argparse.Namespace) -> int:
    settings = Settings().validate()
    history = FootballDataProvider().read(_path(args.csv))
    bundle = train_model_bundle(
        history,
        competition=args.competition,
        aliases=args.alias,
        until=args.until,
        min_train=args.min_train,
        window=args.window,
        refit_every=args.refit_every,
        version=args.version,
    )
    gate_passed = bool(bundle.metadata.validation.get("gate_passed"))
    if args.promote and not gate_passed and not args.force_promote:
        raise ValueError("模型未通过样本外晋级门槛；如需研究用途强制晋级，请显式使用 --force-promote")
    promote = bool(args.promote or args.force_promote)
    registry = ModelRegistry(settings.paths.models)
    model_path = registry.register(bundle, promote=promote)
    if args.out:
        exported = _path(args.out) / model_path.name
        write_json(exported, bundle.to_dict())
    validation = bundle.metadata.validation
    print(f"模型版本：{bundle.metadata.version}")
    print(f"模型文件：{model_path}")
    print(
        f"训练样本 {bundle.metadata.sample_size} · OOF 校准 {bundle.metadata.calibration_sample_size} · "
        f"市场权重 {(bundle.ensemble.market_weight if bundle.ensemble else 0):.1%}"
    )
    print(
        f"验证 Brier {_metric_pair(validation.get('brier'), validation.get('baseline_brier'))} · "
        f"Log-loss {_metric_pair(validation.get('log_loss'), validation.get('baseline_log_loss'))} · "
        f"ECE {float(validation['ece']):.4f}"
    )
    print(f"状态：{'已晋级' if promote else bundle.metadata.calibration_status}")
    return 0


def command_models(args: argparse.Namespace) -> int:
    registry = ModelRegistry(Settings().validate().paths.models)
    if args.promote:
        bundle = registry.promote(args.promote)
        print(f"已晋级模型：{bundle.metadata.version}（{bundle.metadata.competition}）")
        return 0
    rows = registry.list()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("模型注册表为空")
    else:
        for row in rows:
            state = "PRODUCTION" if row.get("promoted") else row.get("calibration_status", "unknown")
            print(
                f"{row.get('version'):36} {row.get('competition'):12} "
                f"{row.get('trained_until'):10} {state}"
            )
    return 0


def command_snapshots(args: argparse.Namespace) -> int:
    store = SnapshotStore(Settings().validate().paths.snapshots)
    rows = store.catalog(args.dataset)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("快照目录为空")
    else:
        for row in rows:
            print(
                f"{row['business_date']} {row['dataset']:24} {row['as_of']} "
                f"{row['snapshot_id'][:12]}"
            )
    return 0


def command_evaluate_daily(args: argparse.Namespace) -> int:
    evaluation = evaluate_daily_files(_path(args.prediction), _path(args.results))
    day = evaluation["business_date"] or "unknown-date"
    target = _path(args.out) or Settings().paths.reports / "evaluation" / day
    target.mkdir(parents=True, exist_ok=True)
    json_path = write_json(target / f"evaluation_{day}.json", evaluation)
    summary = BacktestSummary(**evaluation["overall"])
    strata = []
    for confidence, metrics in evaluation["by_confidence"].items():
        strata.append(
            f"置信度 {confidence}：样本 {metrics['matches']}，命中率 {metrics['accuracy']:.1%}，"
            f"Brier {metrics['brier']:.4f}"
        )
    report = DailyReport(
        business_date=f"{day} 赛后评估",
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        predictions=(),
        sources=("保存的赛前预测快照", "用户/官方赛后比分"),
        warnings=tuple(strata),
        backtest=summary,
        run_id=f"evaluation-{evaluation['prediction_run_id'][:12]}",
    )
    html_path = write_report(report, target / f"evaluation_{day}.html")
    _open_report(html_path, disabled=args.no_open)
    print(f"已生成评估报告：{html_path}")
    print(
        f"已结算 {evaluation['matched']} 场 · 待结算 {len(evaluation['pending'])} 场 · "
        f"命中率 {summary.accuracy:.2%} · Brier {summary.brier:.4f} · Log-loss {summary.log_loss:.4f}"
    )
    print(f"评估数据：{json_path}")
    return 0


def command_validate_intel(args: argparse.Namespace) -> int:
    rows = load_intel(_path(args.file))
    evidence_count = sum(len(row.evidences) for row in rows.values())
    fact_count = sum(len(row.facts) for row in rows.values())
    print(
        f"情报校验通过：{len(rows)} 场，{fact_count} 条结构化事实，"
        f"{evidence_count} 条兼容证据"
    )
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
    _open_report(html_path, disabled=args.no_open)
    print(f"已生成报告：{html_path}")
    print(f"模拟数据：{json_path}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    settings = Settings().validate()
    try:
        import duckdb

        duckdb_version = duckdb.__version__
    except ImportError:
        duckdb_version = None
    model_count = len(ModelRegistry(settings.paths.models).list())
    status = {
        "version": __version__,
        "python": platform.python_version(),
        "node": shutil.which("node") is not None,
        "sporttery_mode": "SportteryAPI REST" if settings.sporttery_api_url else "官方接口本地降级",
        "api_football": bool(settings.api_football_key),
        "paid_market": bool(settings.odds_api_key),
        "auto_clubelo": settings.auto_clubelo,
        "duckdb": duckdb_version,
        "registered_models": model_count,
        "data_dir": str(settings.paths.data),
        "cache_dir": str(settings.paths.cache),
    }
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        for key, value in status.items():
            print(f"{key:16} {value}")
    if args.strict and (not duckdb_version or model_count == 0):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "daily": command_daily,
        "prepare": command_prepare,
        "sync": command_prepare,
        "backtest": command_backtest,
        "train": command_train,
        "models": command_models,
        "snapshots": command_snapshots,
        "evaluate-daily": command_evaluate_daily,
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
