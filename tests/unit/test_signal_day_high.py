"""Unit tests for SignalDayHigh evaluator."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import SignalDayHighConfig
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.signals.evaluate_signal_day_high import evaluate_signal_day_high
from tw_signal_engine.state.signal_state import SignalDayHighState


def _ref(prev_close: float = 100.0) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol="2330",
        name="TSMC",
        market="TSE",
        previous_close=prev_close,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


def test_initial_high_tracking_and_new_high_reset_before_pullback() -> None:
    state = SignalDayHighState(symbol="2330")
    cfg = SignalDayHighConfig(enabled=True)

    triggered, _ = evaluate_signal_day_high(
        state, cfg, 1_050_000, 93000000000, 0, "None", _ref()
    )
    assert triggered is False
    assert state.established_high == 1_050_000
    assert state.pullback_confirmed is False

    triggered, _ = evaluate_signal_day_high(
        state, cfg, 1_060_000, 93010000000, 0, "None", _ref()
    )
    assert triggered is False
    assert state.established_high == 1_060_000
    assert state.pullback_confirmed is False
    assert state.pullback_low == 0


def test_pullback_confirmation_and_lower_low_tracking() -> None:
    state = SignalDayHighState(symbol="2330", established_high=1_060_000, established_high_time=93000000000)
    cfg = SignalDayHighConfig(enabled=True, pullback_ratio=0.01)

    triggered, _ = evaluate_signal_day_high(
        state, cfg, 1_049_000, 93010000000, 0, "None", _ref()
    )
    assert triggered is False
    assert state.pullback_confirmed is True
    assert state.pullback_low == 1_049_000

    triggered, _ = evaluate_signal_day_high(
        state, cfg, 1_045_000, 93020000000, 0, "None", _ref()
    )
    assert triggered is False
    assert state.pullback_low == 1_045_000


def test_breakout_triggers_once_when_filters_pass() -> None:
    state = SignalDayHighState(
        symbol="2330",
        established_high=1_060_000,
        established_high_time=93000000000,
        pullback_confirmed=True,
        pullback_low=1_049_000,
        pullback_time=93010000000,
    )
    cfg = SignalDayHighConfig(enabled=True, min_increase_ratio=0.06, max_entries_per_symbol=1)

    triggered, mt = evaluate_signal_day_high(
        state, cfg, 1_061_000, 93020000000, 0, "StrongGroup", _ref()
    )
    assert triggered is True
    assert mt == "StrongGroup"
    assert state.triggered is True
    assert state.entries == 1

    triggered_again, _ = evaluate_signal_day_high(
        state, cfg, 1_070_000, 93030000000, 0, "StrongGroup", _ref()
    )
    assert triggered_again is False


def test_breakout_preserves_context_for_dashboard_rows() -> None:
    state = SignalDayHighState(
        symbol="2330",
        established_high=1_060_000,
        established_high_time=930_000_00000,
        pullback_confirmed=True,
        pullback_low=1_049_000,
        pullback_time=930_100_00000,
    )
    cfg = SignalDayHighConfig(
        enabled=True,
        min_increase_ratio=0.06,
        max_entries_per_symbol=1,
        entry_start_time=905_000_00000,
        entry_end_time=100_000_000000,
    )

    triggered, mt = evaluate_signal_day_high(
        state, cfg, 1_061_000, 930_200_00000, 0, "StrongGroup", _ref()
    )

    assert triggered is True
    assert mt == "StrongGroup"
    assert state.last_trigger_high == 1_060_000
    assert state.last_trigger_high_time == 930_000_00000
    assert state.last_trigger_pullback_low == 1_049_000
    assert state.last_trigger_pullback_time == 930_100_00000
    assert state.last_trigger_time == 930_200_00000
    assert state.triggered is True
    assert state.entries == 1
    assert state.established_high == 1_061_000


def test_entry_window_and_match_type_and_min_increase_filters() -> None:
    cfg = SignalDayHighConfig(
        enabled=True,
        entry_start_time=90500000000,
        entry_end_time=100000000000,
        min_increase_ratio=0.06,
    )

    # Before entry window.
    state_before = SignalDayHighState(
        symbol="2330",
        established_high=1_060_000,
        pullback_confirmed=True,
        pullback_low=1_040_000,
    )
    triggered, _ = evaluate_signal_day_high(
        state_before, cfg, 1_061_000, 90459000000, 0, "StrongGroup", _ref()
    )
    assert triggered is False

    # match_type must be non-None on breakout tick.
    state_no_match = SignalDayHighState(
        symbol="2330",
        established_high=1_060_000,
        pullback_confirmed=True,
        pullback_low=1_040_000,
    )
    triggered, _ = evaluate_signal_day_high(
        state_no_match, cfg, 1_061_000, 93000000000, 0, "None", _ref()
    )
    assert triggered is False

    # Current price must be at least +6% from previous close.
    state_low_increase = SignalDayHighState(
        symbol="2330",
        established_high=1_020_000,
        pullback_confirmed=True,
        pullback_low=1_005_000,
    )
    triggered, _ = evaluate_signal_day_high(
        state_low_increase, cfg, 1_021_000, 93000000000, 0, "StrongGroup", _ref()
    )
    assert triggered is False
