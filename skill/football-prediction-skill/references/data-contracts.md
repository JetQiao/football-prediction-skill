# 数据契约

所有概率内部使用 0~1 小数；三项之和必须为 1。赔率使用大于 1 的十进制赔率，时间使用 ISO 8601。

## 比赛输入

```json
{
  "matches": [{
    "id": "123",
    "business_date": "2026-06-29",
    "match_no": "周一001",
    "league": "英超",
    "home": "Arsenal",
    "away": "Chelsea",
    "kickoff_at": "2026-06-29T20:00:00+08:00",
    "intel_tier": "A",
    "sporttery_odds": {
      "home": 1.92,
      "draw": 3.35,
      "away": 3.62,
      "source": "sporttery",
      "updated_at": "2026-06-29T12:00:00+08:00"
    }
  }]
}
```

## 球队特征

```json
{
  "teams": [{
    "team": "Arsenal",
    "elo": 1910,
    "xg_for": 1.82,
    "xg_against": 0.96,
    "form_index": 0.35,
    "sample_size": 12,
    "source": "clubelo+understat"
  }]
}
```

## 市场赔率快照

```json
{
  "matches": [{
    "home": "Arsenal",
    "away": "Chelsea",
    "home_odds": 1.88,
    "draw_odds": 3.70,
    "away_odds": 4.30,
    "source": "pinnacle",
    "updated_at": "2026-06-29T12:02:00+08:00"
  }]
}
```

球队名称匹配会忽略大小写、空格和常见 FC/Club 后缀。名称存在歧义时先人工确认，禁止按相似字符串自动猜测。
