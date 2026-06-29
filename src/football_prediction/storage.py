"""原子化 JSON 存储、缓存与运行清单。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .domain import to_dict


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> Path:
    """先写临时文件再替换，避免中断留下半截快照。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(to_dict(value), ensure_ascii=False, indent=2, sort_keys=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path
