"""可追溯的本地模型注册表。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..providers.names import name_key
from .calibration import TemperatureCalibrator
from .dixon_coles import DixonColesModel
from .ensemble import LogPoolEnsemble


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "model"


@dataclass(frozen=True)
class ModelMetadata:
    version: str
    competition: str
    trained_until: str
    sample_size: int
    calibration_status: str = "provisional"
    calibration_sample_size: int = 0
    devig_method: str = "multiplicative"
    promoted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    aliases: tuple[str, ...] = ()
    validation: dict[str, Any] = field(default_factory=dict)

    def matches(self, competition: str) -> bool:
        target = name_key(competition)
        return target in {name_key(self.competition), *(name_key(alias) for alias in self.aliases)}


@dataclass(frozen=True)
class ModelBundle:
    metadata: ModelMetadata
    model: DixonColesModel
    calibrator: TemperatureCalibrator | None = None
    ensemble: LogPoolEnsemble | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": asdict(self.metadata),
            "model": {
                "teams": list(self.model.teams),
                "attack": self.model.attack or {},
                "defence": self.model.defence or {},
                "intercept": self.model.intercept,
                "home_advantage": self.model.home_advantage,
                "rho": self.model.rho,
                "fitted_at": self.model.fitted_at,
            },
            "calibrator": asdict(self.calibrator) if self.calibrator else None,
            "ensemble": asdict(self.ensemble) if self.ensemble else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelBundle":
        raw_metadata = payload["metadata"]
        metadata = ModelMetadata(
            version=raw_metadata["version"],
            competition=raw_metadata["competition"],
            trained_until=raw_metadata["trained_until"],
            sample_size=int(raw_metadata["sample_size"]),
            calibration_status=raw_metadata.get("calibration_status", "provisional"),
            calibration_sample_size=int(raw_metadata.get("calibration_sample_size", 0)),
            devig_method=raw_metadata.get("devig_method", "multiplicative"),
            promoted=bool(raw_metadata.get("promoted", False)),
            created_at=raw_metadata.get("created_at", ""),
            aliases=tuple(raw_metadata.get("aliases", ())),
            validation=dict(raw_metadata.get("validation", {})),
        )
        raw_model = payload["model"]
        model = DixonColesModel(
            teams=tuple(raw_model.get("teams", ())),
            attack={str(key): float(value) for key, value in (raw_model.get("attack") or {}).items()},
            defence={str(key): float(value) for key, value in (raw_model.get("defence") or {}).items()},
            intercept=float(raw_model.get("intercept", 0)),
            home_advantage=float(raw_model.get("home_advantage", 0)),
            rho=float(raw_model.get("rho", -0.08)),
            fitted_at=raw_model.get("fitted_at"),
        )
        raw_calibrator = payload.get("calibrator")
        calibrator = (
            TemperatureCalibrator(
                temperature=float(raw_calibrator["temperature"]),
                trained_until=raw_calibrator.get("trained_until"),
            )
            if raw_calibrator
            else None
        )
        raw_ensemble = payload.get("ensemble")
        ensemble = (
            LogPoolEnsemble(
                market_weight=float(raw_ensemble["market_weight"]),
                outcome_biases=tuple(
                    float(value)
                    for value in raw_ensemble.get("outcome_biases", (0.0, 0.0, 0.0))
                ),
                trained_until=raw_ensemble.get("trained_until"),
                sample_size=int(raw_ensemble.get("sample_size", 0)),
            )
            if raw_ensemble
            else None
        )
        return cls(metadata, model, calibrator, ensemble)


class ModelRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / "registry.json"

    def _read_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"schema_version": "1.0", "models": []}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def register(self, bundle: ModelBundle, *, promote: bool | None = None) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        promoted = bundle.metadata.promoted if promote is None else promote
        metadata = ModelMetadata(**{**asdict(bundle.metadata), "promoted": promoted})
        stored = ModelBundle(metadata, bundle.model, bundle.calibrator, bundle.ensemble)
        path = self.root / f"{_safe_name(metadata.version)}.json"
        path.write_text(
            json.dumps(stored.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        index = self._read_index()
        rows = [row for row in index.get("models", []) if row.get("version") != metadata.version]
        if promoted:
            for row in rows:
                row_names = {
                    name_key(row.get("competition", "")),
                    *(name_key(alias) for alias in row.get("aliases", [])),
                }
                new_names = {
                    name_key(metadata.competition),
                    *(name_key(alias) for alias in metadata.aliases),
                }
                if row_names & new_names:
                    row["promoted"] = False
        rows.append(
            {
                "version": metadata.version,
                "competition": metadata.competition,
                "aliases": list(metadata.aliases),
                "trained_until": metadata.trained_until,
                "calibration_status": metadata.calibration_status,
                "promoted": promoted,
                "path": str(path),
            }
        )
        index["models"] = sorted(rows, key=lambda row: (row.get("competition", ""), row.get("trained_until", "")))
        self._write_index(index)
        return path

    def load(self, version: str) -> ModelBundle:
        index = self._read_index()
        row = next((item for item in index.get("models", []) if item.get("version") == version), None)
        if not row:
            raise ValueError(f"模型注册表中不存在版本：{version}")
        return ModelBundle.from_dict(json.loads(Path(row["path"]).read_text(encoding="utf-8")))

    def resolve(
        self,
        competition: str,
        *,
        as_of: str | None = None,
        allow_challenger: bool = False,
    ) -> ModelBundle | None:
        candidates: list[ModelBundle] = []
        for row in self._read_index().get("models", []):
            try:
                bundle = ModelBundle.from_dict(json.loads(Path(row["path"]).read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if not bundle.metadata.matches(competition):
                continue
            if as_of and bundle.metadata.trained_until >= as_of[:10]:
                continue
            candidates.append(bundle)
        if not candidates:
            return None
        promoted = [bundle for bundle in candidates if bundle.metadata.promoted]
        if not promoted and not allow_challenger:
            return None
        pool = promoted or candidates
        return max(pool, key=lambda bundle: bundle.metadata.trained_until)

    def promote(self, version: str) -> ModelBundle:
        bundle = self.load(version)
        promoted = ModelBundle(
            ModelMetadata(**{**asdict(bundle.metadata), "promoted": True}),
            bundle.model,
            bundle.calibrator,
            bundle.ensemble,
        )
        self.register(promoted, promote=True)
        return promoted

    def list(self) -> list[dict[str, Any]]:
        return list(self._read_index().get("models", []))
