"""Tests for replay-universe construction."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import StrongSingleConfig
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.replay.build_replay_universe import (
    build_replay_universe,
    extract_valid_group_symbols,
)
from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator


def _make_reference(symbol: str) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name=symbol,
        market="T",
        previous_close=10.0,
        limit_up_price=11.0,
        limit_down_price=9.0,
        industry="00",
        security="",
        error_code="0",
    )


def test_build_replay_universe_includes_prevalidated_strong_single_symbols() -> None:
    trading_val = [{} for _ in range(21)]
    for day in range(1, 21):
        trading_val[day]["SINGLE"] = 500

    strong_single = StrongSingleEvaluator(
        config=StrongSingleConfig(enabled=True, min_month_trading_val=100),
        vol_cum=[LinearVolumeTracker() for _ in range(21)],
        trading_val=trading_val,
        f1_map={"SINGLE": _make_reference("SINGLE")},
    )

    single_valid_symbols = strong_single.initialize_validity()
    universe = build_replay_universe({"GROUP"}, single_valid_symbols=single_valid_symbols)

    assert "GROUP" in universe
    assert "SINGLE" in universe
    assert "0050" in universe


def test_extract_valid_group_symbols_filters_false_values() -> None:
    symbol_is_valid = {"AAA": True, "BBB": False, "CCC": True, "DDD": False}

    assert extract_valid_group_symbols(symbol_is_valid) == {"AAA", "CCC"}
