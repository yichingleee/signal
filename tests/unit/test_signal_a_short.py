"""Short-mode Signal A mirror behavior tests."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import SignalAConfig
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.signals.evaluate_signal_a import evaluate_signal_a
from tw_signal_engine.state.signal_state import SignalAState
from tw_signal_engine.state.symbol_state import IndexData


def _ref() -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol="2330",
        name="TSMC",
        market="TSE",
        previous_close=100.0,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="semi",
        security="",
        error_code="0",
    )


def test_short_signal_a_arms_and_triggers_on_rejection() -> None:
    config = SignalAConfig(
        enabled=True,
        short_vwap_near_ratio=0.995,
        bounce_ratio=0.01,
        entry_start_time=90000000000,
        entry_end_time=110000000000,
        pre_condition_start_time=90000000000,
        short_pre_condition_vwap_ratio=1.03,
    )
    state = SignalAState(symbol="2330")
    idx = IndexData(vwap=1000000.0, day_high=1020000, day_low=980000)

    triggered, _ = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1000000,
        91000000000,
        1,
        "StrongGroup",
        _ref(),
    )
    assert triggered is False
    assert state.near_vwap is True
    assert state.high_since_near == 1000000

    triggered, _ = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1020000,
        91050000000,
        2,
        "StrongGroup",
        _ref(),
    )
    assert triggered is False
    assert state.high_since_near == 1020000

    triggered, match_type = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1005000,
        91100000000,
        3,
        "StrongGroup",
        _ref(),
    )
    assert triggered is True
    assert match_type == "StrongGroup"


def test_short_signal_a_precondition_forbids_when_price_too_strong() -> None:
    config = SignalAConfig(
        enabled=True,
        pre_condition_start_time=90000000000,
        short_pre_condition_vwap_ratio=1.01,
        entry_start_time=90000000000,
        entry_end_time=110000000000,
    )
    state = SignalAState(symbol="2330")
    idx = IndexData(vwap=1000000.0)

    triggered, match_type = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1011000,
        90500000000,
        1,
        "StrongGroup",
        _ref(),
    )
    assert triggered is False
    assert match_type == "None"
    assert state.forbidden is True


def test_match_type_none_resets_short_near_state() -> None:
    state = SignalAState(symbol="2330", near_vwap=True, high_since_near=1010000, near_vwap_time=91000000000)
    config = SignalAConfig(entry_start_time=90000000000, entry_end_time=110000000000)
    idx = IndexData(vwap=1000000.0)

    triggered, match_type = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1005000,
        91100000000,
        10,
        "None",
        _ref(),
    )

    assert triggered is False
    assert match_type == "None"
    assert state.near_vwap is False
    assert state.high_since_near == 0


def test_short_signal_a_timeout_marks_triggered() -> None:
    config = SignalAConfig(
        enabled=True,
        short_vwap_near_ratio=0.995,
        max_near_to_entry_us=2,
        entry_start_time=90000000000,
        entry_end_time=110000000000,
    )
    state = SignalAState(symbol="2330")
    idx = IndexData(vwap=1000000.0)

    evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1000000,
        91000000000,
        1,
        "StrongGroup",
        _ref(),
    )
    triggered, match_type = evaluate_signal_a(
        state,
        config,
        "short",
        idx,
        1000000,
        91000000000,
        10,
        "StrongGroup",
        _ref(),
    )

    assert triggered is False
    assert match_type == "None"
    assert state.triggered is True
