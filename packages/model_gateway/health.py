"""连接健康缓存（B3，§9.2）。

- 缓存键 = connection_id + 配置指纹（配置一改自动失效）
- 正缓存 300s / 负缓存 60s
- 同 key 并发的检查合并（single-flight）
- 进程内内存缓存；重启后为空，用 DB 的 last_health_* 仅作展示
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

TTL_OK = 300
TTL_FAIL = 60


@dataclass
class HealthEntry:
    ok: bool
    latency_ms: int
    checked_at: float
    source: str = "live"


class HealthCache:
    def __init__(self) -> None:
        self._data: dict[str, HealthEntry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @staticmethod
    def fingerprint(*parts: object) -> str:
        raw = "|".join(str(p or "") for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def key(self, connection_id: str, fingerprint: str) -> str:
        return f"{connection_id}:{fingerprint}"

    def get(self, key: str) -> HealthEntry | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ttl = TTL_OK if entry.ok else TTL_FAIL
        if time.time() - entry.checked_at > ttl:
            self._data.pop(key, None)
            return None
        return entry

    def put(self, key: str, ok: bool, latency_ms: int) -> HealthEntry:
        entry = HealthEntry(ok=ok, latency_ms=latency_ms, checked_at=time.time(), source="live")
        self._data[key] = entry
        return entry

    def invalidate(self, connection_id: str) -> None:
        for key in [k for k in self._data if k.startswith(f"{connection_id}:")]:
            self._data.pop(key, None)

    def lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def clear(self) -> None:
        self._data.clear()


health_cache = HealthCache()
