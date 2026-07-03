"""从 Dixon-Coles 比分矩阵推导竞彩各玩法，纯函数、无网络依赖。

核心思路：胜平负的最终概率经过市场/情报融合后可能与纯模型矩阵不一致，
因此先把比分矩阵按最终胜平负概率做条件缩放（tilt），使所有衍生玩法
（让球、大小球、双方进球、双重机会、半全场）与头部概率自洽。
"""

from __future__ import annotations

from ..domain import Probability3
from ..modeling.dixon_coles import poisson_pmf
from ..modeling.matrix import tilt_matrix as _tilt_matrix

OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
# 经验上首回合进球占比略低于半场对半场。
FIRST_HALF_SHARE = 0.45


def tilt_matrix(matrix: tuple[tuple[float, ...], ...], final: Probability3) -> list[list[float]]:
    """把比分矩阵缩放到与最终胜平负概率一致，再归一化。"""
    return [list(row) for row in _tilt_matrix(matrix, final)]


def over_under(matrix: list[list[float]], line: float) -> dict[str, float]:
    over = sum(
        matrix[i][j]
        for i in range(len(matrix))
        for j in range(len(matrix[i]))
        if i + j > line
    )
    return {"line": line, "over": over, "under": 1.0 - over}


def both_teams_to_score(matrix: list[list[float]]) -> dict[str, float]:
    yes = sum(
        matrix[i][j]
        for i in range(1, len(matrix))
        for j in range(1, len(matrix[i]))
    )
    return {"yes": yes, "no": 1.0 - yes}


def double_chance(final: Probability3) -> dict[str, float]:
    return {
        "home_draw": final.home + final.draw,
        "home_away": final.home + final.away,
        "draw_away": final.draw + final.away,
    }


def goals_distribution(matrix: list[list[float]], cap: int = 5) -> list[dict[str, float | str]]:
    dist: dict[int, float] = {}
    for i in range(len(matrix)):
        for j in range(len(matrix[i])):
            total = i + j
            key = total if total < cap else cap
            dist[key] = dist.get(key, 0.0) + matrix[i][j]
    rows: list[dict[str, float | str]] = [{"label": str(k), "p": dist.get(k, 0.0)} for k in range(cap)]
    rows.append({"label": f"{cap}+", "p": dist.get(cap, 0.0)})
    return rows


def handicap_result(matrix: list[list[float]], line: float | None) -> dict[str, float] | None:
    """竞彩让球胜平负：主队进球 + 让球数 后比较。让球数为整数，允许走平。"""
    if line is None:
        return None
    home = draw = away = 0.0
    for i in range(len(matrix)):
        for j in range(len(matrix[i])):
            adjusted = i + line
            probability = matrix[i][j]
            if adjusted > j:
                home += probability
            elif adjusted == j:
                draw += probability
            else:
                away += probability
    return {"line": line, "home": home, "draw": draw, "away": away}


def half_full(xg_home: float, xg_away: float, cap: int = 6) -> list[list[float]]:
    """用上下半场独立泊松估计半全场 3x3 联合概率。行=半场，列=全场，顺序 主/平/客。"""
    a = FIRST_HALF_SHARE
    lh1, la1 = xg_home * a, xg_away * a
    lh2, la2 = xg_home * (1 - a), xg_away * (1 - a)

    def sign(home_goals: int, away_goals: int) -> int:
        return 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2

    first = [[poisson_pmf(h, lh1) * poisson_pmf(a_, la1) for a_ in range(cap + 1)] for h in range(cap + 1)]
    second = [[poisson_pmf(h, lh2) * poisson_pmf(a_, la2) for a_ in range(cap + 1)] for h in range(cap + 1)]
    grid = [[0.0, 0.0, 0.0] for _ in range(3)]
    for h1 in range(cap + 1):
        for a1 in range(cap + 1):
            p1 = first[h1][a1]
            if p1 < 1e-9:
                continue
            ht = sign(h1, a1)
            for h2 in range(cap + 1):
                for a2 in range(cap + 1):
                    probability = p1 * second[h2][a2]
                    if probability < 1e-12:
                        continue
                    grid[ht][sign(h1 + h2, a1 + a2)] += probability
    total = sum(sum(row) for row in grid) or 1.0
    return [[value / total for value in row] for row in grid]


