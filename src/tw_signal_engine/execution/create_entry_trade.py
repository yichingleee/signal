"""Entry trade creation logic."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import ExecutionConfig, TradeMode
from tw_signal_engine.execution.position_sizing import compute_entry_quantity
from tw_signal_engine.execution.signal_policy import policy_for_signal
from tw_signal_engine.execution.taiwan_tick_size import get_price_cond
from tw_signal_engine.records.market_event_records import MarketTick
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData

PRICE_SCALE = 10000.0


@dataclass(slots=True, frozen=True)
class EntryFilterEvaluation:
    """Structured entry-filter evaluation shared by execution and dashboard."""

    allowed: bool
    block_reason: str | None
    entry_time_limit: bool
    prev_day_limit_up: bool
    no_entry_friday: bool
    max_0050_entry_chg: bool
    max_0050_intra_chg: bool
    volatility_pause: bool
    already_holding: bool
    single_forbidden: bool
    max_entry_price: bool


def _entry_fill_price(tick: MarketTick, trade_mode: TradeMode) -> int:
    if trade_mode == "short":
        return tick.bid[0].price if tick.bid[0].price > 0 else tick.match.price
    return tick.ask[0].price if tick.ask[0].price > 0 else tick.match.price


def evaluate_entry_filters(
    config: ExecutionConfig,
    trade_mode: TradeMode,
    tick: MarketTick,
    match_type: str,
    signal_type: str,
    pos: PositionState,
    is_friday: bool,
    p0050_prev: int,
    p0050_latest: int,
    market_open_chg_pct: float,
    strong_single_forbidden: dict[str, bool] | None = None,
) -> EntryFilterEvaluation:
    """Evaluate entry filters and return pass/fail flags with the first block reason."""
    del signal_type  # kept for API parity; current filters do not branch by signal.

    entry_time_limit = tick.match_time_str < config.entry_time_limit
    prev_day_limit_up = not (config.filter_prev_day_limit_up and tick.prev_limit_up)
    no_entry_friday = not (config.no_entry_friday and is_friday)

    max_0050_entry_chg = True
    if config.max_0050_entry_chg > 0 and p0050_prev > 0 and p0050_latest > 0:
        chg = (p0050_latest - p0050_prev) / p0050_prev * 100.0
        max_0050_entry_chg = chg < config.max_0050_entry_chg

    max_0050_intra_chg = True
    if config.max_0050_intra_chg < 99 and p0050_prev > 0 and p0050_latest > 0:
        entry_chg = (p0050_latest - p0050_prev) / p0050_prev * 100.0
        intra_chg = entry_chg - market_open_chg_pct
        max_0050_intra_chg = intra_chg < config.max_0050_intra_chg

    volatility_pause = not (config.disposition_stocks_enabled and tick.volatility_pause)
    already_holding = abs(pos.stocks.get(tick.symbol, 0)) <= 0.001
    single_forbidden = not (
        match_type == "StrongSingle"
        and strong_single_forbidden is not None
        and strong_single_forbidden.get(tick.symbol, False)
    )
    current_price = _entry_fill_price(tick, trade_mode) / PRICE_SCALE
    max_entry_price = not (config.max_entry_price > 0 and current_price > config.max_entry_price)

    block_reason: str | None = None
    if not entry_time_limit:
        block_reason = "entry_time_limit"
    elif not prev_day_limit_up:
        block_reason = "prev_day_limit_up"
    elif not no_entry_friday:
        block_reason = "no_entry_friday"
    elif not max_0050_entry_chg:
        block_reason = "max_0050_entry_chg"
    elif not max_0050_intra_chg:
        block_reason = "max_0050_intra_chg"
    elif not volatility_pause:
        block_reason = "volatility_pause"
    elif not already_holding:
        block_reason = "already_holding"
    elif not single_forbidden:
        block_reason = "single_forbidden"
    elif not max_entry_price:
        block_reason = "max_entry_price"

    return EntryFilterEvaluation(
        allowed=block_reason is None,
        block_reason=block_reason,
        entry_time_limit=entry_time_limit,
        prev_day_limit_up=prev_day_limit_up,
        no_entry_friday=no_entry_friday,
        max_0050_entry_chg=max_0050_entry_chg,
        max_0050_intra_chg=max_0050_intra_chg,
        volatility_pause=volatility_pause,
        already_holding=already_holding,
        single_forbidden=single_forbidden,
        max_entry_price=max_entry_price,
    )


def should_enter(
    config: ExecutionConfig,
    trade_mode: TradeMode,
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
    evaluation = evaluate_entry_filters(
        config=config,
        trade_mode=trade_mode,
        tick=tick,
        match_type=match_type,
        signal_type=signal_type,
        pos=pos,
        is_friday=is_friday,
        p0050_prev=p0050_prev,
        p0050_latest=p0050_latest,
        market_open_chg_pct=market_open_chg_pct,
        strong_single_forbidden=strong_single_forbidden,
    )
    return evaluation.allowed, evaluation.block_reason


def execute_entry(
    config: ExecutionConfig,
    trade_mode: TradeMode,
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
    policy = policy_for_signal(signal_type, config)
    side = "short" if trade_mode == "short" else "long"
    entry_fill_price = _entry_fill_price(tick, trade_mode)
    qty, _effective_position = compute_entry_quantity(
        config, entry_fill_price, tick.match.price, pos.trades_entered_today
    )
    signed_qty = -qty if trade_mode == "short" else qty
    pos.trades_entered_today += 1
    pos.stocks[tick.symbol] = signed_qty
    pos.profit_taken[tick.symbol] = False
    entry_cashflow = -signed_qty * (entry_fill_price / PRICE_SCALE)
    pos.cash += entry_cashflow
    pos.symbol_cash[tick.symbol] = pos.symbol_cash.get(tick.symbol, 0.0) + entry_cashflow

    current_price = entry_fill_price / PRICE_SCALE

    # Record open trade
    ot = EntryTrade(
        symbol=tick.symbol,
        side=side,
        signal_type=signal_type,
        enter_cause=match_type,
        entry_time_raw=tick.match_time_str,
        baseline=pos.symbol_cash[tick.symbol] - entry_cashflow,
        entry_price=current_price,
        entry_vwap=idx.vwap / 10000.0,
        day_high_at_entry=idx.day_high / 10000.0,
        is_prev_day_lu=tick.prev_limit_up,
        entry_qty=signed_qty,
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

    limit_up_int = 0
    if ref is not None:
        limit_up_int = int(ref.limit_up_price * 10000 + 0.5)

    if not policy.enable_take_profit:
        pos.orders[tick.symbol] = []
        pos.reserve_stocks[tick.symbol] = 0
        pos.limit_up_prices[tick.symbol] = limit_up_int if trade_mode != "short" else 0
        return

    # Place take-profit orders
    if trade_mode == "short":
        actual_splits = config.take_profit_splits
    else:
        actual_splits = config.take_profit_splits + config.reserve_limit_up_splits
    if actual_splits <= 0:
        raise ValueError(
            "Invalid take-profit split configuration for entry sizing: "
            f"symbol={tick.symbol} trade_mode={trade_mode} "
            f"take_profit_splits={config.take_profit_splits} "
            f"reserve_limit_up_splits={config.reserve_limit_up_splits} "
            f"actual_splits={actual_splits}"
        )
    q = abs(signed_qty) / actual_splits

    prices: list[int] = []
    if config.take_profit_pcts:
        tp_base = entry_fill_price if config.tp_base_entry else idx.day_high
        for i in range(min(config.take_profit_splits, len(config.take_profit_pcts))):
            if trade_mode == "short":
                p = int(tp_base * (1.0 - config.take_profit_pcts[i]) + 0.5)
            else:
                p = int(tp_base * (1.0 + config.take_profit_pcts[i]) + 0.5)
            if limit_up_int > 0 and p > limit_up_int:
                p = limit_up_int
            prices.append(p)
    else:
        for i in range(min(config.take_profit_splits, len(config.take_profit_tick_offsets))):
            offset = config.take_profit_tick_offsets[i]
            if trade_mode == "short":
                offset = -offset
            if offset == 0:
                prices.append(idx.day_high)
            else:
                prices.append(get_price_cond(tick.symbol, idx.day_high, offset))
        if limit_up_int > 0:
            prices = [min(p, limit_up_int) for p in prices]

    if trade_mode == "short":
        pos.reserve_stocks[tick.symbol] = 0.0
        pos.limit_up_prices[tick.symbol] = 0
    else:
        pos.reserve_stocks[tick.symbol] = q * config.reserve_limit_up_splits
        pos.limit_up_prices[tick.symbol] = limit_up_int
    pos.orders[tick.symbol] = [(p, q) for p in prices]
