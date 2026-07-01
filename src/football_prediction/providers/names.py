"""跨数据源球队名称归一化。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def name_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    normalized = re.sub(r"\b(fc|afc|cf|sc|club|football)\b", "", normalized, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", normalized.lower())


@dataclass
class TeamNameResolver:
    aliases: dict[str, str] = field(default_factory=dict)

    def register(self, canonical: str, *aliases: str) -> None:
        for value in (canonical, *aliases):
            self.aliases[name_key(value)] = canonical

    def resolve(self, value: str) -> str:
        return self.aliases.get(name_key(value), value.strip())
