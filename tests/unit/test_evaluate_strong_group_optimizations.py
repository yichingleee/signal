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
    entry_min_group_rank: int = 0,
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
        entry_min_group_rank=entry_min_group_rank,
        require_raw_m1=False,
        block_disposition_entry=False,
        entry_max_vol_ratio=entry_max_vol_ratio,
        entry_min_month_trading_val=0,
    )


def _make_evaluator(
    *,
    member_cond1_enabled: bool = True,
    entry_max_vol_ratio: float = 0.0,
    entry_min_group_rank: int = 0,
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
            entry_min_group_rank=entry_min_group_rank,
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


def test_day_high_selection_explanation_rejects_entry_min_group_rank_like_replay() -> None:
    ev = _make_evaluator(member_cond1_enabled=False, entry_min_group_rank=2)
    idx = IndexData(vwap=1_010_000.0)

    qualified = ev.on_tick(idx, "AAA", 1_010_000, 100, 91000000000, 91000000000, False)
    row = ev.explain_day_high_selection("AAA", idx, 1_010_000)

    assert qualified is False
    assert row.group_rank == 1
    assert row.member_rank == 1
    assert row.raw_member_rank == 1
    assert row.pass_entry_min_group_rank is False
    assert row.selected is False
    assert row.rejection_reason == "entry_min_group_rank"


def test_day_high_selection_explanation_rejects_entry_max_vol_ratio_like_replay() -> None:
    ev = _make_evaluator(member_cond1_enabled=False, entry_max_vol_ratio=1.0)
    idx = IndexData(vwap=1_010_000.0)

    qualified = ev.on_tick(idx, "AAA", 1_010_000, 100, 91000000000, 91000000000, False)
    row = ev.explain_day_high_selection("AAA", idx, 1_010_000)

    assert qualified is False
    assert row.group_rank == 1
    assert row.member_rank == 1
    assert row.raw_member_rank == 1
    assert row.vol_ratio >= 1.0
    assert row.pass_entry_max_vol_ratio is False
    assert row.selected is False
    assert row.rejection_reason == "entry_max_vol_ratio"


def _make_evaluator_for_guc(prices: dict[str, int]) -> StrongGroupEvaluator:
    """Build a 4-member group with explicit last-prices for the GUC test."""
    members = {"AAA", "BBB", "CCC", "DDD"}
    ev = _make_evaluator(
        symbol_to_groups={s: ["G1"] for s in members},
        group_members={"G1": set(members)},
        trading_val={s: 1_000_000 for s in members},
    )
    for sym, price in prices.items():
        ev.price_last[sym] = price
    return ev


def test_count_group_up_members_excludes_current_symbol_from_both_counts() -> None:
    """The entering candidate is excluded from up_count and total_members."""
    # AAA is the entering candidate; even at +5% (above 3% threshold) it should
    # not count toward up_count, and should not inflate total_members.
    ev = _make_evaluator_for_guc(
        {"AAA": 1_050_000, "BBB": 1_040_000, "CCC": 1_020_000, "DDD": 1_010_000}
    )

    up_count, total = ev.count_group_up_members("G1", current_symbol="AAA", threshold=0.03)

    # Only BBB is > +3%; CCC (+2%) and DDD (+1%) are not. AAA excluded entirely.
    assert up_count == 1
    assert total == 3


def test_count_group_up_members_uses_strict_greater_than_threshold() -> None:
    """A member at exactly the threshold must NOT count as up — strict ``>``.

    Uses ``threshold=0.0`` against a member whose price equals ``prev_close``
    so the ratio is *exactly* ``0.0`` with no FP artefact: ``0.0 > 0.0 == False``.
    """
    ev = _make_evaluator_for_guc(
        {"AAA": 1_000_000, "BBB": 1_000_000, "CCC": 1_000_001, "DDD": 999_999}
    )

    up_count, total = ev.count_group_up_members("G1", current_symbol="AAA", threshold=0.0)

    # BBB exactly at threshold → excluded by strict >; CCC just over → counted;
    # DDD just under → not counted but still counts toward total_members.
    assert up_count == 1
    assert total == 3


def test_count_group_up_members_skips_members_with_zero_price_or_no_prev_close() -> None:
    """Members lacking a usable last-price or prev_close drop out of total_members."""
    ev = _make_evaluator_for_guc(
        {"AAA": 1_000_000, "BBB": 1_040_000, "CCC": 0, "DDD": 1_050_000}
    )
    # Strip DDD's prev_close to simulate a member with no reference.
    ev._prev_close_cache["DDD"] = 0

    up_count, total = ev.count_group_up_members("G1", current_symbol="AAA", threshold=0.03)

    # AAA excluded (current). CCC (price=0) and DDD (prev_close<=0) drop out.
    # Only BBB remains and it is up.
    assert up_count == 1
    assert total == 1
