# 架构设计

## 数据流

```text
竞彩/SportteryAPI ─→ 全赛单守卫 → 五玩法联合校准 ─┐
Elo/xG/伤病 ───────────────→ Dixon-Coles ────────┼→ 概率融合 → 情报限幅 → 价值评估
赛前外部市场快照 ────────────────────────────────┘                 ↓
                                              JSON + manifest + 自包含 HTML
赛后比分 ─→ prediction 快照对齐 ─→ 分层 Brier / Log-loss / ROI 评估
```

## 边界

- `providers/` 只负责抓取、契约校验和归一化，不在适配器里做模型判断。
- Provider 以官方赛单为边界保留所有比赛；HAD 缺失不是过滤条件，源场次数与解析场次数不一致时立即失败。
- `modeling/` 是确定性纯计算；Dixon-Coles 可由历史数据拟合，也能在缺少模型时使用 Elo/xG 特征。
- `modeling/market_calibration.py` 把 HAD、HHAD、比分、总进球、半全场共同约束到一组期望进球与比分矩阵。
- `intelligence/` 不抓网页，只校验智能体产出的来源、时间和影响边界。
- `backtest/` 严格按时间滚动，拟合窗口永远截止于当前比赛之前。
- `reporting/` 不访问网络，模板和图表全部随 Python 包分发。
- 用户数据写入平台数据目录，升级 Skill 不覆盖历史报告。

## 概率融合

统计概率与市场去水概率使用 logarithmic opinion pool，不把已经进入 xG/攻防模型的实力与状态再次按百分比相加。没有独立 Elo/xG 或外部市场时，官方多玩法只作为低置信“市场基线”，禁止标记为独立模型优势或价值信号。情报只作为有界 logit 残差，最后再进行温度校准。

## SportteryAPI

SportteryAPI 未以可直接导入的公共 npm 库发布，因此本项目通过其 REST/MCP 输出契约集成，并复用其公开的五类玩法编码约定。未配置服务时，本地 Provider 直连同一官方上游并只承担必要的响应归一化。

## 可追溯性

每次运行生成 SHA-256 `run_id`、数据源列表、模型参数、降级警告和产物路径。API Key 不进入产物。
