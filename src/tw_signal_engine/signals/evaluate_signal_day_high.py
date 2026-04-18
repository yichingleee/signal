"""SignalDayHigh: intraday high, pullback, and breakout detection."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import SignalDayHighConfig
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.state.signal_state import SignalDayHighState


def _reset_for_new_high(state: SignalDayHighState, price: int, match_time_str: int) -> None:
    state.established_high = price
    state.established_high_time = match_time_str
    state.pullback_confirmed = False
    state.pullback_low = 0
    state.pullback_time = 0


def evaluate_signal_day_high(
    state: SignalDayHighState,
    config: SignalDayHighConfig,
    price: int,
    match_time_str: int,
    match_time_us: int,
    match_type: str,
    ref: ReferenceSymbol | None,
) -> tuple[bool, str]:
    """Evaluate SignalDayHigh for one tick.

    Returns (triggered, trigger_match_type).
    """
    del match_time_us  # kept for signature parity with other evaluators

    if state.symbol == "":
        state.symbol = ref.symbol if ref is not None else state.symbol

    if price <= 0:
        return False, "None"

    if state.established_high <= 0:
        _reset_for_new_high(state, price, match_time_str)
        return False, "None"

    # Before pullback, a new high resets the pattern anchor.
    if not state.pullback_confirmed and price > state.established_high:
        _reset_for_new_high(state, price, match_time_str)
        return False, "None"

    # Detect pullback from established high.
    if not state.pullback_confirmed:
        pullback_threshold = int(state.established_high * (1.0 - config.pullback_ratio) + 0.5)
        if price <= pullback_threshold:
            state.pullback_confirmed = True
            state.pullback_low = price
            state.pullback_time = match_time_str
        return False, "None"

    # After pullback confirmation, keep tracking the pullback low.
    if state.pullback_low <= 0 or price < state.pullback_low:
        state.pullback_low = price
        state.pullback_time = match_time_str

    if price <= state.established_high:
        return False, "None"

    # Breakout observed. Reset for a new cycle before evaluating trigger filters.
    trigger_high = state.established_high
    _reset_for_new_high(state, price, match_time_str)

    if state.triggered or state.entries >= config.max_entries_per_symbol:
        return False, "None"
    if match_type == "None":
        return False, "None"
    if match_time_str < config.entry_start_time or match_time_str >= config.entry_end_time:
        return False, "None"
    if ref is None:
        return False, "None"
    prev_close = ref.previous_close * 10000
    if prev_close <= 0:
        return False, "None"

    increase_ratio = (price - prev_close) / prev_close
    if increase_ratio < config.min_increase_ratio:
        return False, "None"

    # The upper bound is intentionally handled at screening level (VWAP ranking).
    _ = trigger_high
    state.triggered = True
    state.entries += 1
    return True, match_type
