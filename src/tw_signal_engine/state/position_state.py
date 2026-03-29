"""Position and order tracking state."""

from __future__ import annotations

from dataclasses import dataclass, field

from tw_signal_engine.records.trade_records import EntryTrade


@dataclass
class PositionState:
    """Mutable state for order/position management."""

    cash: float = 0.0
    stocks: dict[str, float] = field(default_factory=dict)
    symbol_cash: dict[str, float] = field(default_factory=dict)
    orders: dict[str, list[tuple[int, float]]] = field(default_factory=dict)  # symbol -> [(price, qty)]
    profit_taken: dict[str, bool] = field(default_factory=dict)
    stopped_loss_symbols: set[str] = field(default_factory=set)
    entered_symbols: set[str] = field(default_factory=set)
    open_trades: dict[str, EntryTrade] = field(default_factory=dict)
    reserve_stocks: dict[str, float] = field(default_factory=dict)
    limit_up_prices: dict[str, int] = field(default_factory=dict)
    trades_entered_today: int = 0
    # MAE/MFE tracking: per-symbol lowest/highest price since entry
    trade_low: dict[str, int] = field(default_factory=dict)
    trade_high: dict[str, int] = field(default_factory=dict)
