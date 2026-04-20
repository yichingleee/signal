"""Bailout exit rule: exit when price drops significantly after take-profit."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import ExecutionConfig, TradeMode
from tw_signal_engine.execution.apply_stop_loss_exit import _close_position
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData


def check_bailout(
    config: ExecutionConfig,
    trade_mode: TradeMode,
    symbol: str,
    price: int,
    bid_price: int,
    ask_price: int,
    entry_idx: IndexData,
    pos: PositionState,
) -> bool:
    """Check and execute bailout. Returns True if bailed out."""
    if not pos.profit_taken.get(symbol, False):
        return False

    if trade_mode == "short":
        if config.bailout_ratio <= 0:
            return False
        if entry_idx.day_low > 0 and price >= entry_idx.day_low / config.bailout_ratio:
            _close_position(symbol, price, bid_price, ask_price, pos, trade_mode)
            return True
    elif price <= entry_idx.day_high * config.bailout_ratio:
        _close_position(symbol, price, bid_price, ask_price, pos, trade_mode)
        return True
    return False
