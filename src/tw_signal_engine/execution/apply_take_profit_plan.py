"""Take-profit order execution."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import TradeMode
from tw_signal_engine.state.position_state import PositionState

PRICE_SCALE = 10000.0


def check_take_profit(
    symbol: str,
    price: int,
    trade_mode: TradeMode,
    pos: PositionState,
    match_time_str: int = 0,
) -> bool:
    """Check and fill take-profit orders. Returns True if any filled."""
    orders = pos.orders.get(symbol, [])
    if not orders:
        return False

    ever_taken = False
    remaining: list[tuple[int, float]] = []
    for order_price, qty in orders:
        should_fill = price <= order_price if trade_mode == "short" else price >= order_price
        if should_fill:
            if trade_mode == "short":
                cashflow = -qty * order_price / PRICE_SCALE
                pos.stocks[symbol] = pos.stocks.get(symbol, 0) + qty
            else:
                cashflow = qty * order_price / PRICE_SCALE
                pos.stocks[symbol] = pos.stocks.get(symbol, 0) - qty
            pos.cash += cashflow
            pos.symbol_cash[symbol] = pos.symbol_cash.get(symbol, 0.0) + cashflow
            ever_taken = True
            # Track TP slice fills on the open trade
            ot = pos.open_trades.get(symbol)
            if ot is not None:
                ot.tp_slices_filled += 1
                # Track profit (not revenue) relative to entry price
                entry_price_int = int(ot.entry_price * PRICE_SCALE + 0.5)
                side_sign = -1.0 if ot.side == "short" else 1.0
                tp_profit = side_sign * qty * (order_price - entry_price_int) / PRICE_SCALE
                ot.tp_realized_pnl += tp_profit
                if ot.first_tp_time_raw == 0 and match_time_str > 0:
                    ot.first_tp_time_raw = match_time_str
        else:
            remaining.append((order_price, qty))
    pos.orders[symbol] = remaining

    if abs(pos.stocks.get(symbol, 0)) < 0.001:
        pos.stocks[symbol] = 0

    if ever_taken:
        pos.profit_taken[symbol] = True

    return ever_taken
