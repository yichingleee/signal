"""Binary cache helpers for parquet history-day artifacts.

The parquet history loader builds ``LinearVolumeTracker`` and ``trading_val``
maps per market/date. This module persists that in-memory shape as compact
pickle files plus JSON metadata for freshness checks against source parquet
files.
"""

from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_io import parquet_path

PARQUET_HISTORY_CACHE_SCHEMA_VERSION = 1
PARQUET_HISTORY_CACHE_ENV_VAR = "TW_SIGNAL_PARQUET_HISTORY_CACHE_DIR"
DEFAULT_PARQUET_HISTORY_CACHE_DIR_NAME = "parquet-history-cache"


@dataclass(frozen=True)
class BuildParquetHistoryCacheResult:
    market: str
    date: str
    path: Path
    row_count: int
    elapsed_sec: float
    status: str
    message: str = ""


def default_parquet_history_cache_root(data_dir: str | Path) -> Path:
    override = os.environ.get(PARQUET_HISTORY_CACHE_ENV_VAR)
    if override:
        return Path(override)
    return Path(data_dir).parent / DEFAULT_PARQUET_HISTORY_CACHE_DIR_NAME


def parquet_history_cache_path(cache_root: str | Path, market_type: str, date: str) -> Path:
    return Path(cache_root) / market_type / f"{date}.pkl"


def parquet_history_meta_path(cache_root: str | Path, market_type: str, date: str) -> Path:
    return Path(cache_root) / market_type / f"{date}.meta.json"


def _tmp_path(final_path: Path) -> Path:
    return final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")


def _read_metadata(path: Path) -> dict[str, object] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def read_parquet_history_cache_metadata(
    market_type: str,
    date: str,
    cache_root: str | Path,
) -> dict[str, object] | None:
    return _read_metadata(parquet_history_meta_path(cache_root, market_type, date))


def is_parquet_history_cache_fresh(
    market_type: str,
    date: str,
    parquet_root: str | Path,
    cache_root: str | Path,
) -> bool:
    source = parquet_path(parquet_root, market_type, date)
    if not source.exists():
        return False

    cache_file = parquet_history_cache_path(cache_root, market_type, date)
    meta_file = parquet_history_meta_path(cache_root, market_type, date)
    if not cache_file.exists() or not meta_file.exists():
        return False

    metadata = _read_metadata(meta_file)
    if metadata is None:
        return False

    source_stat = source.stat()
    return (
        metadata.get("schema_version") == PARQUET_HISTORY_CACHE_SCHEMA_VERSION
        and metadata.get("source_size") == source_stat.st_size
        and metadata.get("source_mtime_ns") == source_stat.st_mtime_ns
    )


def write_parquet_history_cache(
    market_type: str,
    date: str,
    parquet_root: str | Path,
    cache_root: str | Path,
    tracker: LinearVolumeTracker,
    trading_val: dict[str, int],
    row_count: int,
) -> Path:
    source = parquet_path(parquet_root, market_type, date)
    if not source.exists():
        raise FileNotFoundError(source)

    cache_file = parquet_history_cache_path(cache_root, market_type, date)
    meta_file = parquet_history_meta_path(cache_root, market_type, date)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    tmp_cache = _tmp_path(cache_file)
    with tmp_cache.open("wb") as f:
        pickle.dump((tracker, trading_val), f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_cache.replace(cache_file)

    source_stat = source.stat()
    metadata: dict[str, object] = {
        "market": market_type,
        "date": date,
        "schema_version": PARQUET_HISTORY_CACHE_SCHEMA_VERSION,
        "source_path": str(source),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "row_count": row_count,
        "symbol_count": len(tracker.data_store),
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    tmp_meta = _tmp_path(meta_file)
    with tmp_meta.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_meta.replace(meta_file)

    return cache_file


def load_parquet_history_cache(
    market_type: str,
    date: str,
    cache_root: str | Path,
) -> tuple[LinearVolumeTracker, dict[str, int]]:
    cache_file = parquet_history_cache_path(cache_root, market_type, date)
    with cache_file.open("rb") as f:
        payload = pickle.load(f)

    if (
        not isinstance(payload, tuple)
        or len(payload) != 2
        or not isinstance(payload[0], LinearVolumeTracker)
        or not isinstance(payload[1], dict)
    ):
        raise ValueError(
            f"invalid parquet history cache payload: {cache_file}"
        )

    tracker = payload[0]
    trading_val = payload[1]
    return tracker, trading_val
