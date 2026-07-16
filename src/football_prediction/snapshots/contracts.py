"""不可变赛前快照的数据契约。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "2.0"


def parse_timestamp(value: str, *, business_date: str | None = None) -> datetime:
    """解析 ISO 时间；只有时分秒时使用业务日期和上海时区补齐。"""

    raw = value.strip()
    if not raw:
        raise ValueError("时间字段不能为空")
    if len(raw) <= 8 and ":" in raw:
        if not business_date:
            raise ValueError(f"时间 {value!r} 缺少业务日期")
        raw = f"{business_date}T{raw}"
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed


def parse_as_of(value: str | None, *, now: datetime | None = None) -> datetime:
    """解析预测截点；默认使用当前本地时间。"""

    if value in (None, "", "now", "现在"):
        current = now or datetime.now().astimezone()
        return current if current.tzinfo else current.replace(tzinfo=LOCAL_TZ)
    return parse_timestamp(value)


def canonical_payload_hash(payload: Any) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SnapshotEnvelope:
    dataset: str
    business_date: str
    as_of: str
    observed_at: str
    source: str
    source_event_id: str
    payload: Any
    schema_version: str = SCHEMA_VERSION
    payload_hash: str = field(default="")
    snapshot_id: str = field(default="")

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.business_date)
        except ValueError as exc:
            raise ValueError(f"非法业务日期：{self.business_date}") from exc
        if not self.dataset.strip():
            raise ValueError("dataset 不能为空")
        if not self.source.strip():
            raise ValueError("source 不能为空")
        if not self.source_event_id.strip():
            raise ValueError("source_event_id 不能为空")
        as_of = parse_timestamp(self.as_of, business_date=self.business_date)
        observed_at = parse_timestamp(self.observed_at, business_date=self.business_date)
        if observed_at > as_of:
            raise ValueError("observed_at 不能晚于 as_of")
        if not self.payload_hash:
            object.__setattr__(self, "payload_hash", canonical_payload_hash(self.payload))
        if not self.snapshot_id:
            # payload_hash 只描述内容；snapshot_id 同时包含事件时间和来源，
            # 避免“内容未变化”时把两个不同预测截点错误折叠成一个快照。
            object.__setattr__(
                self,
                "snapshot_id",
                canonical_payload_hash(
                    {
                        "dataset": self.dataset,
                        "business_date": self.business_date,
                        "as_of": self.as_of,
                        "observed_at": self.observed_at,
                        "source": self.source,
                        "source_event_id": self.source_event_id,
                        "schema_version": self.schema_version,
                        "payload_hash": self.payload_hash,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "business_date": self.business_date,
            "as_of": self.as_of,
            "observed_at": self.observed_at,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "payload_hash": self.payload_hash,
            "payload": self.payload,
        }
