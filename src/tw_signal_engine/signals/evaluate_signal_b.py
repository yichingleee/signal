"""Signal B: long-oriented rolling-low/volume state machine."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import SignalBConfig
from tw_signal_engine.execution.taiwan_tick_size import get_price_cond
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.state.signal_state import SignalBState
from tw_signal_engine.state.symbol_state import IndexData


def evaluate_signal_b(
    state: SignalBState,
    config: SignalBConfig,
    idx: IndexData,
    symbol: str,
    price: int,
    qty: int,
    match_time_str: int,
    match_time_us: int,
    trade_at: int,
    match_type: str,
    f1: ReferenceSymbol | None,
    is_stopped_loss: bool,
) -> tuple[bool, str]:
    """Evaluate Signal B (long-only). Returns (triggered, trigger_match_type)."""
    if not config.enabled:
        return False, "None"

    # Update rolling windows
    inner_vol = qty if trade_at == 1 else 0
    state.rolling_sum_short.update(match_time_us, inner_vol)
    rs_short = state.rolling_sum_short.get_sum()

    state.rolling_sum_long.update(match_time_us, inner_vol)
    rs_long = state.rolling_sum_long.get_sum()

    if rs_long != 0:
        state.rolling_sum_ratio = (
            (rs_short / rs_long)
            * (config.rolling_sum_long_duration_us / config.rolling_sum_short_duration_us)
        )
    else:
        state.rolling_sum_ratio = 0.0

    state.rolling_low.update(match_time_us, price)
    state.rolling_low_val = state.rolling_low.get_low()
    idx.rolling_low = state.rolling_low_val

    if is_stopped_loss:
        state.forbidden = True
    if state.forbidden:
        return False, "None"

    # Pre-condition
    if match_time_str >= config.pre_condition_start_time:
        if price <= idx.vwap * config.pre_condition_vwap_ratio or state.forbidden:
            state.forbidden = True
            return False, "None"

    trigger = False
    trigger_match_type = "None"

    # Track zone evaluation
    if match_type != "None":
        cond1 = (
            price <= idx.day_high * config.track_zone_day_high_ratio
            and price >= idx.vwap * config.track_zone_vwap_ratio
        )
        cond2 = price <= state.rolling_low_val
        if cond1 and cond2:
            state.in_buffer_zone = True
            state.buffer_zone_trigger_price = price
            state.buffer_zone_start_time = match_time_us
            state.buffer_zone_match_type = match_type

    # Buffer zone
    if state.in_buffer_zone:
        # Exit check
        cond1 = match_time_us - state.buffer_zone_start_time > config.buffer_zone_duration_us
        cond2 = price >= state.buffer_zone_trigger_price * config.buffer_zone_exit_price_ratio
        if cond1 or cond2:
            state.in_buffer_zone = False
            state.buffer_zone_trigger_price = -1
            state.buffer_zone_start_time = -1
            state.buffer_zone_match_type = "None"
        else:
            # Eval check
            if config.buffer_zone_start_time <= match_time_str < config.buffer_zone_end_time:
                vol_cond = state.rolling_sum_ratio < config.vol_contract_ratio
                if f1 is not None:
                    prev_close = f1.previous_close * 10000
                    rl_increase = (idx.rolling_low - prev_close) / prev_close if prev_close > 0 else 0.0
                    price_cond = rl_increase >= config.buffer_zone_rolling_low_increase_ratio
                else:
                    price_cond = False
                if vol_cond and price_cond:
                    state.in_trade_zone = True
                    state.trade_zone_trigger_price = state.buffer_zone_trigger_price
                    state.trade_zone_start_time = match_time_us
                    state.trade_zone_match_type = state.buffer_zone_match_type

    # Trade zone
    if state.in_trade_zone:
        # Exit check
        cond1 = match_time_us - state.trade_zone_start_time > config.trade_zone_duration_us
        cond2 = price <= get_price_cond(symbol, state.trade_zone_trigger_price, -config.trade_zone_exit_tick_sub)
        if cond1 or cond2:
            state.in_trade_zone = False
            state.trade_zone_trigger_price = -1
            state.trade_zone_start_time = -1
            state.trade_zone_match_type = "None"
        else:
            # Eval check
            cond1 = price >= state.trade_zone_trigger_price * config.trade_zone_eval_price_ratio
            eval_price = get_price_cond(symbol, state.trade_zone_trigger_price, config.trade_zone_eval_tick_add)
            cond2 = price >= eval_price
            if f1 is not None:
                prev_close = f1.previous_close * 10000
                dh_increase = (idx.day_high - prev_close) / prev_close if prev_close > 0 else 0.0
                cond3 = dh_increase > config.trade_zone_eval_day_high_increase_ratio
            else:
                cond3 = False
            if cond1 and cond2 and cond3:
                state.in_trade_zone = False
                if match_time_str >= config.trade_zone_start_time:
                    trigger = True
                    trigger_match_type = match_type if match_type != "None" else state.trade_zone_match_type

    return trigger, trigger_match_type
