# 数据源、角色与降级

## 来源优先级

- 竞彩赛单与目标价格：SportteryAPI REST → 中国体育彩票公开接口本地直连 → 用户赛前快照。
- 独立参考市场：Pinnacle/可靠付费聚合源 → 多公司共识 → 无参考市场并降级。
- 球队实力：本地 xG + Elo → 自动 ClubElo → 联赛中性先验。
- 阵容事实：俱乐部/赛事官方信息 → API-Football → 可靠媒体 → 缺失并降低置信度。
- 历史回测：football-data.co.uk；只在本地下载，不随 Skill 分发。

## 市场角色

- `reference_market`：可作为预测先验或融合输入。
- `target_market`：只用于与最终独立概率比较价格。
- `benchmark_market`：只用于历史概率评估或 CLV。

目标市场不得同时充当同一价值判断的唯一预测来源。历史收盘赔率只能作为基准，不能伪装成更早时点输入。

## 事件时间

每条数据都应记录来源、观测时间和预测截点。进入模型必须满足：

```text
observed_at <= as_of < kickoff_at
```

训练模型还必须满足：

```text
model.trained_until < business_date
```

## 自动增强

- 配置 `THE_ODDS_API_KEY` 后，日常流程自动尝试独立参考市场。
- 配置 `API_FOOTBALL_KEY` 且赛单提供 `provider_fixture_id` 后，自动拉取结构化伤病事实。
- `FOOTBALL_AUTO_CLUBELO=true` 时，无本地特征会自动尝试 ClubElo。

自动 Provider 失败时必须保留警告并降低数据质量，不得静默换用未来数据或伪造覆盖。

## 运行约束

- 缓存原始响应并记录时间，但不要提交第三方数据集。
- 遵守来源条款、授权范围、robots 策略和请求频率限制。
- SportteryAPI 全球 Worker 可能受上游地域限制；优先在可直连中国大陆网络的本机运行。
- football-data 自 2025-07 后部分 Pinnacle 字段可能滞后，优先使用可用的市场平均字段作为历史基准。
