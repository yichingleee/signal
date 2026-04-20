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
        is_weighted_avg=False,
        group_vol_ratio_exempt_threshold=0,
        filter_prev_day_limit_up=True,
        exclude_prev_limit_up_from_rank=False,
        exclude_disposition_from_rank=False,
        member_cond1_enabled=member_cond1_enabled,
        member_cond2_enabled=False,
        member_cond4_enabled=False,
        entry_min_vwap_pct_chg=0.0,
        entry_max_vwap_pct_chg=0.0,
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
) -> StrongGroupEvaluator:
    symbol_to_groups = {"AAA": ["G1"]}
    group_members = {"G1": {"AAA"}}
    vol_cum = [LinearVolumeTracker()]
    trading_val = [{"AAA": 1_000_000} for _ in range(21)]
    f1_map = {"AAA": _ref("AAA")}

    ev = StrongGroupEvaluator(
        config=_make_config(
            member_cond1_enabled=member_cond1_enabled,
            entry_max_vol_ratio=entry_max_vol_ratio,
        ),
        symbol_to_groups=symbol_to_groups,
        group_members=group_members,
        vol_cum=vol_cum,
        trading_val=trading_val,
        f1_map=f1_map,
        prev_day_limit_up={},
        trade_mode="long",
    )
    ev.initialize_validity()
    return ev


def test_group_percentage_is_computed_once_per_group_tick_when_validated_and_ranked() -> None:
    ev = _make_evaluator()
    calls = {"n": 0}
    original = ev._group_percentage_chg

    def _counted(group: str, weighted_avg: bool) -> float:
        calls["n"] += 1
        return original(group, weighted_avg)

    ev._group_percentage_chg = _counted

    qualified = ev.on_tick(IndexData(vwap=1_010_000.0), "AAA", 1_010_000, 100, 91000000000, 91000000000, False)

    assert qualified is True
    assert calls["n"] == 1


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
