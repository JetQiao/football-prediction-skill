# 赛事推演

将每场未赛比赛写成 `group/home/away/home_prob/draw_prob/away_prob`。已赛比赛附加 `played_score: [主队进球, 客队进球]`。

```json
{
  "seed": 42,
  "fixtures": [{
    "group": "A",
    "home": "A1",
    "away": "A2",
    "home_prob": 0.46,
    "draw_prob": 0.29,
    "away_prob": 0.25
  }]
}
```

运行 `football-predict tournament fixtures.json --runs 10000`，交付 `tournament_report.html`，JSON 只作为机器可读副产物。

当前通用排名顺序为积分、净胜球、进球数。具体赛事若先比较相互战绩，必须在解释中标注差异并扩展规则后再给正式结论。最佳第三名不在支持范围内。
