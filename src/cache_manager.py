"""
cache_manager.py — TTL-based disk cache for API responses.

Each cached item is stored as:
  {cache_dir}/{key}.pkl       — serialised data
  {cache_dir}/{key}.meta.json — timestamp + source metadata

Design principles:
  - SRP: this module only handles cache I/O, nothing else
  - Zero external dependencies beyond stdlib + pickle
  - Thread-safe via atomic writes (write to temp, then rename)
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Lightweight disk cache with per-item TTL.

    Parameters
    ----------
    cache_dir : str | Path
        Directory to store cache files (created if absent).
    default_ttl_hours : float
        Default time-to-live in hours for all items.
        Can be overridden per item in ``get``/``set``.
    """

    _META_SUFFIX = ".meta.json"
    _DATA_SUFFIX = ".pkl"

    def __init__(
        self,
        cache_dir: str | Path = ".cache",
        default_ttl_hours: float = 24.0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.default_ttl_hours = default_ttl_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────

    def get(
        self,
        key: str,
        ttl_hours: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Return cached value if it exists and is fresh, else None.

        Parameters
        ----------
        key : str
            Cache key (alphanumeric + underscores recommended).
        ttl_hours : float | None
            Override the instance-level default TTL for this lookup.
        """
        meta_path = self._meta_path(key)
        data_path = self._data_path(key)

        if not meta_path.exists() or not data_path.exists():
            return None

        try:
            meta = self._read_meta(meta_path)
            effective_ttl = ttl_hours if ttl_hours is not None else self.default_ttl_hours
            ttl  = effective_ttl * 3600
            age  = time.time() - meta["timestamp"]

            if ttl == 0 or age > ttl:
                logger.debug("Cache STALE (%.1fh old, TTL=%.1fh): %s", age/3600, ttl/3600, key)
                return None

            with data_path.open("rb") as fh:
                data = pickle.load(fh)

            logger.info(
                "Cache HIT (%.1fh old, TTL=%.1fh): %s",
                age / 3600,
                ttl / 3600,
                key,
            )
            return data

        except Exception as exc:
            logger.warning("Cache read failed for '%s': %s — will re-fetch", key, exc)
            return None

    def set(
        self,
        key: str,
        value: Any,
        source: str = "",
    ) -> None:
        """
        Persist ``value`` under ``key``.

        Uses atomic write (tempfile → rename) to avoid corrupt files
        if the process is interrupted mid-write.
        """
        data_path = self._data_path(key)
        meta_path = self._meta_path(key)

        try:
            with tempfile.NamedTemporaryFile(
                dir=self.cache_dir,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                pickle.dump(value, tmp)
                tmp_path = tmp.name
            os.replace(tmp_path, data_path)
        except Exception as exc:
            logger.error("Cache write FAILED for '%s': %s", key, exc)
            return

        meta = {
            "timestamp": time.time(),
            "source":    source,
            "key":       key,
        }
        meta_path.write_text(json.dumps(meta, indent=2))
        logger.info("Cache SET: %s (source=%s)", key, source or "unknown")

    def invalidate(self, key: str) -> bool:
        """Delete a cache entry. Returns True if it existed."""
        removed = False
        for path in (self._data_path(key), self._meta_path(key)):
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def clear_all(self) -> int:
        """Delete every cache file. Returns number of entries cleared."""
        count = 0
        for f in self.cache_dir.glob(f"*{self._DATA_SUFFIX}"):
            stem = f.stem
            self.invalidate(stem)
            count += 1
        logger.info("Cache cleared: %d entries removed", count)
        return count

    def status(self) -> list[dict]:
        """Return a list of cache entries with age and staleness info."""
        entries = []
        for data_file in sorted(self.cache_dir.glob(f"*{self._DATA_SUFFIX}")):
            key       = data_file.stem
            meta_path = self._meta_path(key)
            size_kb   = data_file.stat().st_size / 1024
            if meta_path.exists():
                meta     = self._read_meta(meta_path)
                age_h    = (time.time() - meta["timestamp"]) / 3600
                entries.append({
                    "key":     key,
                    "source":  meta.get("source", ""),
                    "age_h":   round(age_h, 2),
                    "size_kb": round(size_kb, 1),
                })
            else:
                entries.append({"key": key, "source": "", "age_h": None, "size_kb": round(size_kb, 1)})
        return entries

    # ── Private helpers ───────────────────────────────────────────────────

    def _data_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}{self._DATA_SUFFIX}"

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}{self._META_SUFFIX}"

    @staticmethod
    def _read_meta(path: Path) -> dict:
        return json.loads(path.read_text())
