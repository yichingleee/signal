"""Tests for the parquet history-window loader (M3)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tw_signal_engine.market_data.load_history_window import load_history_window
from tw_signal_engine.market_data.parquet_history_loader import (
    _convert_raw_time_to_us,
    _find_history_files,
    load_parquet_history_window,
)

PARQUET_ROOT = Path("/Users/liyijing/Projects/Trading/market-data/tick-data")
TEXT_ROOT = Path("exec/data")


def _parquet_root_available() -> bool:
    return (PARQUET_ROOT / "TWSE").is_dir() and (PARQUET_ROOT / "TPEX").is_dir()


def _text_root_available() -> bool:
    return (TEXT_ROOT / "TSEQuote.20260326").exists()


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------


def test_convert_raw_time_to_us_handles_canonical_open() -> None:
    # 91500000000 = 09:15:00.000000
    assert _convert_raw_time_to_us(91500000000) == (9 * 3600 + 15 * 60) * 1_000_000


def test_convert_raw_time_to_us_handles_microseconds() -> None:
    # 130530123456 = 13:05:30.123456
    expected = (13 * 3600 + 5 * 60 + 30) * 1_000_000 + 123456
    assert _convert_raw_time_to_us(130530123456) == expected


# ---------------------------------------------------------------------------
# History file discovery (uses a synthetic tmp_path tree)
# ---------------------------------------------------------------------------


def _write_minimal_parquet(
    path: Path,
    *,
    symbol: str = "1101",
    price: float = 588.0,
    time_raw: int = 91500000000,
    match_flag: str = "Y",
    qty: int = 100,
) -> None:
    table = pa.table(
        {
            "symbol": pa.array([symbol], type=pa.string()),
            "time": pa.array([time_raw], type=pa.int64()),
            "matchFlag": pa.array([match_flag], type=pa.string()),
            "tradePrice": pa.array([price], type=pa.float64()),
            "tradeVolume": pa.array([qty], type=pa.int32()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


def test_find_history_files_excludes_target_date(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    for date in ["20260319", "20260320", "20260323", "20260325", "20260326"]:
        _write_minimal_parquet(twse / f"{date}.parquet")

    files = _find_history_files("TSE", "20260326", tmp_path)
    found_dates = [d for _, d in files]
    assert "20260326" not in found_dates
    assert found_dates == ["20260325", "20260323", "20260320", "20260319"]


def test_find_history_files_caps_at_twenty_sessions(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    # 25 prior dates + 1 target date
    dates = [f"2026{m:02d}{d:02d}" for m in (1, 2) for d in range(1, 14)]
    dates = sorted(dates)[:25]
    for date in dates:
        _write_minimal_parquet(twse / f"{date}.parquet")
    target = "20260301"
    _write_minimal_parquet(twse / f"{target}.parquet")

    files = _find_history_files("TSE", target, tmp_path)
    assert len(files) == 20
    found_dates = [d for _, d in files]
    # Newest first.
    assert found_dates == sorted(found_dates, reverse=True)


def test_find_history_files_requires_target_file_by_default(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    _write_minimal_parquet(twse / "20260319.parquet")

    with pytest.raises(FileNotFoundError, match="20260326"):
        _find_history_files("TSE", "20260326", tmp_path)


def test_find_history_files_allows_missing_target_for_live_mode(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    _write_minimal_parquet(twse / "20260319.parquet")

    files = _find_history_files("TSE", "20260326", tmp_path, require_target_file=False)
    assert [d for _, d in files] == ["20260319"]


def test_find_history_files_raises_when_market_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="TWSE"):
        _find_history_files("TSE", "20260326", tmp_path)


# ---------------------------------------------------------------------------
# Single-day load shape
# ---------------------------------------------------------------------------


def test_load_parquet_history_window_returns_shape(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    _write_minimal_parquet(twse / "20260319.parquet", symbol="1101", price=588.0)
    _write_minimal_parquet(twse / "20260320.parquet", symbol="1101", price=590.0)
    _write_minimal_parquet(twse / "20260326.parquet", symbol="1101", price=600.0)

    hw = load_parquet_history_window("TSE", "20260326", tmp_path)

    assert hw.num_days == 2
    assert hw.source_dates == ["20260320", "20260319"]

    # vol_cum entries are LinearVolumeTracker objects with one symbol.
    most_recent = hw.vol_cum[0]
    assert "1101" in most_recent.data_store
    nodes = most_recent.data_store["1101"]
    assert nodes[-1].cumulative_qty == 100

    # trading_val: qty * (round(price * 10000)) // 10
    assert hw.trading_val[0]["1101"] == 100 * 5900000 // 10


def test_load_parquet_history_window_applies_status_equivalence_filter(tmp_path: Path) -> None:
    twse = tmp_path / "TWSE"
    table = pa.table(
        {
            "symbol": pa.array(["1101", "1101", "1101"], type=pa.string()),
            "time": pa.array([85959000000, 90000000000, 90100000000], type=pa.int64()),
            "matchFlag": pa.array(["Y", "Y", "N"], type=pa.string()),
            "tradePrice": pa.array([10.0, 10.5, 11.0], type=pa.float64()),
            "tradeVolume": pa.array([100, 0, 200], type=pa.int32()),
        }
    )
    twse.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(twse / "20260320.parquet"))
    _write_minimal_parquet(twse / "20260326.parquet", symbol="1101", price=12.0)

    hw = load_parquet_history_window("TSE", "20260326", tmp_path)
    assert hw.num_days == 1
    tracker = hw.vol_cum[0]
    nodes = tracker.data_store["1101"]
    assert [n.timestamp for n in nodes] == [_convert_raw_time_to_us(90000000000)]
    assert nodes[0].cumulative_qty == 0
    assert hw.trading_val[0]["1101"] == 0


# ---------------------------------------------------------------------------
# Real-data parity vs the legacy text loader (slow; skipped in absent envs)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_parquet_root_available() and _text_root_available()),
    reason="parquet root or legacy text root unavailable on this developer machine",
)
def test_parquet_loader_matches_text_loader() -> None:
    """Compare the parquet loader against the legacy text loader for one date.

    Acceptance, derived from the M1 / cross-check findings recorded in the
    plan's Surprises & Discoveries section:

      * Every symbol the parquet feed reports must also exist in the text
        feed (the reverse is allowed because the parquet feed deliberately
        omits all 00-prefix ETFs and warrants).
      * For symbols present in both feeds the per-symbol cumulative volume
        delta must be at most 1% of the text-side total OR 1000 shares,
        whichever is larger. Both feeds quote the same trades; the only
        recurring drift is at the closing-auction batch where parquet
        sometimes captures a slightly larger aggregate than the text dump.
        Anything beyond that envelope would indicate a real regression in
        the loader.
    """
    text_hw = load_history_window("TSE", "20260326", str(TEXT_ROOT), use_cache=True)
    parq_hw = load_parquet_history_window("TSE", "20260326", PARQUET_ROOT)

    assert text_hw.num_days > 0
    assert parq_hw.num_days > 0
    common = sorted(set(text_hw.source_dates) & set(parq_hw.source_dates), reverse=True)
    assert common, "no overlapping prior-session dates between text and parquet"

    text_idx = {d: i for i, d in enumerate(text_hw.source_dates)}
    parq_idx = {d: i for i, d in enumerate(parq_hw.source_dates)}

    parquet_only_violations: list[str] = []
    big_delta_violations: list[tuple[str, str, int, int, int]] = []

    for date in common:
        ti = text_idx[date]
        pi = parq_idx[date]
        text_tracker = text_hw.vol_cum[ti]
        parq_tracker = parq_hw.vol_cum[pi]
        text_totals = {
            sym: nodes[-1].cumulative_qty for sym, nodes in text_tracker.data_store.items()
        }
        parq_totals = {
            sym: nodes[-1].cumulative_qty for sym, nodes in parq_tracker.data_store.items()
        }

        for sym, parq_total in parq_totals.items():
            if sym not in text_totals:
                parquet_only_violations.append(f"{date}:{sym}")
                continue
            text_total = text_totals[sym]
            delta = abs(parq_total - text_total)
            tolerance = max(1000, text_total // 100)
            if delta > tolerance:
                big_delta_violations.append((date, sym, text_total, parq_total, delta))

    assert not parquet_only_violations, (
        f"parquet feed introduced symbols absent from text on dates: "
        f"{parquet_only_violations[:10]} (total {len(parquet_only_violations)})"
    )
    assert not big_delta_violations, (
        "parquet vs text cumulative-volume delta exceeded auction-tail tolerance: "
        f"{big_delta_violations[:5]}"
    )
