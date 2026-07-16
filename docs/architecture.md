# 架构设计

## 生产数据流

```text
赛单 / 目标竞彩 SP ─┐
独立参考市场 ───────┤
Elo / xG / 阵容事实 ├→ 不可变快照 → 身份与事件时间校验 → PredictionPipeline
有来源赛前情报 ─────┘                                      │
                                                           ├→ 动态 Dixon-Coles
模型注册表 ────────────────────────────────────────────────┤
                                                           ├→ 样本外市场融合
                                                           ├→ 温度校准
                                                           ├→ 弃权 / 价值策略
                                                           └→ JSON / Manifest / HTML

赛后结果 + 历史快照 → 同一个 PredictionPipeline 回放 → 指标与模型晋级
```

## 模块边界

- `providers/`：抓取、契约校验和归一化，不做胜平负判断。
- `snapshots/`：DuckDB 目录、Parquet 数据与 JSON 信封；快照按事件时间不可变。
- `modeling/`：Dixon-Coles、去水、样本外融合、校准和模型注册表。
- `prediction.py`：生产与回放共享的唯一概率入口。
- `policy/`：置信度、不确定性、弃权和价值门槛。
- `intelligence/`：校验来源与时间；结构化阵容事实不直接携带赛果方向。
- `backtest/`：按比赛日整体留出，计算概率与策略指标。
- `reporting/`：视图模型、模板、CSS 与 JavaScript；运行时不访问网络。

## 事件时间

所有可进入模型的数据必须满足：

```text
observed_at <= as_of < kickoff_at
model.trained_until < business_date
```

同一比赛日全部预测完成后，赛果才能进入训练历史。CSV 没有可靠开赛时间时，以日期为最小批次，禁止同日行间泄漏。

## 市场角色

- `reference_market`：预测先验或融合输入。
- `target_market`：竞彩价格比较对象。
- `benchmark_market`：历史评估基准。

目标市场不能同时作为同一价值判断的预测来源。只有竞彩自身多玩法时，可以展示“目标市场共识”，但必须 `abstain`。

## 快照

快照信封至少记录：

- `dataset`
- `business_date`
- `as_of`
- `observed_at`
- `source`
- `source_event_id`
- `schema_version`
- `payload_hash`
- `snapshot_id`

`payload_hash` 只表示内容；`snapshot_id` 同时包含来源与事件时间。因此相同内容在两个不同截点会保留为两个快照。

## 模型与晋级

Champion 基础模型是按联赛训练的动态 Dixon-Coles。市场融合器从 OOF 概率学习：

- 市场权重。
- 主胜/平/客的有界系统性偏置。
- 去水方法：Multiplicative、Power 或 Shin。

随后使用 OOF 概率训练温度校准器。生产模型必须同时满足：

- Log-loss 不比市场差超过 0.2%。
- Brier 至少优于市场 0.5%。
- RPS 不比市场差超过 0.2%。
- ECE 不高于 0.03。

未通过门槛的模型保留为 challenger，但 `ModelRegistry.resolve()` 默认不加载。

## 阵容与情报

推荐输入 `AvailabilityFact`：

- 球队、球员、状态、位置。
- 预计分钟变化。
- 来源 URL、观测时间和可信度。
- 事件 fingerprint。

确定性层把事实映射为最多 12% 的进攻/防守 xG 调整。旧的 `IntelEvidence.impact` 仅为兼容路径，继续受单条与总量边界限制。

## 决策状态

- `candidate`：独立概率、校准状态和价格优势全部通过。
- `lean`：有方向，但缺少价格、校准或足够优势。
- `no_edge`：目标价格没有正向独立优势。
- `abstain`：数据不足、目标价格进入概率或不确定性过高。

## 可追溯性

manifest 保存快照 ID、模型版本、训练截止、校准状态、参数、决策计数和产物路径。API Key 不进入任何产物。
