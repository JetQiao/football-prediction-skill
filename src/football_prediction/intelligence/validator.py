"""情报输入校验，防止无来源的 LLM 判断进入概率模型。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain import IntelEvidence, MatchIntel, Outcome


def _datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def validate_intel(intel: MatchIntel, *, kickoff_at: str | None = None) -> MatchIntel:
    if kickoff_at:
        kickoff = _datetime(kickoff_at)
        for evidence in intel.evidences:
            published = _datetime(evidence.published_at)
            if published.tzinfo is None and kickoff.tzinfo is not None:
                published = published.replace(tzinfo=kickoff.tzinfo)
            if kickoff.tzinfo is None and published.tzinfo is not None:
                kickoff = kickoff.replace(tzinfo=published.tzinfo)
            if published > kickoff:
                raise ValueError(f"情报发布时间晚于开赛时间，存在未来数据泄漏：{evidence.title}")
    return intel


def load_intel(path: Path) -> dict[str, MatchIntel]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = payload.get("matches", payload)
    result: dict[str, MatchIntel] = {}
    for row in rows:
        evidences = tuple(
            IntelEvidence(
                title=item["title"],
                url=item["url"],
                published_at=item["published_at"],
                credibility=float(item["credibility"]),
                impact=float(item["impact"]),
                outcome=Outcome(item["outcome"]),
                note=item.get("note", ""),
            )
            for item in row.get("evidences", [])
        )
        result[row["match_id"]] = MatchIntel(
            match_id=row["match_id"],
            evidences=evidences,
            completeness=float(row.get("completeness", 0)),
            missing=tuple(row.get("missing", [])),
        )
    return result
