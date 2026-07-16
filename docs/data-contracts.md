# 公共数据协议

概率内部使用 0~1 小数且三项之和为 1；赔率使用大于 1 的十进制赔率；时间使用 ISO 8601。

## 比赛

```json
{
  "matches": [{
    "id": "fixture-123",
    "business_date": "2026-07-16",
    "match_no": "周四001",
    "league": "英超",
    "competition_id": "E0",
    "season_id": "2026",
    "home": "Arsenal",
    "away": "Chelsea",
    "home_team_id": "team-1",
    "away_team_id": "team-2",
    "provider_fixture_id": 123456,
    "kickoff_at": "2026-07-16T20:00:00+08:00",
    "sporttery_odds": {
      "home": 1.92,
      "draw": 3.35,
      "away": 3.62,
      "source": "sporttery",
      "updated_at": "2026-07-16T12:00:00+08:00",
      "role": "target_market"
    }
  }]
}
```

`sporttery_odds` 只代表 HAD，允许为 `null`。只要官方赛单仍包含比赛，即使仅开放 HHAD 或全部玩法待开售，也不得删除。

## 球队特征

```json
{
  "teams": [{
    "team": "Arsenal",
    "team_id": "team-1",
    "elo": 1910,
    "xg_for": 1.82,
    "xg_against": 0.96,
    "form_index": 0.35,
    "sample_size": 12,
    "source": "clubelo+understat",
    "observed_at": "2026-07-16T10:00:00+08:00",
    "competition_id": "E0"
  }]
}
```

## 独立参考市场

```json
{
  "matches": [{
    "home": "Arsenal",
    "away": "Chelsea",
    "home_odds": 1.88,
    "draw_odds": 3.70,
    "away_odds": 4.30,
    "source": "pinnacle",
    "updated_at": "2026-07-16T12:02:00+08:00",
    "role": "reference_market"
  }]
}
```

允许的角色：

- `reference_market`
- `target_market`
- `benchmark_market`

本地市场文件默认是 `reference_market`。目标竞彩默认是 `target_market`。历史 football-data 赔率只作为 `benchmark_market`。

## 结构化阵容事实

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
      "event_fingerprint": "optional-stable-id"
    }]
  }]
}
```

事实不含 `outcome` 或直接胜平负影响。若未提供 fingerprint，系统按事实内容生成 SHA-256。

兼容旧版 `evidences[]`，但其 `impact` 必须位于 -0.08~0.08，并且重复来源/标题/方向只计一次。

## 快照信封

```json
{
  "dataset": "sporttery-fixtures",
  "business_date": "2026-07-16",
  "as_of": "2026-07-16T12:00:00+08:00",
  "observed_at": "2026-07-16T12:00:00+08:00",
  "source": "sporttery-api",
  "source_event_id": "2026-07-16-18",
  "schema_version": "2.0",
  "payload_hash": "sha256...",
  "snapshot_id": "sha256...",
  "payload": {}
}
```

## 赛后比分

```json
{
  "results": [
    {"match_id": "fixture-123", "score": "1:2"},
    {"match_no": "周四002", "home_goals": 2, "away_goals": 0}
  ]
}
```

所有输入都经过 Python 领域模型强校验；时间越界、赔率角色错误、源场次数不一致或重复阵容事实会直接终止，不静默修正。
