# football-prediction-skill

一个面向 Codex、Claude Code 与命令行的竞彩足球智能分析 Skill：按日期拉取赛单，用 Dixon-Coles、市场概率和有来源情报生成可解释预测，并输出可离线打开的深色 HTML 报告。

> 只做赛前概率研究与回测，不代客操作、不提供下注通道、不承诺命中率或收益。理性购彩，未成年人禁止购彩。

## 能力

- 按日期覆盖竞彩足球胜平负场次，支持 SportteryAPI 与官方接口本地降级。
- Dixon-Coles 低比分修正、时间衰减拟合、Elo/xG 特征与市场对数融合。
- A/B 情报分层；每条 A 级情报必须包含来源、发布时间、可信度和有界影响。
- 价值判断、推荐比分、置信度、信息缺口与逐场解释。
- 防未来数据泄漏的滚动回测：命中率、Brier、log-loss、ROI、最大回撤和可靠性曲线。
- 小组赛蒙特卡洛排名、可配置淘汰赛对阵与“避强路径”启发式。
- 自包含 HTML：内联数据、CSS、JavaScript、SVG，离线打开不发网络请求。

## 安装

需要 Node.js 18+ 和 Python 3.10+：

```bash
npx github:JetQiao/football-prediction-skill install
```

安装器不会通过 pip 构建本项目本身，避免额外下载 `setuptools/wheel`；Python 运行依赖会在 PyPI、清华和阿里云镜像间自动降级。网络受限时可显式指定镜像：

```bash
FOOTBALL_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  npx -y github:JetQiao/football-prediction-skill#v0.1.1 install
```

如需长期使用全局命令：

```bash
npm install -g github:JetQiao/football-prediction-skill
football-predict doctor
```

也可以只安装 Python CLI：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

## 快速体验

先用完全离线的虚构数据验证运行环境：

```bash
npx -y github:JetQiao/football-prediction-skill demo --no-open --out ./reports/demo
```

生成真实日期报告：

```bash
npx -y github:JetQiao/football-prediction-skill daily --date today
```

下面示例使用全局 `football-predict`；未全局安装时，把它替换为 `npx -y github:JetQiao/football-prediction-skill`。

完整的智能体情报工作流：

```bash
# 1. 拉赛单并生成 A 级情报队列
football-predict prepare --date today --out ./work/today

# 2. 智能体根据 intel_queue_*.json 搜索赛前信息，生成 intel.json

# 3. 校验并生成最终报告
football-predict validate-intel ./work/today/intel.json
football-predict daily \
  --date today \
  --input ./work/today/matches_YYYY-MM-DD.json \
  --intel ./work/today/intel.json
```

每次日常运行生成三个可追溯产物：

- `prediction_YYYY-MM-DD.json`：机器可读预测快照。
- `report_YYYY-MM-DD.html`：最终离线报告。
- `manifest_<run_id>.json`：数据源、参数、警告和产物路径。

生成五大联赛 xG + ClubElo 特征快照（需安装可选依赖）：

```bash
pip install 'football-prediction-skill[xg]'
football-predict fetch-features \
  --league ENG-Premier League --season 2025 \
  --out ./features.json
```

## 数据增强

不配置 Key 也能运行。以下能力按需启用：

| 环境变量 | 用途 |
|---|---|
| `SPORTTERY_API_URL` | 本地或自部署 SportteryAPI，推荐优先使用 |
| `SPORTTERY_API_KEY` | SportteryAPI 可选鉴权 |
| `API_FOOTBALL_KEY` | 结构化伤病和阵容 |
| `THE_ODDS_API_KEY` | 实时市场赔率；免费降级模式不需要 |

SportteryAPI 的全球 Worker 可能受竞彩上游地域限制。本地 MCP/REST 或本地官方接口通常更可靠。详见 [SportteryAPI](https://github.com/Johnserf-Seed/SportteryAPI)。

## 输入协议

球队特征、市场快照和情报 JSON 示例位于 [`examples/`](examples/)。字段契约见 [`docs/data-contracts.md`](docs/data-contracts.md)。

## 回测

```bash
football-predict backtest ./E0.csv --min-train 120 --window 600
```

历史数据可从 [football-data.co.uk](https://www.football-data.co.uk/data.php) 获取。回测按时间排序，只用当前比赛之前的数据拟合；收盘赔率只能用于历史基准，不能提前注入日常预测。该站提示 2025-07 之后的 Pinnacle 数据可能系统性滞后，本项目对这些赛季优先采用市场平均收盘赔率。

## 开发

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -p 'test_*.py'
python /path/to/skill-creator/scripts/quick_validate.py skill/football-prediction-skill
```

架构、Provider 边界和降级策略见 [`docs/architecture.md`](docs/architecture.md)。欢迎提交 Issue 与 Pull Request。

## License

MIT。第三方数据与服务受各自条款约束，详见 [`NOTICE`](NOTICE)。
