# 数据契约

概率使用 0~1 小数且三项之和为 1；赔率使用大于 1 的十进制赔率；时间使用 ISO 8601。

## 比赛输入

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

`sporttery_odds` 只代表 HAD，允许为 `null`。官方赛单仍包含的比赛必须保留，即使仅开放 HHAD 或全部玩法待开售。

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

允许角色为 `reference_market`、`target_market`、`benchmark_market`。本地市场文件默认是参考市场，竞彩 SP 默认是目标市场。

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

事实不含 `outcome` 或直接胜平负影响。没有 fingerprint 时程序会按事实内容生成 SHA-256。旧版 `evidences[]` 仅作为兼容路径。

## 赛后比分

```json
{
  "results": [
    {"match_id": "fixture-123", "score": "1:2"},
    {"match_no": "周四002", "home_goals": 2, "away_goals": 0}
  ]
}
```

时间越界、赔率角色错误、源场次数不一致和重复阵容事实会终止处理，不做静默修正。
