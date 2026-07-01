"""国家队名称 → 国旗（离线内联 PNG）。

竞彩里的国家队用中文简称；这里把它们映射到 ISO 3166-1 alpha-2（含英格兰/苏格兰/
威尔士/北爱等 gb 子区划）代码，再从随包打包的 flagcdn 公共域 w160 PNG 生成 base64
data-URI（国旗只在 ≤56px 圆形徽标里出现，w160 已足够清晰且体积有界）。
只有真正打包了对应国旗的国家才会返回代码；否则退回字母徽标（俱乐部即走此路径）。
"""

from __future__ import annotations

import base64
import functools
from importlib.resources import files

from ..providers.names import name_key

# 中文队名 → flagcdn 代码。键可写多个别名，都会经 name_key 归一后匹配。
NATIONAL_TEAM_CODES: dict[str, str] = {
    # —— 欧洲 ——
    "英格兰": "gb-eng", "苏格兰": "gb-sct", "威尔士": "gb-wls", "北爱尔兰": "gb-nir",
    "法国": "fr", "德国": "de", "西班牙": "es", "意大利": "it", "葡萄牙": "pt",
    "荷兰": "nl", "比利时": "be", "克罗地亚": "hr", "瑞士": "ch", "丹麦": "dk",
    "瑞典": "se", "挪威": "no", "波兰": "pl", "奥地利": "at", "乌克兰": "ua",
    "塞尔维亚": "rs", "捷克": "cz", "希腊": "gr", "土耳其": "tr", "俄罗斯": "ru",
    "匈牙利": "hu", "爱尔兰": "ie", "罗马尼亚": "ro", "斯洛伐克": "sk",
    "斯洛文尼亚": "si", "波黑": "ba", "波斯尼亚和黑塞哥维那": "ba", "北马其顿": "mk",
    "阿尔巴尼亚": "al", "芬兰": "fi", "冰岛": "is", "保加利亚": "bg", "黑山": "me",
    "格鲁吉亚": "ge", "卢森堡": "lu", "白俄罗斯": "by", "以色列": "il",
    # —— 南美 ——
    "巴西": "br", "阿根廷": "ar", "乌拉圭": "uy", "哥伦比亚": "co", "智利": "cl",
    "秘鲁": "pe", "厄瓜多尔": "ec", "巴拉圭": "py", "玻利维亚": "bo", "委内瑞拉": "ve",
    # —— 中北美及加勒比 ——
    "美国": "us", "墨西哥": "mx", "加拿大": "ca", "哥斯达黎加": "cr", "巴拿马": "pa",
    "洪都拉斯": "hn", "牙买加": "jm", "萨尔瓦多": "sv", "危地马拉": "gt",
    "特立尼达和多巴哥": "tt", "海地": "ht", "库拉索": "cw",
    # —— 非洲 ——
    "塞内加尔": "sn", "摩洛哥": "ma", "埃及": "eg", "突尼斯": "tn", "阿尔及利亚": "dz",
    "尼日利亚": "ng", "喀麦隆": "cm", "加纳": "gh", "科特迪瓦": "ci", "马里": "ml",
    "南非": "za", "刚果金": "cd", "刚果（金）": "cd", "民主刚果": "cd", "刚果民主共和国": "cd",
    "刚果布": "cg", "刚果（布）": "cg", "布基纳法索": "bf", "几内亚": "gn", "佛得角": "cv",
    "赞比亚": "zm", "安哥拉": "ao", "加蓬": "ga", "乌干达": "ug", "贝宁": "bj",
    "莫桑比克": "mz", "赤道几内亚": "gq", "毛里塔尼亚": "mr", "纳米比亚": "na",
    "津巴布韦": "zw", "肯尼亚": "ke", "坦桑尼亚": "tz", "多哥": "tg", "冈比亚": "gm",
    # —— 亚洲及大洋洲 ——
    "日本": "jp", "韩国": "kr", "南韩": "kr", "澳大利亚": "au", "伊朗": "ir",
    "沙特阿拉伯": "sa", "沙特": "sa", "卡塔尔": "qa", "阿联酋": "ae", "伊拉克": "iq",
    "中国": "cn", "国足": "cn", "乌兹别克斯坦": "uz", "约旦": "jo", "阿曼": "om",
    "巴林": "bh", "科威特": "kw", "叙利亚": "sy", "朝鲜": "kp", "泰国": "th",
    "越南": "vn", "印度尼西亚": "id", "马来西亚": "my", "印度": "in", "巴勒斯坦": "ps",
    "黎巴嫩": "lb", "塔吉克斯坦": "tj", "土库曼斯坦": "tm", "吉尔吉斯斯坦": "kg",
    "新西兰": "nz",
}

_CODE_BY_KEY: dict[str, str] = {name_key(name): code for name, code in NATIONAL_TEAM_CODES.items()}


@functools.lru_cache(maxsize=None)
def flag_data_uri(code: str) -> str | None:
    """把随包 PNG 编码成离线 data-URI；未打包对应国旗时返回 None。"""

    resource = files("football_prediction.reporting").joinpath("assets", "flags", f"{code}.png")
    if not resource.is_file():
        return None
    encoded = base64.b64encode(resource.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def flag_for(team: str) -> str | None:
    """返回该队可用的国旗代码；非国家队或缺少资源时返回 None（走字母徽标）。"""

    code = _CODE_BY_KEY.get(name_key(team))
    if code and flag_data_uri(code):
        return code
    return None
