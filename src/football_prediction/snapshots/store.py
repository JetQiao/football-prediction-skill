"""用 DuckDB 管目录、用 Parquet 保存不可变快照。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import SnapshotEnvelope


def _safe_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return normalized.strip("-") or "unknown"


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


class SnapshotStore:
    """本地、幂等、无服务依赖的快照仓库。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.parquet_root = root / "parquet"
        self.json_root = root / "json"
        self.db_path = root / "catalog.duckdb"

    @staticmethod
    def _duckdb():
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("缺少 DuckDB，请重新安装项目依赖：pip install -e .") from exc
        return duckdb

    def ensure(self) -> "SnapshotStore":
        self.parquet_root.mkdir(parents=True, exist_ok=True)
        self.json_root.mkdir(parents=True, exist_ok=True)
        duckdb = self._duckdb()
        with duckdb.connect(str(self.db_path)) as connection:
            existing = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'snapshots'
                """
            ).fetchall()
            columns = {row[0] for row in existing}
            if columns and "snapshot_id" not in columns:
                connection.execute("ALTER TABLE snapshots RENAME TO snapshots_legacy")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id VARCHAR PRIMARY KEY,
                    payload_hash VARCHAR NOT NULL,
                    dataset VARCHAR NOT NULL,
                    business_date DATE NOT NULL,
                    as_of TIMESTAMPTZ NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    source VARCHAR NOT NULL,
                    source_event_id VARCHAR NOT NULL,
                    schema_version VARCHAR NOT NULL,
                    parquet_path VARCHAR NOT NULL,
                    json_path VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT current_timestamp
                )
                """
            )
            if columns and "snapshot_id" not in columns:
                connection.execute(
                    """
                    INSERT INTO snapshots (
                        snapshot_id, payload_hash, dataset, business_date, as_of, observed_at,
                        source, source_event_id, schema_version, parquet_path, json_path, created_at
                    )
                    SELECT payload_hash, payload_hash, dataset, business_date, as_of, observed_at,
                           source, source_event_id, schema_version, parquet_path, json_path, created_at
                    FROM snapshots_legacy
                    """
                )
                connection.execute("DROP TABLE snapshots_legacy")
        return self

    def write(self, envelope: SnapshotEnvelope) -> tuple[Path, Path]:
        self.ensure()
        dataset = _safe_segment(envelope.dataset)
        as_of_segment = _safe_segment(envelope.as_of)
        relative = Path(dataset) / envelope.business_date / as_of_segment
        parquet_dir = self.parquet_root / relative
        json_dir = self.json_root / relative
        parquet_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        stem = envelope.snapshot_id[:16]
        parquet_path = parquet_dir / f"{stem}.parquet"
        json_path = json_dir / f"{stem}.json"

        if not json_path.exists():
            json_path.write_text(
                json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        duckdb = self._duckdb()
        with duckdb.connect(str(self.db_path)) as connection:
            exists = connection.execute(
                "SELECT parquet_path, json_path FROM snapshots WHERE snapshot_id = ?",
                [envelope.snapshot_id],
            ).fetchone()
            if exists:
                return Path(exists[0]), Path(exists[1])

            connection.execute(
                """
                CREATE TEMP TABLE snapshot_row (
                    snapshot_id VARCHAR,
                    payload_hash VARCHAR,
                    dataset VARCHAR,
                    business_date VARCHAR,
                    as_of VARCHAR,
                    observed_at VARCHAR,
                    source VARCHAR,
                    source_event_id VARCHAR,
                    schema_version VARCHAR,
                    payload JSON
                )
                """
            )
            connection.execute(
                "INSERT INTO snapshot_row VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    envelope.snapshot_id,
                    envelope.payload_hash,
                    envelope.dataset,
                    envelope.business_date,
                    envelope.as_of,
                    envelope.observed_at,
                    envelope.source,
                    envelope.source_event_id,
                    envelope.schema_version,
                    json.dumps(envelope.payload, ensure_ascii=False, separators=(",", ":")),
                ],
            )
            connection.execute(
                f"COPY snapshot_row TO '{_sql_path(parquet_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            connection.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, payload_hash, dataset, business_date, as_of, observed_at, source,
                    source_event_id, schema_version, parquet_path, json_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    envelope.snapshot_id,
                    envelope.payload_hash,
                    envelope.dataset,
                    envelope.business_date,
                    envelope.as_of,
                    envelope.observed_at,
                    envelope.source,
                    envelope.source_event_id,
                    envelope.schema_version,
                    str(parquet_path),
                    str(json_path),
                ],
            )
        return parquet_path, json_path

    def latest(self, dataset: str, business_date: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        self.ensure()
        duckdb = self._duckdb()
        query = """
            SELECT json_path
            FROM snapshots
            WHERE dataset = ? AND business_date = ?
        """
        params: list[Any] = [dataset, business_date]
        if as_of:
            query += " AND as_of <= ?"
            params.append(as_of)
        query += " ORDER BY as_of DESC, created_at DESC LIMIT 1"
        with duckdb.connect(str(self.db_path), read_only=True) as connection:
            row = connection.execute(query, params).fetchone()
        if not row:
            return None
        return json.loads(Path(row[0]).read_text(encoding="utf-8"))

    def catalog(self, dataset: str | None = None) -> list[dict[str, Any]]:
        self.ensure()
        duckdb = self._duckdb()
        query = """
            SELECT snapshot_id, payload_hash, dataset, CAST(business_date AS VARCHAR), CAST(as_of AS VARCHAR),
                   source, schema_version, parquet_path
            FROM snapshots
        """
        params: list[Any] = []
        if dataset:
            query += " WHERE dataset = ?"
            params.append(dataset)
        query += " ORDER BY as_of DESC"
        with duckdb.connect(str(self.db_path), read_only=True) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "snapshot_id": row[0],
                "payload_hash": row[1],
                "dataset": row[2],
                "business_date": row[3],
                "as_of": row[4],
                "source": row[5],
                "schema_version": row[6],
                "parquet_path": row[7],
            }
            for row in rows
        ]
