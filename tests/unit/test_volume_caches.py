"""Tests for the volume cache system."""

from __future__ import annotations

import json
import time

import pytest

from tw_signal_engine.market_data.build_volume_caches import (
    CACHE_SCHEMA_VERSION,
    _cache_path,
    build_cache,
    is_cache_valid,
)
from tw_signal_engine.market_data.load_history_window import load_history_window


@pytest.fixture()
def data_dir(tmp_path):
    """Create a data directory with sample replay files."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "OTCQuote.20260128").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n"
        "Trade,SYM1,90100000000,0,100000,20\n"
        "Trade,SYM2,90000000000,0,200000,5\n",
        encoding="utf-8",
    )
    (d / "OTCQuote.20260129").write_text("", encoding="utf-8")
    return d


def test_build_cache_creates_file(data_dir) -> None:
    path = build_cache("OTC", "20260128", str(data_dir))
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CACHE_SCHEMA_VERSION
    assert raw["market"] == "OTC"
    assert raw["date"] == "20260128"
    assert "SYM1" in raw["symbols"]
    assert "SYM2" in raw["symbols"]


def test_cache_is_valid_after_build(data_dir) -> None:
    assert not is_cache_valid("OTC", "20260128", str(data_dir))
    build_cache("OTC", "20260128", str(data_dir))
    assert is_cache_valid("OTC", "20260128", str(data_dir))


def test_cache_invalid_after_source_change(data_dir) -> None:
    build_cache("OTC", "20260128", str(data_dir))
    assert is_cache_valid("OTC", "20260128", str(data_dir))

    # Modify source file
    time.sleep(0.05)
    source = data_dir / "OTCQuote.20260128"
    source.write_text(
        source.read_text(encoding="utf-8") + "Trade,SYM3,90200000000,0,150000,15\n",
        encoding="utf-8",
    )
    assert not is_cache_valid("OTC", "20260128", str(data_dir))


def test_cache_invalid_with_wrong_schema(data_dir) -> None:
    build_cache("OTC", "20260128", str(data_dir))
    path = _cache_path(str(data_dir), "OTC", "20260128")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = -1
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert not is_cache_valid("OTC", "20260128", str(data_dir))


def test_load_cache_matches_text_parse(data_dir) -> None:
    """Cached data must exactly match text-parsed data."""
    # Load from text
    hw_text = load_history_window("OTC", "20260129", str(data_dir), use_cache=False)

    # Build and load from cache
    build_cache("OTC", "20260128", str(data_dir))
    hw_cached = load_history_window("OTC", "20260129", str(data_dir), use_cache=True)

    assert hw_text.num_days == hw_cached.num_days
    assert hw_text.source_dates == hw_cached.source_dates

    for i in range(hw_text.num_days):
        assert hw_text.trading_val[i] == hw_cached.trading_val[i]
        # Compare vol_cum data stores
        text_store = hw_text.vol_cum[i].data_store
        cache_store = hw_cached.vol_cum[i].data_store
        assert set(text_store.keys()) == set(cache_store.keys())
        for sym in text_store:
            text_nodes = text_store[sym]
            cache_nodes = cache_store[sym]
            assert len(text_nodes) == len(cache_nodes)
            for t, c in zip(text_nodes, cache_nodes):
                assert t.timestamp == c.timestamp
                assert t.cumulative_qty == c.cumulative_qty


def test_load_history_window_cache_miss_does_not_write(data_dir) -> None:
    """load_history_window with use_cache=True falls back to text parse without writing cache."""
    cache_path = _cache_path(str(data_dir), "OTC", "20260128")
    assert not cache_path.exists()

    hw = load_history_window("OTC", "20260129", str(data_dir), use_cache=True)
    assert hw.num_days == 1
    # Cache should NOT be auto-built — keeps data dir read-only safe
    assert not cache_path.exists()


def test_build_cache_missing_source(data_dir) -> None:
    with pytest.raises(FileNotFoundError):
        build_cache("OTC", "20260130", str(data_dir))
