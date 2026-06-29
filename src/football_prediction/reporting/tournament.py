"""赛事排名概率的自包含 HTML。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Mapping


def write_tournament_report(
    result: Mapping[str, Mapping[str, Mapping[int, float]]],
    path: Path,
    *,
    runs: int,
) -> Path:
    sections = []
    for group, teams in result.items():
        rows = []
        for team, ranks in sorted(teams.items(), key=lambda item: item[1].get(1, 0), reverse=True):
            cells = "".join(
                f'<td><span class="bar" style="--p:{probability:.4f}"></span>{probability:.1%}</td>'
                for _, probability in sorted(ranks.items())
            )
            rows.append(f"<tr><th>{html.escape(team)}</th>{cells}</tr>")
        max_rank = max((max(ranks) for ranks in teams.values()), default=0)
        headers = "".join(f"<th>第 {rank} 名</th>" for rank in range(1, max_rank + 1))
        sections.append(
            f'<section><h2>{html.escape(group)} 组</h2><div class="table"><table><thead><tr><th>球队</th>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>'
        )
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>赛事排名概率推演</title><style>
    :root{{--bg:#071018;--panel:#101d29;--line:#263b4c;--text:#edf7fb;--muted:#8ea4b3;--cyan:#32d8c5;--red:#ff6b78}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#15344b,transparent 36%),var(--bg);color:var(--text);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}}main{{width:min(1100px,calc(100% - 28px));margin:auto;padding:50px 0}}.eyebrow{{color:var(--cyan);font-weight:800;letter-spacing:.16em;text-transform:uppercase}}h1{{font-size:clamp(32px,6vw,58px);margin:8px 0}}p{{color:var(--muted)}}section{{margin:30px 0;padding:20px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#112230,#0a151e)}}h2{{margin-top:0}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:640px}}th,td{{padding:13px;text-align:right;border-bottom:1px solid var(--line);position:relative}}th:first-child{{text-align:left}}td{{font-variant-numeric:tabular-nums}}.bar{{position:absolute;inset:5px auto 5px 0;width:calc(var(--p)*100%);background:linear-gradient(90deg,rgba(50,216,197,.08),rgba(50,216,197,.35));border-radius:5px;z-index:0}}td{{isolation:isolate}}footer{{margin-top:35px;color:var(--muted);border-top:1px solid var(--line);padding-top:20px}}footer strong{{color:var(--red)}}
    </style></head><body><main><div class="eyebrow">Monte Carlo · Tournament</div><h1>赛事排名概率推演</h1><p>{runs:,} 次模拟；当前通用规则按积分、净胜球、进球数排序，不包含最佳第三名。</p>{"".join(sections)}<footer><strong>概率不是承诺。</strong> 本报告仅供研究参考；具体赛事如优先比较相互战绩，需加载对应赛制规则。</footer></main><script type="application/json" id="result">{payload}</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path
