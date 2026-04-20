"""Signal A: VWAP touch + bounce detection."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import SignalAConfig
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.state.signal_state import SignalAState
from tw_signal_engine.state.symbol_state import IndexData


def evaluate_signal_a(
    state: SignalAState,
    config: SignalAConfig,
    idx: IndexData,
    price: int,
    match_time_str: int,
    match_time_us: int,
    match_type: str,
    f1: ReferenceSymbol | None,
) -> tuple[bool, str]:
    """Evaluate Signal A for one tick.

    Returns (triggered, trigger_match_type).
    """
    if state.triggered:
        return False, "None"
    if match_type == "None":
        if state.near_vwap:
            state.near_vwap = False
            state.low_since_near = 0
            state.high_since_near = 0
            state.near_vwap_time = 0
            state.near_vwap_time_us = 0
            state.near_vwap_pv_ratio = 0.0
        return False, "None"
    if match_time_str < config.entry_start_time or match_time_str >= config.entry_end_time:
        return False, "None"

    # Pre-condition check
    if match_time_str >= config.pre_condition_start_time:
        if price <= idx.vwap * config.pre_condition_vwap_ratio or state.forbidden:
            state.forbidden = True
            return False, "None"

    # Max increase ratio filter
    if f1 is not None:
        prev_close = f1.previous_close * 10000
        if prev_close > 0:
            pct_chg = (price - prev_close) / prev_close
            if pct_chg > config.trade_zone_max_increase_ratio:
                return False, "None"

    vwap = idx.vwap
    if vwap <= 0:
        return False, "None"

    pv_ratio = price / vwap

    # Phase 1: detect price approaching VWAP
    if not state.near_vwap:
        if pv_ratio <= config.vwap_near_ratio:
            state.near_vwap = True
            state.near_vwap_time = match_time_str
            state.near_vwap_time_us = match_time_us
            state.near_vwap_pv_ratio = pv_ratio
            state.low_since_near = price
            state.high_since_near = 0
        return False, "None"

    # Timeout check
    if config.max_near_to_entry_us > 0 and (match_time_us - state.near_vwap_time_us) > config.max_near_to_entry_us:
        state.triggered = True
        return False, "None"

    if price < state.low_since_near:
        state.low_since_near = price
    bounce = (
        (price - state.low_since_near) / state.low_since_near
        if state.low_since_near > 0
        else 0.0
    )
    if bounce >= config.bounce_ratio:
        state.triggered = True
        return True, match_type

    return False, "None"
