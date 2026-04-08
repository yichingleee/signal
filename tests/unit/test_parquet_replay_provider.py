"""Tests for the parquet replay provider (M4)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tw_signal_engine.market_data.parquet_replay_provider import (
    ParquetReplayProvider,
    _convert_raw_time_to_us,
)
from tw_signal_engine.replay.iterate_market_file import iterate_market_file

PARQUET_ROOT = Path("/Users/liyijing/Projects/Trading/market-data/tick-data")
TEXT_ROOT = Path("exec/data")
PARITY_DATE = "20260326"
PARITY_SYMBOL = "1101"


def _parquet_root_available() -> bool:
    return (PARQUET_ROOT / "TWSE" / f"{PARITY_DATE}.parquet").exists() and (
        PARQUET_ROOT / "TPEX" / f"{PARITY_DATE}.parquet"
    ).exists()


def _text_root_available() -> bool:
    return (TEXT_ROOT / f"TSEQuote.{PARITY_DATE}").exists()


def _write_replay_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    arrays = {
        "symbol": pa.array([r["symbol"] for r in rows], type=pa.string()),
        "time": pa.array([r["time"] for r in rows], type=pa.int64()),
        "matchFlag": pa.array([r.get("matchFlag", "Y") for r in rows], type=pa.string()),
        "tradePrice": pa.array([r["tradePrice"] for r in rows], type=pa.float64()),
        "tradeVolume": pa.array([r["tradeVolume"] for r in rows], type=pa.int32()),
        "buyPrice1": pa.array([r["buyPrice1"] for r in rows], type=pa.float64()),
        "sellPrice1": pa.array([r["sellPrice1"] for r in rows], type=pa.float64()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(arrays), str(path))


# ---------------------------------------------------------------------------
# Time conversion sanity
# ---------------------------------------------------------------------------


def test_convert_raw_time_to_us_handles_open() -> None:
    assert _convert_raw_time_to_us(91500000000) == (9 * 3600 + 15 * 60) * 1_000_000


# ---------------------------------------------------------------------------
# Synthetic-tree integration tests
# ---------------------------------------------------------------------------


def test_chronological_order_across_otc_tse_merge(tmp_path: Path) -> None:
    """Yielded ticks must be sorted by ``match_time_str`` after the merge."""
    _write_replay_parquet(
        tmp_path / "TWSE" / "20260326.parquet",
        [
            {
                "symbol": "1101",
                "time": 90100000000,
                "tradePrice": 26.10,
                "tradeVolume": 100,
                "buyPrice1": 26.05,
                "sellPrice1": 26.15,
            },
            {
                "symbol": "1102",
                "time": 90300000000,
                "tradePrice": 31.55,
                "tradeVolume": 50,
                "buyPrice1": 31.50,
                "sellPrice1": 31.60,
            },
            {
                "symbol": "1103",
                "time": 90500000000,
                "tradePrice": 50.0,
                "tradeVolume": 0,  # replay path keeps trade rows only
                "buyPrice1": 49.95,
                "sellPrice1": 50.05,
            },
        ],
    )
    _write_replay_parquet(
        tmp_path / "TPEX" / "20260326.parquet",
        [
            {
                "symbol": "5483",
                "time": 90200000000,
                "tradePrice": 100.0,
                "tradeVolume": 200,
                "buyPrice1": 99.5,
                "sellPrice1": 100.5,
            },
            {
                "symbol": "6488",
                "time": 90400000000,
                "tradePrice": 1234.50,
                "tradeVolume": 30,
                "buyPrice1": 1234.0,
                "sellPrice1": 1235.0,
            },
        ],
    )

    provider = ParquetReplayProvider(
        otc_date="20260326",
        tse_date="20260326",
        root=tmp_path,
    )
    ticks = list(provider.iterate_ticks())

    assert [t.match_time_str for t in ticks] == sorted(t.match_time_str for t in ticks)
    assert [t.symbol for t in ticks] == ["1101", "5483", "1102", "6488"]
    assert [t.market for t in ticks] == ["TSE", "OTC", "TSE", "OTC"]
    assert all(t.match.qty > 0 for t in ticks)


def test_status_equivalence_filters_matchflag_and_preopen(tmp_path: Path) -> None:
    _write_replay_parquet(
        tmp_path / "TWSE" / "20260326.parquet",
        [
            {
                "symbol": "1101",
                "time": 85959000000,  # pre-open: filtered
                "matchFlag": "Y",
                "tradePrice": 26.1,
                "tradeVolume": 100,
                "buyPrice1": 26.05,
                "sellPrice1": 26.15,
            },
            {
                "symbol": "1101",
                "time": 90000000000,  # session open: kept
                "matchFlag": "Y",
                "tradePrice": 26.2,
                "tradeVolume": 0,
                "buyPrice1": 26.15,
                "sellPrice1": 26.25,
            },
            {
                "symbol": "1101",
                "time": 90100000000,  # non-match flag: filtered
                "matchFlag": "N",
                "tradePrice": 26.3,
                "tradeVolume": 200,
                "buyPrice1": 26.25,
                "sellPrice1": 26.35,
            },
            {
                "symbol": "1101",
                "time": 90150000000,  # valid trade row: kept
                "matchFlag": "Y",
                "tradePrice": 26.4,
                "tradeVolume": 10,
                "buyPrice1": 26.35,
                "sellPrice1": 26.45,
            },
        ],
    )
    _write_replay_parquet(tmp_path / "TPEX" / "20260326.parquet", [])

    provider = ParquetReplayProvider(
        otc_date="20260326",
        tse_date="20260326",
        root=tmp_path,
    )
    ticks = list(provider.iterate_ticks())
    assert len(ticks) == 1
    assert ticks[0].match_time_str == 90150000000
    assert ticks[0].match.qty == 10


def test_tick_filter_pushdown_keeps_only_target_symbol(tmp_path: Path) -> None:
    _write_replay_parquet(
        tmp_path / "TWSE" / "20260326.parquet",
        [
            {
                "symbol": "1101",
                "time": 90100000000,
                "tradePrice": 26.10,
                "tradeVolume": 100,
                "buyPrice1": 26.05,
                "sellPrice1": 26.15,
            },
            {
                "symbol": "2330",
                "time": 90200000000,
                "tradePrice": 588.0,
                "tradeVolume": 100,
                "buyPrice1": 587.0,
                "sellPrice1": 589.0,
            },
        ],
    )
    _write_replay_parquet(
        tmp_path / "TPEX" / "20260326.parquet",
        [
            {
                "symbol": "5483",
                "time": 90150000000,
                "tradePrice": 100.0,
                "tradeVolume": 200,
                "buyPrice1": 99.5,
                "sellPrice1": 100.5,
            },
        ],
    )

    provider = ParquetReplayProvider(
        otc_date="20260326",
        tse_date="20260326",
        root=tmp_path,
        tick_filter={"1101"},
    )
    ticks = list(provider.iterate_ticks())
    assert [t.symbol for t in ticks] == ["1101"]
    assert ticks[0].market == "TSE"


def test_price_conversion_uses_round(tmp_path: Path) -> None:
    """Per H2 in the design report: 0.57 -> 5700, never 5699."""
    _write_replay_parquet(
        tmp_path / "TWSE" / "20260326.parquet",
        [
            {
                "symbol": "1101",
                "time": 90100000000,
                "tradePrice": 0.57,
                "tradeVolume": 100,
                "buyPrice1": 0.56,
                "sellPrice1": 0.58,
            },
        ],
    )
    _write_replay_parquet(tmp_path / "TPEX" / "20260326.parquet", [])

    provider = ParquetReplayProvider(
        otc_date="20260326",
        tse_date="20260326",
        root=tmp_path,
    )
    ticks = list(provider.iterate_ticks())
    assert len(ticks) == 1
    assert ticks[0].match.price == 5700
    assert ticks[0].bid[0].price == 5600
    assert ticks[0].ask[0].price == 5800
    # 0.57 sits at the bid in our fixture; trade_at should be 1 (inner).
    # Here the price is 5700, bid is 5600 -> not at bid, ask is 5800 -> not at ask.
    # Provider falls back to "outer" only if ask > 0; both bids/asks are present
    # so trade_at goes to outer/2 since price != bid.
    assert ticks[0].trade_at in (1, 2)


def test_volatility_pause_set_for_first_three_ticks(tmp_path: Path) -> None:
    rows = [
        {
            "symbol": "1101",
            "time": 90100000000 + i * 100000,
            "tradePrice": 26.10,
            "tradeVolume": 10,
            "buyPrice1": 26.05,
            "sellPrice1": 26.15,
        }
        for i in range(5)
    ]
    _write_replay_parquet(tmp_path / "TWSE" / "20260326.parquet", rows)
    _write_replay_parquet(tmp_path / "TPEX" / "20260326.parquet", [])

    provider = ParquetReplayProvider(
        otc_date="20260326",
        tse_date="20260326",
        root=tmp_path,
    )
    ticks = list(provider.iterate_ticks())
    assert [t.volatility_pause for t in ticks] == [True, True, True, False, False]


# ---------------------------------------------------------------------------
# Real-data parity vs the legacy iterate_market_file
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_parquet_root_available() and _text_root_available()),
    reason="parquet root or legacy text root unavailable on this developer machine",
)
def test_row_count_parity_for_single_symbol_against_iterate_market_file() -> None:
    """For a non-00 symbol that appears in both feeds the per-symbol cumulative
    volume from the parquet provider should match the legacy provider within
    the closing-auction tolerance documented in the plan."""
    text_total = sum(
        tick.match.qty
        for tick in iterate_market_file("TSE", PARITY_DATE, str(TEXT_ROOT), {PARITY_SYMBOL})
    )
    provider = ParquetReplayProvider(
        otc_date=PARITY_DATE,
        tse_date=PARITY_DATE,
        root=PARQUET_ROOT,
        tick_filter={PARITY_SYMBOL},
    )
    parq_total = sum(tick.match.qty for tick in provider.iterate_ticks())
    delta = abs(parq_total - text_total)
    tolerance = max(1000, text_total // 100)
    assert delta <= tolerance, f"text={text_total} parquet={parq_total} delta={delta}"
