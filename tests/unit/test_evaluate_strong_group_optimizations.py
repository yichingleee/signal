"""Optimization-focused tests for strong-group screening hot paths."""

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


def _make_config(
    *,
    member_cond1_enabled: bool = True,
    entry_max_vol_ratio: float = 0.0,
    is_weighted_avg: bool = False,
    entry_max_vwap_pct_chg: float = 0.0,
) -> StrongGroupConfig:
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
        top_group_min_select=0,
        normal_group_max_select=1,
        normal_group_min_select=0,
        member_vwap_pct_chg_threshold=0.0,
        group_valid_top_n=10,
        is_weighted_avg=is_weighted_avg,
        group_vol_ratio_exempt_threshold=0,
        filter_prev_day_limit_up=True,
        exclude_prev_limit_up_from_rank=False,
        exclude_disposition_from_rank=False,
        member_cond1_enabled=member_cond1_enabled,
        member_cond2_enabled=False,
        member_cond4_enabled=False,
        entry_min_vwap_pct_chg=0.0,
        entry_max_vwap_pct_chg=entry_max_vwap_pct_chg,
        entry_min_group_rank=0,
        require_raw_m1=False,
        block_disposition_entry=False,
        entry_max_vol_ratio=entry_max_vol_ratio,
        entry_min_month_trading_val=0,
    )


def _make_evaluator(
    *,
    member_cond1_enabled: bool = True,
    entry_max_vol_ratio: float = 0.0,
    is_weighted_avg: bool = False,
    trade_mode: str = "long",
    symbol_to_groups: dict[str, list[str]] | None = None,
    group_members: dict[str, set[str]] | None = None,
    trading_val: dict[str, int] | None = None,
) -> StrongGroupEvaluator:
    if symbol_to_groups is None:
        symbol_to_groups = {"AAA": ["G1"]}
    if group_members is None:
        group_members = {"G1": {"AAA"}}
    if trading_val is None:
        trading_val = {"AAA": 1_000_000}
    vol_cum = [LinearVolumeTracker()]
    trading_val_histories = [dict(trading_val) for _ in range(21)]
    symbols = sorted({symbol for symbols in group_members.values() for symbol in symbols})
    f1_map = {symbol: _ref(symbol) for symbol in symbols}

    ev = StrongGroupEvaluator(
        config=_make_config(
            member_cond1_enabled=member_cond1_enabled,
            entry_max_vol_ratio=entry_max_vol_ratio,
            is_weighted_avg=is_weighted_avg,
        ),
        symbol_to_groups=symbol_to_groups,
        group_members=group_members,
        vol_cum=vol_cum,
        trading_val=trading_val_histories,
        f1_map=f1_map,
        prev_day_limit_up={},
        trade_mode=trade_mode,
    )
    ev.initialize_validity()
    return ev


def test_cached_group_average_is_used_instead_of_full_scan_in_hot_path() -> None:
    ev = _make_evaluator()
    calls = {"n": 0}
    original = ev._group_percentage_chg

    def _counted(group: str, weighted_avg: bool) -> float:
        calls["n"] += 1
        return original(group, weighted_avg)

    ev._group_percentage_chg = _counted

    qualified = ev.on_tick(IndexData(vwap=1_010_000.0), "AAA", 1_010_000, 100, 91000000000, 91000000000, False)

    assert qualified is True
    assert calls["n"] == 0


def test_unweighted_group_average_matches_slow_formula_for_single_member() -> None:
    ev = _make_evaluator()

    for i, price in enumerate((1_000_000, 1_015_000, 1_025_000, 1_010_000)):
        ev.on_tick(IndexData(vwap=float(price)), "AAA", price, 100, 91000000000 + i, 91000000000 + i, False)
        fast = ev._current_group_avg_pct("G1")
        slow = ev._group_percentage_chg_slow("G1", False)
        assert abs(fast - slow) < 1e-12


def test_unweighted_group_average_matches_slow_formula_for_multiple_members_with_staggered_ticks() -> None:
    ev = _make_evaluator(
        symbol_to_groups={"AAA": ["G1"], "BBB": ["G1"]},
        group_members={"G1": {"AAA", "BBB"}},
        trading_val={"AAA": 1_000_000, "BBB": 1_000_000},
    )

    updates = [
        ("AAA", 1_020_000, 50),
        ("BBB", 1_010_000, 40),
        ("AAA", 1_000_000, 30),
        ("BBB", 990_000, 60),
    ]
    for i, (symbol, price, qty) in enumerate(updates):
        ev.on_tick(IndexData(vwap=float(price)), symbol, price, qty, 91000000000 + i, 91000000000 + i, False)
        fast = ev._current_group_avg_pct("G1")
        slow = ev._group_percentage_chg_slow("G1", False)
        assert abs(fast - slow) < 1e-12


