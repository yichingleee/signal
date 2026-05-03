"""Tests for shared parquet IO helpers (M2)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from tw_signal_engine.market_data.parquet_io import (
    PARQUET_HISTORY_COLUMNS,
    PARQUET_HISTORY_REQUIRED_COLUMNS,
    PARQUET_REPLAY_COLUMNS,
    assert_history_schema,
    assert_replay_schema,
    parquet_path,
    to_int_price,
)

# ---------------------------------------------------------------------------
# to_int_price
# ---------------------------------------------------------------------------


def test_to_int_price_matches_legacy_reference_prices() -> None:
    """``to_int_price`` must round identically to ``int(legacy_text * 1)``.

    The legacy text feed already stores prices as ``int * 10000``; the parquet
    feed stores them as floats. ``round`` is the only conversion that survives
    IEEE-754 quantization for the canonical Taiwan tick prices.
    """
    # Includes the canary 31.55 from the design report (H2): the float
    # 31.55 * 10000 lands at 315499.99..., int() truncates to 315499.
    reference_prices = [
        (10.00, 100000),
        (10.05, 100500),
        (10.10, 101000),
        (12.34, 123400),
        (15.55, 155500),
        (20.00, 200000),
        (26.10, 261000),
        (31.55, 315500),
        (50.00, 500000),
        (50.50, 505000),
        (99.99, 999900),
        (100.00, 1000000),
        (100.50, 1005000),
        (199.50, 1995000),
        (250.00, 2500000),
        (588.00, 5880000),
        (612.50, 6125000),
        (1000.00, 10000000),
        (1234.50, 12345000),
        (5880.00, 58800000),
    ]
    for price, expected in reference_prices:
        assert to_int_price(price) == expected, f"price={price}"


def test_to_int_price_survives_float_quantization_canaries() -> None:
    """Direct regression for the float-quantization bug from H2 of the design report.

    Each price below makes ``int(p * 10000)`` truncate one tick low because the
    float multiplication lands at ``…99.999999…``. ``round(...)`` is the only
    safe conversion.
    """
    # Prices were discovered by sweeping every Taiwan tick price; these are all
    # real points on the published tick ladder.
    canaries = [
        (0.57, 5700),
        (0.69, 6900),
        (1.13, 11300),
        (2.01, 20100),
        (3.01, 30100),
        (4.06, 40600),
    ]
    for price, expected in canaries:
        assert to_int_price(price) == expected, f"price={price}"
        # Demonstrates why we cannot use int().
        assert int(price * 10000) == expected - 1, f"price={price}"


# ---------------------------------------------------------------------------
# assert_replay_schema
# ---------------------------------------------------------------------------


def _replay_table(**overrides: pa.Array) -> pa.Table:
    arrays: dict[str, pa.Array] = {
        "symbol": pa.array(["2330"], type=pa.string()),
        "time": pa.array([91500000000], type=pa.int64()),
        "matchFlag": pa.array(["Y"], type=pa.string()),
        "tradePrice": pa.array([588.0], type=pa.float64()),
        "tradeVolume": pa.array([100], type=pa.int32()),
        "buyPrice1": pa.array([587.0], type=pa.float64()),
        "buyVolume1": pa.array([10], type=pa.int32()),
        "buyVolume2": pa.array([20], type=pa.int32()),
        "buyVolume3": pa.array([0], type=pa.int32()),
        "buyVolume4": pa.array([0], type=pa.int32()),
        "buyVolume5": pa.array([0], type=pa.int32()),
        "sellPrice1": pa.array([589.0], type=pa.float64()),
        "sellVolume1": pa.array([15], type=pa.int32()),
        "sellVolume2": pa.array([0], type=pa.int32()),
        "sellVolume3": pa.array([0], type=pa.int32()),
        "sellVolume4": pa.array([0], type=pa.int32()),
        "sellVolume5": pa.array([0], type=pa.int32()),
    }
    arrays.update(overrides)
    return pa.table(arrays)


def _history_table(**overrides: pa.Array) -> pa.Table:
    arrays: dict[str, pa.Array] = {
        "symbol": pa.array(["2330"], type=pa.string()),
        "time": pa.array([91500000000], type=pa.int64()),
        "matchFlag": pa.array(["Y"], type=pa.string()),
        "tradePrice": pa.array([588.0], type=pa.float64()),
        "tradeVolume": pa.array([100], type=pa.int32()),
    }
    arrays.update(overrides)
    return pa.table(arrays)


def test_assert_replay_schema_accepts_canonical_table() -> None:
    assert_replay_schema(_replay_table())


def test_assert_replay_schema_lists_missing_column() -> None:
    table = _replay_table()
    table = table.drop(["matchFlag"])
    with pytest.raises(ValueError) as exc:
        assert_replay_schema(table)
    assert "missing" in str(exc.value)
    assert "matchFlag" in str(exc.value)


def test_assert_replay_schema_lists_mistyped_column() -> None:
    # Force tradeVolume to int64 to trigger a type mismatch (expected: int32).
    table = _replay_table(tradeVolume=pa.array([100], type=pa.int64()))
    with pytest.raises(ValueError) as exc:
        assert_replay_schema(table)
    assert "mistyped" in str(exc.value)
    assert "tradeVolume" in str(exc.value)


def test_assert_history_schema_accepts_required_columns() -> None:
    assert_history_schema(_history_table().schema)


def test_assert_history_schema_requires_matchflag_for_filter_contract() -> None:
    table = _history_table().drop(["matchFlag"])
    with pytest.raises(ValueError) as exc:
        assert_history_schema(table.schema)
    assert "missing" in str(exc.value)
    assert "matchFlag" in str(exc.value)


# ---------------------------------------------------------------------------
# parquet_path
# ---------------------------------------------------------------------------


def test_parquet_path_tse_maps_to_twse() -> None:
    assert parquet_path("/root", "TSE", "20260326") == Path("/root/TWSE/20260326.parquet")


def test_parquet_path_otc_maps_to_tpex() -> None:
    assert parquet_path("/root", "OTC", "20260326") == Path("/root/TPEX/20260326.parquet")


def test_parquet_path_accepts_path_root() -> None:
    assert parquet_path(Path("/root"), "TSE", "20260326") == Path("/root/TWSE/20260326.parquet")


def test_parquet_path_rejects_unknown_market() -> None:
    with pytest.raises(ValueError):
        parquet_path("/root", "TWSE", "20260326")
    with pytest.raises(ValueError):
        parquet_path("/root", "TPEX", "20260326")


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_canonical_column_lists_are_complete() -> None:
    # Replay covers everything the engine needs to construct a MarketTick,
    # including the five-level depth volumes that surface limit-up-locked state.
    expected_replay = {
        "symbol",
        "time",
        "matchFlag",
        "tradePrice",
        "tradeVolume",
        "buyPrice1",
        "buyVolume1",
        "buyVolume2",
        "buyVolume3",
        "buyVolume4",
        "buyVolume5",
        "sellPrice1",
        "sellVolume1",
        "sellVolume2",
        "sellVolume3",
        "sellVolume4",
        "sellVolume5",
    }
    assert set(PARQUET_REPLAY_COLUMNS) == expected_replay
    # History needs the lighter projection (no quote levels).
    assert set(PARQUET_HISTORY_COLUMNS) == {"symbol", "time", "tradePrice", "tradeVolume"}
    assert set(PARQUET_HISTORY_REQUIRED_COLUMNS) == {
        "symbol",
        "time",
        "matchFlag",
        "tradePrice",
        "tradeVolume",
    }
