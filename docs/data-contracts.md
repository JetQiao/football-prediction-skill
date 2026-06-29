# 公共数据协议

稳定的 JSON 输入协议与 Skill 内说明保持一致：

- 比赛：`id/business_date/match_no/league/home/away/kickoff_at/sporttery_odds`。
- 特征：`team/elo/xg_for/xg_against/form_index/sample_size/source`。
- 市场：`home/away/home_odds/draw_odds/away_odds/source/updated_at`。
- 情报：`match_id/completeness/missing/evidences[]`；每条证据含 URL、发布时间、可信度、影响和对应赛果。

Schema 在 Python `domain.py` 中实施强校验，输入错误直接终止，不静默篡改概率或赔率。
