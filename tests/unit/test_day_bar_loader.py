"""Tests for the day-bar loader (M6.1 — 0050 backfill for the parquet path)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tw_signal_engine.market_data.day_bar_loader import (
    _list_day_bar_datasets,
    _pick_dataset_for_date,
    load_0050_open,
)

REAL_DAY_BAR_ROOT = Path("/Users/liyijing/Projects/Trading/market-data/day-ohlcv-and-chip")


def _write_open_parquet(path: Path, dates: list[str], price_0050: list[float]) -> None:
    """Write a minimal day-bar open.parquet matching the production schema.

    The production files use ``date`` as the pandas index column with a
    DatetimeIndex; we replicate that with the pandas metadata path so the
    loader exercises the real round-trip.
    """
    df = pd.DataFrame(
        {"0050": price_0050},
        index=pd.DatetimeIndex(pd.to_datetime(dates), name="date"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=True)
    pq.write_table(table, str(path))


# ---------------------------------------------------------------------------
# Dataset discovery
# ---------------------------------------------------------------------------


def test_list_returns_empty_when_root_missing(tmp_path: Path) -> None:
    assert _list_day_bar_datasets(tmp_path / "no-such-dir") == []


def test_list_sorts_by_end_date_descending(tmp_path: Path) -> None:
    (tmp_path / "day_adj_20070423_20260119").mkdir()
    (tmp_path / "day_adj_20200323_20260401").mkdir()
    (tmp_path / "day_adj_20200323_20260119").mkdir()
    (tmp_path / "noise_dir").mkdir()
    triples = _list_day_bar_datasets(tmp_path)
    ends = [end for _, end, _ in triples]
    assert ends == ["20260401", "20260119", "20260119"]


def test_pick_dataset_returns_freshest_covering_date(tmp_path: Path) -> None:
    (tmp_path / "day_adj_20070423_20260119").mkdir()
    (tmp_path / "day_adj_20200323_20260401").mkdir()
    pick = _pick_dataset_for_date(tmp_path, "20260319")
    assert pick is not None
    assert pick.name == "day_adj_20200323_20260401"


def test_pick_dataset_returns_none_when_date_out_of_range(tmp_path: Path) -> None:
    (tmp_path / "day_adj_20200323_20260401").mkdir()
    assert _pick_dataset_for_date(tmp_path, "20260501") is None


# ---------------------------------------------------------------------------
# Synthetic-tree value lookup
# ---------------------------------------------------------------------------


def test_load_0050_open_returns_correct_value(tmp_path: Path) -> None:
    _write_open_parquet(
        tmp_path / "day_adj_20200323_20260401" / "open.parquet",
        dates=["2026-03-19", "2026-03-20", "2026-03-23"],
        price_0050=[76.6, 76.2, 73.5],
    )
    assert load_0050_open("20260320", tmp_path) == pytest.approx(76.2)


def test_load_0050_open_returns_none_when_root_missing(tmp_path: Path) -> None:
    assert load_0050_open("20260320", tmp_path / "no-such") is None


def test_load_0050_open_returns_none_when_date_missing(tmp_path: Path) -> None:
    _write_open_parquet(
        tmp_path / "day_adj_20200323_20260401" / "open.parquet",
        dates=["2026-03-19"],
        price_0050=[76.6],
    )
    assert load_0050_open("20260320", tmp_path) is None


def test_load_0050_open_returns_none_when_open_parquet_absent(tmp_path: Path) -> None:
    (tmp_path / "day_adj_20200323_20260401").mkdir()
    assert load_0050_open("20260320", tmp_path) is None


# ---------------------------------------------------------------------------
# Real-data smoke test against the developer machine root
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL_DAY_BAR_ROOT.exists(),
    reason="day-ohlcv-and-chip root not present on this developer machine",
)
def test_load_real_0050_opens_match_known_values() -> None:
    expected = {
        "20260319": 76.6,
        "20260320": 76.2,
        "20260326": 76.3,
    }
    for date, want in expected.items():
        got = load_0050_open(date, REAL_DAY_BAR_ROOT)
        assert got is not None
        assert got == pytest.approx(want, abs=0.01)
