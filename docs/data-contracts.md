# 公共数据协议

稳定的 JSON 输入协议与 Skill 内说明保持一致：

- 比赛：`id/business_date/match_no/league/home/away/kickoff_at/sporttery_odds?/sporttery_markets[]`。
- 竞彩玩法：`code/label/line/updated_at/outcomes[]`；选项含 `code/key/label/odds/trend`，覆盖 `had/hhad/crs/ttg/hafu`。
- 特征：`team/elo/xg_for/xg_against/form_index/sample_size/source`。
- 市场：`home/away/home_odds/draw_odds/away_odds/source/updated_at`。
- 情报：`match_id/completeness/missing/evidences[]`；每条证据含 URL、发布时间、可信度、影响和对应赛果。

Schema 在 Python `domain.py` 中实施强校验，输入错误直接终止，不静默篡改概率或赔率。

## 赛单完整性

- `sporttery_odds` 仅代表普通胜平负 HAD，未开售时允许为 `null`，不得因此删除整场比赛。
- 只要官方赛单包含该对阵，即使仅开放 HHAD 或全部玩法待开售，也必须保留比赛。
- `prepare` 产物包含 `meta.source_match_count/parsed_match_count`；读取快照时两者不一致会直接报错。
- 新增玩法或单个玩法临时为空时按能力降级，不依赖日期、场号、联赛或球队白名单。

## 赛后评估

`evaluate-daily` 接受通用赛果 JSON：

```json
{
  "results": [
    {"match_id": "2040347", "score": "1:2"},
    {"match_no": "周五088", "home_goals": 2, "away_goals": 0}
  ]
}
```

输出整体、联赛、置信度和分析模式分层的命中率、Brier、Log-loss、ROI 与最大回撤；未完赛场次保留在 `pending` 中。
