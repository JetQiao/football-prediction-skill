"""情报输入校验，防止无来源的 LLM 判断进入概率模型。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain import AvailabilityFact, IntelEvidence, MatchIntel, Outcome


def _datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def validate_intel(
    intel: MatchIntel,
    *,
    kickoff_at: str | None = None,
    as_of: str | None = None,
) -> MatchIntel:
    kickoff = _datetime(kickoff_at) if kickoff_at else None
    cutoff = _datetime(as_of) if as_of else None
    for evidence in intel.evidences:
        published = _datetime(evidence.published_at)
        if kickoff:
            if published.tzinfo is None and kickoff.tzinfo is not None:
                published = published.replace(tzinfo=kickoff.tzinfo)
            if kickoff.tzinfo is None and published.tzinfo is not None:
                kickoff = kickoff.replace(tzinfo=published.tzinfo)
            if published > kickoff:
                raise ValueError(f"情报发布时间晚于开赛时间，存在未来数据泄漏：{evidence.title}")
        if cutoff:
            comparable = published
            if comparable.tzinfo is None and cutoff.tzinfo is not None:
                comparable = comparable.replace(tzinfo=cutoff.tzinfo)
            if cutoff.tzinfo is None and comparable.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=comparable.tzinfo)
            if comparable > cutoff:
                raise ValueError(f"情报发布时间晚于预测截点，存在未来数据泄漏：{evidence.title}")
    fingerprints: set[str] = set()
    for fact in intel.facts:
        if fact.event_fingerprint in fingerprints:
            raise ValueError(f"阵容事实重复：{fact.player}")
        fingerprints.add(fact.event_fingerprint)
        observed = _datetime(fact.observed_at)
        if kickoff:
            comparable = observed
            if comparable.tzinfo is None and kickoff.tzinfo is not None:
                comparable = comparable.replace(tzinfo=kickoff.tzinfo)
            if comparable >= kickoff:
                raise ValueError(f"阵容事实时间不早于开赛，存在未来数据泄漏：{fact.player}")
        if cutoff:
            comparable = observed
            if comparable.tzinfo is None and cutoff.tzinfo is not None:
                comparable = comparable.replace(tzinfo=cutoff.tzinfo)
            if comparable > cutoff:
                raise ValueError(f"阵容事实时间晚于预测截点，存在未来数据泄漏：{fact.player}")
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
        facts = tuple(
            AvailabilityFact(
                event_type=item["event_type"],
                team=item["team"],
                player=item["player"],
                status=item["status"],
                observed_at=item["observed_at"],
                source_url=item["source_url"],
                credibility=float(item.get("credibility", 0.8)),
                position=item.get("position", ""),
                expected_minutes_delta=float(item.get("expected_minutes_delta", -45)),
                reason=item.get("reason", ""),
                event_fingerprint=item.get("event_fingerprint", ""),
            )
            for item in row.get("facts", [])
        )
        result[row["match_id"]] = MatchIntel(
            match_id=row["match_id"],
            evidences=evidences,
            facts=facts,
            completeness=float(row.get("completeness", 0)),
            missing=tuple(row.get("missing", [])),
        )
    return result
