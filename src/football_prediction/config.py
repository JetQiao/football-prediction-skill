"""运行配置与用户数据目录。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是数字") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"环境变量 {name} 必须是 true/false")


@dataclass(frozen=True)
class AppPaths:
    """把缓存、配置和报告与 Skill 安装目录彻底分离。"""

    data: Path = field(default_factory=lambda: Path(user_data_dir("football-prediction-skill", "JetQiao")))
    cache: Path = field(default_factory=lambda: Path(user_cache_dir("football-prediction-skill", "JetQiao")))
    config: Path = field(default_factory=lambda: Path(user_config_dir("football-prediction-skill", "JetQiao")))

    @property
    def reports(self) -> Path:
        return self.data / "reports"

    @property
    def snapshots(self) -> Path:
        return self.data / "snapshots"

    @property
    def models(self) -> Path:
        return self.data / "models"

    def ensure(self) -> "AppPaths":
        for path in (self.data, self.cache, self.config, self.reports, self.snapshots, self.models):
            path.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class Settings:
    """只保留可解释且能通过回测固化的模型参数。"""

    sporttery_api_url: str | None = field(default_factory=lambda: os.getenv("SPORTTERY_API_URL"))
    sporttery_api_key: str | None = field(default_factory=lambda: os.getenv("SPORTTERY_API_KEY"))
    api_football_key: str | None = field(default_factory=lambda: os.getenv("API_FOOTBALL_KEY"))
    odds_api_key: str | None = field(default_factory=lambda: os.getenv("THE_ODDS_API_KEY"))
    auto_clubelo: bool = field(default_factory=lambda: _env_bool("FOOTBALL_AUTO_CLUBELO", True))
    market_weight: float = field(default_factory=lambda: _env_float("FOOTBALL_MARKET_WEIGHT", 0.58))
    official_market_weight: float = field(
        default_factory=lambda: _env_float("FOOTBALL_OFFICIAL_MARKET_WEIGHT", 0.35)
    )
    value_threshold: float = field(default_factory=lambda: _env_float("FOOTBALL_VALUE_THRESHOLD", 0.05))
    max_intel_logit: float = field(default_factory=lambda: _env_float("FOOTBALL_MAX_INTEL_LOGIT", 0.12))
    request_timeout: float = field(default_factory=lambda: _env_float("FOOTBALL_REQUEST_TIMEOUT", 15.0))
    paths: AppPaths = field(default_factory=AppPaths)

    def validate(self) -> "Settings":
        if not 0 <= self.market_weight <= 1:
            raise ValueError("market_weight 必须位于 0~1")
        if not 0 <= self.official_market_weight <= 1:
            raise ValueError("official_market_weight 必须位于 0~1")
        if not 0 <= self.value_threshold <= 1:
            raise ValueError("value_threshold 必须位于 0~1")
        if not 0 <= self.max_intel_logit <= 0.25:
            raise ValueError("max_intel_logit 必须位于 0~0.25")
        self.paths.ensure()
        return self
