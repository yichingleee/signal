"""Stop-loss exit rule."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig, TradeMode
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData

PRICE_SCALE = 10000.0


def check_stop_loss(
    config: ExecutionConfig,
    trade_mode: TradeMode,
    symbol: str,
    price: int,
    bid_price: int,
    ask_price: int,
    signal_type: str,
    entry_idx: IndexData,
    pos: PositionState,
) -> bool:
    """Check and execute stop-loss. Returns True if stopped out."""
    if signal_type == "SignalA":
        if trade_mode == "short":
            if entry_idx.vwap <= 0:
                return False
            if config.stop_loss_ratio_a <= 0:
                return False
            should_stop = price >= entry_idx.vwap / config.stop_loss_ratio_a
        else:
            should_stop = price <= entry_idx.vwap * config.stop_loss_ratio_a
        if should_stop:
            _close_position(symbol, price, bid_price, ask_price, pos, trade_mode)
            pos.stopped_loss_symbols.add(symbol)
            return True
    elif signal_type == "SignalB":
        if trade_mode == "short":
            if entry_idx.rolling_low <= 0:
                return False
            if config.stop_loss_ratio_b <= 0:
                return False
            should_stop = price >= entry_idx.rolling_low / config.stop_loss_ratio_b
        else:
            should_stop = price <= entry_idx.rolling_low * config.stop_loss_ratio_b
        if should_stop:
            _close_position(symbol, price, bid_price, ask_price, pos, trade_mode)
            pos.stopped_loss_symbols.add(symbol)
            return True
    return False


def _close_position(
    symbol: str,
    match_price: int,
    bid_price: int,
    ask_price: int,
    pos: PositionState,
    trade_mode: TradeMode,
) -> None:
    """Close entire position at market price."""
    if trade_mode == "short":
        market_price = ask_price if ask_price > 0 else match_price
    else:
        market_price = bid_price if bid_price > 0 else match_price
    market_price_actual = market_price / PRICE_SCALE
    qty = pos.stocks.get(symbol, 0)
    cashflow = qty * market_price_actual
    pos.cash += cashflow
    pos.symbol_cash[symbol] = pos.symbol_cash.get(symbol, 0.0) + cashflow
    pos.stocks[symbol] = 0
    pos.orders[symbol] = []
    pos.reserve_stocks[symbol] = 0
    pos.profit_taken[symbol] = False

    # Fix floating point residual
    if abs(pos.symbol_cash.get(symbol, 0)) < 1.0:
        pos.cash -= pos.symbol_cash.get(symbol, 0)
        pos.symbol_cash[symbol] = 0
