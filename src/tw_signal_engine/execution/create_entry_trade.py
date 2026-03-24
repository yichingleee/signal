"""Entry trade creation logic."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig
from tw_signal_engine.execution.position_sizing import compute_entry_quantity
from tw_signal_engine.execution.taiwan_tick_size import get_price_cond
from tw_signal_engine.records.market_event_records import MarketTick
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData

PRICE_SCALE = 10000.0


def should_enter(
    config: ExecutionConfig,
    tick: MarketTick,
    match_type: str,
    signal_type: str,
    pos: PositionState,
    is_friday: bool,
    p0050_prev: int,
    p0050_latest: int,
    market_open_chg_pct: float,
    strong_single_forbidden: dict[str, bool] | None = None,
) -> tuple[bool, str | None]:
    """Check all entry filters. Returns (allowed, block_reason)."""
    if tick.match_time_str >= config.entry_time_limit:
        return False, "entry_time_limit"
    if config.filter_prev_day_limit_up and tick.prev_limit_up:
        return False, "prev_day_limit_up"
    if config.no_entry_friday and is_friday:
        return False, "no_entry_friday"
    if config.max_0050_entry_chg > 0 and p0050_prev > 0 and p0050_latest > 0:
        chg = (p0050_latest - p0050_prev) / p0050_prev * 100.0
        if chg >= config.max_0050_entry_chg:
            return False, "max_0050_entry_chg"
    if config.max_0050_intra_chg < 99 and p0050_prev > 0 and p0050_latest > 0:
        entry_chg = (p0050_latest - p0050_prev) / p0050_prev * 100.0
        intra_chg = entry_chg - market_open_chg_pct
        if intra_chg >= config.max_0050_intra_chg:
            return False, "max_0050_intra_chg"
    if config.disposition_stocks_enabled and tick.volatility_pause:
        return False, "volatility_pause"
    if pos.stocks.get(tick.symbol, 0) != 0:
        return False, "already_holding"
    if match_type == "StrongSingle" and strong_single_forbidden and strong_single_forbidden.get(tick.symbol, False):
        return False, "single_forbidden"
    current_price = (tick.ask[0].price if tick.ask[0].price > 0 else tick.match.price) / PRICE_SCALE
    if config.max_entry_price > 0 and current_price > config.max_entry_price:
        return False, "max_entry_price"
    return True, None


def execute_entry(
    config: ExecutionConfig,
    tick: MarketTick,
    idx: IndexData,
    match_type: str,
    signal_type: str,
    pos: PositionState,
    f1_map: dict[str, ReferenceSymbol],
    strong_group: StrongGroupEvaluator,
    p0050_prev: int,
    p0050_latest: int,
    market_open_chg_pct: float,
    near_vwap_time: int = 0,
    near_vwap_pv_ratio: float = 0.0,
) -> None:
    """Execute the entry: update position state, place take-profit orders."""
    qty, effective_position = compute_entry_quantity(
        config, tick.ask[0].price, tick.match.price, pos.trades_entered_today
    )
    pos.trades_entered_today += 1
    pos.stocks[tick.symbol] = qty
    pos.profit_taken[tick.symbol] = False
    pos.cash -= effective_position
    pos.symbol_cash[tick.symbol] = pos.symbol_cash.get(tick.symbol, 0.0) - effective_position

    current_price = (tick.ask[0].price if tick.ask[0].price > 0 else tick.match.price) / PRICE_SCALE

    # Record open trade
    ot = EntryTrade(
        symbol=tick.symbol,
        signal_type=signal_type,
        enter_cause=match_type,
        entry_time_raw=tick.match_time_str,
        baseline=pos.symbol_cash[tick.symbol] + effective_position,
        entry_price=current_price,
        entry_vwap=idx.vwap / 10000.0,
        day_high_at_entry=idx.day_high / 10000.0,
        is_prev_day_lu=tick.prev_limit_up,
    )

    mi = strong_group.last_match_info.get(tick.symbol)
    if mi is not None:
        ot.group_name = mi.group_name
        ot.group_rank = mi.group_rank
        ot.member_rank = mi.member_rank
        ot.raw_member_rank = mi.raw_member_rank
        ot.m1_symbol = mi.m1_symbol
        ot.vol_ratio = mi.vol_ratio
        ot.month_trading_val = mi.month_trading_val

    ref = f1_map.get(tick.symbol)
    if ref is not None:
        ot.prev_close = ref.previous_close
        ot.is_disposition = ref.security == "RR"
    ot.had_circuit_breaker = False  # could track circuit breaker symbols

    if ot.group_name:
        ot.group_limit_up_count = strong_group.get_group_limit_up_count(ot.group_name)
    if p0050_prev > 0 and p0050_latest > 0:
        ot.market_entry_chg_pct = (p0050_latest - p0050_prev) / p0050_prev * 100.0

    pos.open_trades[tick.symbol] = ot
    pos.entered_symbols.add(tick.symbol)

    # Place take-profit orders
    actual_splits = config.take_profit_splits + config.reserve_limit_up_splits
    q = qty / actual_splits

    limit_up_int = 0
    if ref is not None:
        limit_up_int = int(ref.limit_up_price * 10000 + 0.5)

    prices: list[int] = []
    if config.take_profit_pcts:
        tp_base = tick.match.price if config.tp_base_entry else idx.day_high
        for i in range(min(config.take_profit_splits, len(config.take_profit_pcts))):
            p = int(tp_base * (1.0 + config.take_profit_pcts[i]) + 0.5)
            if limit_up_int > 0 and p > limit_up_int:
                p = limit_up_int
            prices.append(p)
    else:
        for i in range(min(config.take_profit_splits, len(config.take_profit_tick_offsets))):
            offset = config.take_profit_tick_offsets[i]
            if offset == 0:
                prices.append(idx.day_high)
            else:
                prices.append(get_price_cond(tick.symbol, idx.day_high, offset))
        if limit_up_int > 0:
            prices = [min(p, limit_up_int) for p in prices]

    pos.reserve_stocks[tick.symbol] = q * config.reserve_limit_up_splits
    pos.limit_up_prices[tick.symbol] = limit_up_int
    pos.orders[tick.symbol] = [(p, q) for p in prices]