def test_weighted_group_average_matches_slow_formula_across_cumulative_volume_changes() -> None:
    ev = _make_evaluator(
        is_weighted_avg=True,
        symbol_to_groups={"AAA": ["G1"], "BBB": ["G1"]},
        group_members={"G1": {"AAA", "BBB"}},
        trading_val={"AAA": 2_000_000, "BBB": 1_000_000},
    )

    updates = [
        ("AAA", 1_020_000, 100),
        ("BBB", 1_040_000, 10),
        ("AAA", 1_010_000, 150),
        ("BBB", 990_000, 30),
    ]
    for i, (symbol, price, qty) in enumerate(updates):
        ev.on_tick(IndexData(vwap=float(price)), symbol, price, qty, 91000000000 + i, 91000000000 + i, False)
        fast = ev._current_group_avg_pct("G1")
        slow = ev._group_percentage_chg_slow("G1", True)
        assert abs(fast - slow) < 1e-12


def test_symbol_in_multiple_groups_updates_each_group_cache() -> None:
    ev = _make_evaluator(
        symbol_to_groups={"AAA": ["G1", "G2"], "BBB": ["G1"], "CCC": ["G2"]},
        group_members={"G1": {"AAA", "BBB"}, "G2": {"AAA", "CCC"}},
        trading_val={"AAA": 1_000_000, "BBB": 1_000_000, "CCC": 1_000_000},
    )

    updates = [
        ("AAA", 1_020_000, 100),
        ("BBB", 1_010_000, 100),
        ("CCC", 1_030_000, 100),
        ("AAA", 990_000, 100),
    ]
    for i, (symbol, price, qty) in enumerate(updates):
        ev.on_tick(IndexData(vwap=float(price)), symbol, price, qty, 91000000000 + i, 91000000000 + i, False)
        assert abs(ev._current_group_avg_pct("G1") - ev._group_percentage_chg_slow("G1", False)) < 1e-12
        assert abs(ev._current_group_avg_pct("G2") - ev._group_percentage_chg_slow("G2", False)) < 1e-12


def test_short_mode_cached_average_remains_sign_consistent_with_slow_path() -> None:
    ev = _make_evaluator(trade_mode="short")

    for i, price in enumerate((970_000, 980_000, 940_000)):
        ev.on_tick(IndexData(vwap=float(price)), "AAA", price, 100, 91000000000 + i, 91000000000 + i, False)
        fast = ev._current_group_avg_pct("G1")
        slow = ev._group_percentage_chg_slow("G1", False)
        assert fast < 0.0
        assert abs(fast - slow) < 1e-12


def test_snapshot_avg_pct_matches_slow_group_formula() -> None:
    ev = _make_evaluator(
        symbol_to_groups={"AAA": ["G1"], "BBB": ["G1"]},
        group_members={"G1": {"AAA", "BBB"}},
        trading_val={"AAA": 1_000_000, "BBB": 1_000_000},
    )

    ev.on_tick(IndexData(vwap=1_020_000.0), "AAA", 1_020_000, 120, 91000000000, 91000000000, False)
    ev.on_tick(IndexData(vwap=1_010_000.0), "BBB", 1_010_000, 120, 91010000000, 91010000000, False)
    snapshots = ev.to_snapshot({"AAA": IndexData(vwap=1_020_000.0), "BBB": IndexData(vwap=1_010_000.0)})

    assert len(snapshots) == 1
    assert abs(snapshots[0].avg_pct_chg - ev._group_percentage_chg_slow("G1", False)) < 1e-12


def test_no_rolling_volume_query_when_no_enabled_filter_or_entry_ratio_conditions() -> None:
    def _fail_monthly_volume_average(symbol: str, match_time_us: int) -> int:
        raise AssertionError("20-day rolling-volume query should not run under this config")

    ev = _make_evaluator(member_cond1_enabled=False, entry_max_vol_ratio=0.0)
    ev._monthly_volume_average = _fail_monthly_volume_average
    assert ev.on_tick(
        IndexData(vwap=1_100_000.0),
        "AAA",
        1_100_000,
        100,
        91000000000,
        91000000000,
        False,
    ) is False