def _argmax2(grid: list[list[float]]) -> tuple[int, int, float]:
    best = (0, 0, grid[0][0])
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            if value > best[2]:
                best = (i, j, value)
    return best


def derive_markets(
    matrix: tuple[tuple[float, ...], ...],
    final: Probability3,
    xg_home: float,
    xg_away: float,
    handicap: float | None,
) -> dict:
    """汇总所有衍生玩法，并给出每个玩法的推荐选项与概率。"""
    tilted = tilt_matrix(matrix, final)
    ou25 = over_under(tilted, 2.5)
    ou15 = over_under(tilted, 1.5)
    ou35 = over_under(tilted, 3.5)
    btts = both_teams_to_score(tilted)
    dc = double_chance(final)
    hcp = handicap_result(tilted, handicap)
    htft = half_full(xg_home, xg_away)

    ht, ft, htft_p = _argmax2(htft)
    htft_pick = f"{('主', '平', '客')[ht]} / {('主', '平', '客')[ft]}"

    dc_items = [
        ("双胜 1X（主胜或平）", dc["home_draw"]),
        ("不败 12（主胜或客胜）", dc["home_away"]),
        ("客不败 X2（平或客胜）", dc["draw_away"]),
    ]
    dc_best = max(dc_items, key=lambda item: item[1])

    handicap_card = None
    if hcp is not None:
        sign = "+" if hcp["line"] > 0 else ""
        pick = max(("home", "draw", "away"), key=lambda key: hcp[key])
        handicap_card = {
            "line_label": f"{sign}{int(hcp['line']) if float(hcp['line']).is_integer() else hcp['line']}",
            "home": hcp["home"],
            "draw": hcp["draw"],
            "away": hcp["away"],
            "pick_label": OUTCOME_LABELS[pick],
            "pick_prob": hcp[pick],
        }

    return {
        "tilted_matrix": tilted,
        "over_under": {
            "main": ou25,
            "lines": [ou15, ou25, ou35],
            "pick_label": "大球 2.5" if ou25["over"] >= 0.5 else "小球 2.5",
            "pick_prob": max(ou25["over"], ou25["under"]),
        },
        "btts": {
            **btts,
            "pick_label": "双方进球" if btts["yes"] >= 0.5 else "非双方进球",
            "pick_prob": max(btts["yes"], btts["no"]),
        },
        "double_chance": {"items": dc_items, "best_label": dc_best[0], "best_prob": dc_best[1]},
        "handicap": handicap_card,
        "htft": {"grid": htft, "pick_label": htft_pick, "pick_prob": htft_p},
        "goals_distribution": goals_distribution(tilted),
    }


def plain_summary(
    home: str,
    away: str,
    final: Probability3,
    xg_home: float,
    xg_away: float,
    top_score_label: str,
    markets: dict,
) -> str:
    """生成一句话白话结论，让非专业用户也能看懂。"""
    favourite = final.best()
    pmax = final.get(favourite)
    if favourite.value == "draw":
        lead = f"两队实力接近，模型认为平局概率最高（{pmax:.0%}）"
    else:
        name = home if favourite.value == "home" else away
        if pmax >= 0.55:
            lead = f"模型明显看好{name}（{pmax:.0%}）"
        elif pmax >= 0.45:
            lead = f"模型略微看好{name}（{pmax:.0%}），但优势不大"
        else:
            lead = (
                f"接近五五开（{home} {final.home:.0%} / 平 {final.draw:.0%} / {away} {final.away:.0%}），"
                f"{name}略占上风"
            )

    total = xg_home + xg_away
    goals_desc = "进球可能偏多" if total >= 3.0 else "进球偏少" if total <= 2.2 else "进球中等"
    over = markets["over_under"]["main"]["over"]
    ou_desc = "盘口偏大球" if over >= 0.55 else "盘口偏小球" if over <= 0.45 else "大小球接近五五开"

    tail = ""
    yes = markets["btts"]["yes"]
    if yes >= 0.58:
        tail = "双方都有较大机会破门。"
    elif yes <= 0.42:
        tail = "存在一方被零封的可能。"

    return f"{lead}；最可能比分 {top_score_label}，{goals_desc}，{ou_desc}。{tail}".strip()
