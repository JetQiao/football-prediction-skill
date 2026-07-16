---
name: football-prediction-skill
description: Generate explainable China Sports Lottery football predictions with event-time snapshots, strict reference/target market separation, sourced pre-match intelligence, Dixon-Coles probabilities, model-gated value decisions, rolling backtests, tournament simulations, and self-contained dark HTML reports. Use for 竞彩足球、足球预测、竞彩赛单、胜平负概率、让球分析、比分预测、赔率价值、串关研究、赛前情报、足球回测、小组排名、淘汰赛对阵、football prediction or Sporttery analysis.
---

# 竞彩足球智能预测

使用确定性程序完成赛单归一化、事件时间校验、概率模型、价值策略、回测和 HTML 渲染。智能体只负责查找并抽取有来源的赛前事实。始终把自包含 HTML 作为主要交付物。

## 核心约束

- 固定预测截点 `as_of`；只允许 `observed_at <= as_of < kickoff_at` 的数据进入模型。
- 明确区分 `reference_market`、`target_market` 和 `benchmark_market`。
- 不得用目标竞彩价格生成概率后，再用同一价格证明存在价值。
- 只有独立概率、校准状态和价格优势都通过门槛时，才输出 `candidate`。
- 数据不足、未来数据风险或校准未通过时，输出 `lean / no_edge / abstain`。
- 不执行下注，不承诺命中率或盈利，不使用“稳、必选、稳赚”等措辞。

## 选择工作流

- 分析某日竞彩：执行“每日流程”。
- 用户提供历史 CSV：执行“回测或训练”。
- 用户询问小组排名或淘汰赛：读取 [赛事推演](references/tournament.md) 后运行 `tournament`。
- 单场不在竞彩赛单中：按 [数据契约](references/data-contracts.md) 构造输入 JSON，再运行 `daily --input`。

## 命令入口

优先检查已安装命令：

```bash
football-predict doctor
```

命令不存在时使用仓库入口：

```bash
npx -y github:JetQiao/football-prediction-skill doctor
```

下文统一以 `football-predict` 表示当前可用入口。

## 每日流程

1. 确定竞彩销售日期和预测截点。未指定时使用用户本地当前时间；历史日期必须使用明确赛前截点或让 CLI 选择最早开赛前 90 分钟。
2. 获取赛单并写入不可变快照：

```bash
football-predict sync \
  --date YYYY-MM-DD \
  --as-of "YYYY-MM-DDTHH:MM:SS+08:00" \
  --out /tmp/football-predict-YYYY-MM-DD
```

3. 核对源场次数与解析场次数。HAD 未开售、仅 HHAD 在售或玩法暂未开放的比赛也必须保留。
4. 读取 `intel_queue_*.json`。只对 A 级场做深度联网检索，并按 [情报流程](references/intelligence.md) 写入结构化 `facts[]`。不得使用截点后或开赛后的信息。
5. 校验情报：

```bash
football-predict validate-intel /tmp/football-predict-YYYY-MM-DD/intel.json
```

6. 使用相同 `as_of` 生成报告：

```bash
football-predict daily \
  --date YYYY-MM-DD \
  --as-of "YYYY-MM-DDTHH:MM:SS+08:00" \
  --input /tmp/football-predict-YYYY-MM-DD/matches_YYYY-MM-DD.json \
  --intel /tmp/football-predict-YYYY-MM-DD/intel.json
```

7. 回复只提供 HTML 绝对路径、场次数、四态决策数量和关键降级警告。概率不是承诺。

## 市场与特征

使用 `--features features.json` 注入赛前 Elo/xG，使用 `--market market.json` 注入独立参考市场。读取 [数据源与降级](references/sources.md) 确认来源和角色。

- 官方竞彩 HAD/HHAD/SP 默认是 `target_market`。
- 用户传入或 The Odds API 的独立市场默认是 `reference_market`。
- football-data 历史赔率默认是 `benchmark_market`。
- 只有竞彩自身多玩法时，可以展示“目标市场共识”，但必须禁止独立价值候选。

## 回测与模型

生产概率回放：

```bash
football-predict backtest history.csv --pipeline production --no-open
```

独立价值策略回放：

```bash
football-predict backtest history.csv --pipeline independent-value --no-open
```

训练 challenger：

```bash
football-predict train history.csv \
  --competition 英超 \
  --alias "Premier League"
```

查看模型注册表：

```bash
football-predict models
```

只有样本外 Brier、Log-loss、RPS 和 ECE 门槛通过的模型才能使用 `--promote` 晋级。未通过时保留为 challenger，不得因为单段 ROI 漂亮而强行作为生产结论。

每日预测赛后可结算：

```bash
football-predict evaluate-daily prediction_YYYY-MM-DD.json results.json
```

## 输出规则

- 保留 `prediction_*.json`、`report_*.html`、`manifest_*.json` 和快照 ID。
- HTML 必须单文件、离线可用且不发网络请求。
- 报告保留 `as_of`、来源、模型版本、训练截止、校准状态、数据缺失和弃权原因。
- 不在回复中粘贴完整赛单表；HTML 是主要交付物。
