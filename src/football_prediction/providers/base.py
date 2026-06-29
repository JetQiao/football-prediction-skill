"""Provider 公共网络能力。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping


class ProviderError(RuntimeError):
    """数据源不可用或响应契约已变化。"""


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/124 Safari/537.36 football-prediction-skill/0.1"
)


def fetch_json(
    url: str,
    *,
    timeout: float = 15,
    headers: Mapping[str, str] | None = None,
    cache_dir: Path | None = None,
    cache_ttl: int = 30,
) -> Any:
    cache_path: Path | None = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = cache_dir / f"{digest}.json"
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime <= cache_ttl:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    merged_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    merged_headers.update(headers or {})
    request = urllib.request.Request(url, headers=merged_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(f"请求数据源失败：{url} ({exc})") from exc

    if cache_path:
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def with_query(url: str, params: Mapping[str, object]) -> str:
    encoded = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    return f"{url}{'&' if '?' in url else '?'}{encoded}"
