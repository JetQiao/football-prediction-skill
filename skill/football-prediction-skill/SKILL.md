---
name: football-prediction-skill
description: Generate explainable China Sports Lottery football predictions, value comparisons, sourced pre-match intelligence, Dixon-Coles score probabilities, rolling backtests, group-stage simulations, and self-contained dark HTML reports. Use when the user asks about 竞彩足球、足球预测、竞彩赛单、胜平负概率、让球分析、比分预测、赔率价值、串关研究、赛前情报、足球回测、小组排名、淘汰赛对阵、football prediction or Sporttery analysis.
---

# 竞彩足球智能预测

使用确定性脚本完成数据归一化、概率模型、价值计算、回测和 HTML 渲染；仅使用智能体处理有来源的非结构化情报。始终产出自包含 HTML，不在回复中粘贴完整赛单表。

## 选择工作流

- 用户要分析某日全部竞彩：执行“完整每日流程”。
- 用户只要快速基线或没有联网检索能力：直接运行 `daily`，明确市场/情报降级。
- 用户提供历史 CSV：运行 `backtest`。
- 用户询问小组排名或淘汰赛：读取 [赛事推演](references/tournament.md) 后运行 `tournament`。
- 用户只提供一场比赛且不在竞彩赛单中：构造符合 [数据契约](references/data-contracts.md) 的输入 JSON，再运行 `daily --input`。

## 命令入口

优先使用已安装命令：

```bash
football-predict doctor
```

若命令不存在，使用开源仓库入口：

```bash
npx -y github:JetQiao/football-prediction-skill doctor
```

下文以 `football-predict` 表示可用入口；保持同一入口完成整次任务。

## 完整每日流程

1. 确定竞彩销售日期；未指定时使用用户本地今天，不把开赛自然日与销售日混淆。
2. 创建临时工作目录并拉取赛单：

```bash
football-predict prepare --date YYYY-MM-DD --out /tmp/football-predict-YYYY-MM-DD
```

3. 读取 `matches_*.json` 和 `intel_queue_*.json`。对所有 B 级场保留模型基线；只对队列中的 A 级场执行深度联网检索。
4. 按 [情报流程](references/intelligence.md) 搜索并写入 `intel.json`。禁止使用开赛后的文章、赛果或收盘后才可见的数据。
5. 校验情报：

```bash
football-predict validate-intel /tmp/football-predict-YYYY-MM-DD/intel.json
```

6. 生成最终产物：

```bash
football-predict daily \
  --date YYYY-MM-DD \
  --input /tmp/football-predict-YYYY-MM-DD/matches_YYYY-MM-DD.json \
  --intel /tmp/football-predict-YYYY-MM-DD/intel.json
```

7. 在回复中只提供 HTML 绝对路径、场次数、高置信数、价值信号数和关键降级警告。提醒概率不等于承诺，不给“稳赚”表述。

## 市场与特征增强

使用 `--features features.json` 注入赛前 Elo/xG，使用 `--market market.json` 注入同一预测时点的锐角/市场赔率。读取 [数据源与降级](references/sources.md) 确认来源优先级。

绝不把历史收盘赔率注入更早时点的预测。缺少实时市场时允许降级，但必须保留报告警告。

## 回测

从 football-data.co.uk 获取用户有权使用的联赛 CSV，在本地运行：

```bash
football-predict backtest history.csv --min-train 120 --window 600
```

比较 Brier、log-loss 与竞彩 SP 基线；同时报告样本量、ROI 和最大回撤。不要只挑表现好的联赛或时间段。

## 输出规则

- 保留 `prediction_*.json`、`report_*.html` 和 `manifest_*.json`。
- 把 HTML 作为主要交付物；它必须离线打开且不发网络请求。
- 保留来源、生成时间、运行 ID、缺失信息与降级原因。
- 不执行下注、不代客操作、不承诺盈利；显著提示理性购彩和未成年人禁止购彩。
