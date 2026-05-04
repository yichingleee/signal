from __future__ import annotations

import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_history_cache import (
    default_parquet_history_cache_root,
    is_parquet_history_cache_fresh,
    load_parquet_history_cache,
    parquet_history_cache_path,
    parquet_history_meta_path,
    read_parquet_history_cache_metadata,
    write_parquet_history_cache,
)


def _write_minimal_parquet(path: Path) -> None:
    table = pa.table(
        {
            "symbol": pa.array(["1101"], type=pa.string()),
            "time": pa.array([90000000000], type=pa.int64()),
            "matchFlag": pa.array(["Y"], type=pa.string()),
            "tradePrice": pa.array([10.0], type=pa.float64()),
            "tradeVolume": pa.array([100], type=pa.int32()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


def test_write_and_load_cache_round_trip(tmp_path: Path) -> None:
    parquet_root = tmp_path / "ticks"
    source = parquet_root / "TWSE" / "20260320.parquet"
    _write_minimal_parquet(source)
    cache_root = tmp_path / "cache"

    tracker = LinearVolumeTracker()
    tracker.on_tick("1101", 32_400_000_000, 100)
    trading_val = {"1101": 100_000}

    path = write_parquet_history_cache(
        market_type="TSE",
        date="20260320",
        parquet_root=parquet_root,
        cache_root=cache_root,
        tracker=tracker,
        trading_val=trading_val,
        row_count=1,
    )
    assert path == parquet_history_cache_path(cache_root, "TSE", "20260320")
    assert path.exists()
    assert parquet_history_meta_path(cache_root, "TSE", "20260320").exists()

    loaded_tracker, loaded_tv = load_parquet_history_cache("TSE", "20260320", cache_root)
    assert loaded_tv == trading_val
    assert loaded_tracker.data_store["1101"][-1].cumulative_qty == 100

    meta = read_parquet_history_cache_metadata("TSE", "20260320", cache_root)
    assert meta is not None
    assert meta["schema_version"] == 1
    assert meta["row_count"] == 1
    assert meta["symbol_count"] == 1


def test_cache_freshness_tracks_source_mtime(tmp_path: Path) -> None:
    parquet_root = tmp_path / "ticks"
    source = parquet_root / "TWSE" / "20260320.parquet"
    _write_minimal_parquet(source)
    cache_root = tmp_path / "cache"

    tracker = LinearVolumeTracker()
    tracker.on_tick("1101", 32_400_000_000, 100)
    write_parquet_history_cache(
        market_type="TSE",
        date="20260320",
        parquet_root=parquet_root,
        cache_root=cache_root,
        tracker=tracker,
        trading_val={"1101": 100_000},
        row_count=1,
    )

    assert is_parquet_history_cache_fresh("TSE", "20260320", parquet_root, cache_root)

    time.sleep(0.01)
    _write_minimal_parquet(source)
    assert not is_parquet_history_cache_fresh("TSE", "20260320", parquet_root, cache_root)


def test_default_cache_root_uses_env_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    override = tmp_path / "override"
    monkeypatch.setenv("TW_SIGNAL_PARQUET_HISTORY_CACHE_DIR", str(override))
    assert default_parquet_history_cache_root(tmp_path / "ticks") == override
