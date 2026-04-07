"""SQLite-based cache with TTL, SHA-256 key hashing, and zlib compression."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Any

from research_mcp.config import CacheConfig


class Cache:
    def __init__(self, config: CacheConfig) -> None:
        self._config = config
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        if not self._config.enabled:
            return
        db_path = Path(self._config.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                created_at REAL NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                source TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(created_at, ttl_seconds)"
        )
        self._conn.commit()
        self._evict_expired()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def make_key(tool_name: str, params: dict[str, Any]) -> str:
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        raw = f"{tool_name}:{sorted_params}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        if not self._conn or not self._config.enabled:
            return None
        row = self._conn.execute(
            "SELECT value, created_at, ttl_seconds FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value_blob, created_at, ttl_seconds = row
        if time.time() > created_at + ttl_seconds:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return json.loads(zlib.decompress(value_blob))

    def set(self, key: str, value: Any, ttl_seconds: int, source: str = "") -> None:
        if not self._conn or not self._config.enabled:
            return
        compressed = zlib.compress(json.dumps(value, default=str).encode())
        self._conn.execute(
            """
            INSERT OR REPLACE INTO cache (key, value, created_at, ttl_seconds, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, compressed, time.time(), ttl_seconds, source),
        )
        self._conn.commit()

    def _evict_expired(self) -> None:
        if not self._conn:
            return
        now = time.time()
        self._conn.execute(
            "DELETE FROM cache WHERE (created_at + ttl_seconds) < ?", (now,)
        )
        self._conn.commit()

    def evict_expired(self) -> None:
        self._evict_expired()
