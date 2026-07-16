# A 级赛前情报流程

## 来源优先级

1. 赛事、国家队、俱乐部官方公告与主教练发布会。
2. 可靠通讯社、当地长期跟队记者和主流体育媒体。
3. API-Football 等结构化伤病源。
4. 聚合站与社交媒体只作线索，不能单独支撑高影响事实。

## 必查项目

- 官方大名单、预计首发、门将与中轴线可用性。
- 伤病、停赛、轮换、赛程密度和旅行因素。
- 主教练明确表达的战术或人员信息。
- 更衣室或负面传闻只有在至少两个可靠来源一致时才记录。

## 时间边界

每条事实必须满足：

```text
observed_at <= as_of < kickoff_at
```

不得使用截点后发布的首发、开赛后报道、赛果或收盘后数据。来源页面若没有可确认发布时间，降低可信度或放入 `missing`，不要猜测时间。

## 首选 facts 协议

```json
{
  "matches": [{
    "match_id": "fixture-123",
    "completeness": 0.75,
    "missing": ["客队最终首发"],
    "facts": [{
      "event_type": "player_unavailable",
      "team": "Arsenal",
      "player": "Player A",
      "status": "confirmed_out",
      "position": "ST",
      "expected_minutes_delta": -75,
      "source_url": "https://example.com/official-news",
      "observed_at": "2026-07-16T09:00:00+08:00",
      "credibility": 0.95,
      "reason": "俱乐部确认肌肉伤缺",
      "event_fingerprint": "optional-stable-id"
    }]
  }]
}
```

约束：

- 智能体只抽取事实，不填写主胜/平/客方向或概率影响。
- `expected_minutes_delta` 位于 `-90~0`，表达预计缺失分钟。
- 同一事件只保留一条；优先使用稳定 fingerprint 去重。
- 传闻和未确认状态使用更低可信度，并明确写入 `status/reason`。
- 程序将事实映射为有界 xG 调整，单场阵容调整不会无限放大。

## 兼容 evidences

旧版 `evidences[]` 仍可读取，其中单条 `impact` 必须位于 `-0.08~0.08`。这是兼容用 logit 残差，不是直接加减概率；新任务不要优先生成该格式。
