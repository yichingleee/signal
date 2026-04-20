"""Tests for weakest-path strong-group screening in short mode."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import StrongGroupConfig
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.state.symbol_state import IndexData


def _ref(symbol: str) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name=symbol,
        market="TSE",
        previous_close=100.0,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


def _config(entry_max_vwap_pct_chg: float = 0.0) -> StrongGroupConfig:
    return StrongGroupConfig(
        enabled=True,
        member_min_month_trading_val=0,
        group_min_month_trading_val=0,
        group_min_avg_pct_chg=0.0,
        group_min_val_ratio=0.0,
        member_strong_vol_ratio=0.0,
        member_strong_trading_val=0,
        top_group_rank_threshold=10,
        top_group_max_select=1,
        normal_group_max_select=1,
        member_vwap_pct_chg_threshold=0.0,
        group_valid_top_n=10,
        member_cond1_enabled=False,
        member_cond2_enabled=False,
        member_cond4_enabled=False,
        entry_min_vwap_pct_chg=0.0,
        entry_max_vwap_pct_chg=entry_max_vwap_pct_chg,
        require_raw_m1=True,
        block_disposition_entry=False,
        entry_max_vol_ratio=0.0,
    )


def _make_eval(trade_mode: str, entry_max_vwap_pct_chg: float = 0.0) -> StrongGroupEvaluator:
    symbol_to_groups = {"AAA": ["G1"], "BBB": ["G1"]}
    group_members = {"G1": {"AAA", "BBB"}}
    vol_cum = [LinearVolumeTracker()]
    trading_val = [{"AAA": 1_000_000_000, "BBB": 1_000_000_000}]
    f1_map = {"AAA": _ref("AAA"), "BBB": _ref("BBB")}

    ev = StrongGroupEvaluator(
        config=_config(entry_max_vwap_pct_chg=entry_max_vwap_pct_chg),
        symbol_to_groups=symbol_to_groups,
        group_members=group_members,
        vol_cum=vol_cum,
        trading_val=trading_val,
        f1_map=f1_map,
        prev_day_limit_up={},
        trade_mode=trade_mode,
    )
    ev.initialize_validity()
    return ev


def test_short_mode_selects_weakest_member_with_raw_rank_gate() -> None:
    ev = _make_eval("short")

    # Stronger symbol first; short group validity needs average pct < 0.
    got_b = ev.on_tick(IndexData(vwap=1_020_000.0), "BBB", 1_020_000, 100, 91000000000, 91000000000, False)
    got_a = ev.on_tick(IndexData(vwap=970_000.0), "AAA", 970_000, 100, 91010000000, 91010000000, False)

    assert got_b is False
    assert got_a is True
    info = ev.last_match_info["AAA"]
    assert info.raw_member_rank == 1


def test_long_mode_still_selects_strongest_member() -> None:
    ev = _make_eval("long")

    ev.on_tick(IndexData(vwap=1_010_000.0), "AAA", 1_010_000, 100, 91000000000, 91000000000, False)
    got_b = ev.on_tick(IndexData(vwap=1_020_000.0), "BBB", 1_020_000, 100, 91010000000, 91010000000, False)

    assert got_b is True
    info = ev.last_match_info["BBB"]
    assert info.raw_member_rank == 1


def test_long_mode_can_rank_between_85_and_95_pct_when_upper_bound_is_configured() -> None:
    ev = _make_eval("long", entry_max_vwap_pct_chg=0.095)

    ev.on_tick(IndexData(vwap=1_080_000.0), "BBB", 1_080_000, 100, 91000000000, 91000000000, False)
    got_a = ev.on_tick(IndexData(vwap=1_090_000.0), "AAA", 1_090_000, 100, 91010000000, 91010000000, False)

    assert got_a is True
    info = ev.last_match_info["AAA"]
    assert info.raw_member_rank == 1


def test_long_mode_keeps_legacy_85_pct_cutoff_by_default() -> None:
    ev = _make_eval("long")

    ev.on_tick(IndexData(vwap=1_080_000.0), "BBB", 1_080_000, 100, 91000000000, 91000000000, False)
    got_a = ev.on_tick(IndexData(vwap=1_090_000.0), "AAA", 1_090_000, 100, 91010000000, 91010000000, False)

    assert got_a is False
