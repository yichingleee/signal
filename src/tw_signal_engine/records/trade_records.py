"""Trade-related immutable records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EntryTrade:
    """Snapshot of state at time of entry."""

    symbol: str
    signal_type: str
    enter_cause: str
    entry_time_raw: int = 0
    baseline: float = 0.0
    had_take_profit: bool = False
    group_name: str = ""
    group_rank: int = 0
    member_rank: int = 0
    raw_member_rank: int = 0
    m1_symbol: str = ""
    entry_price: float = 0.0
    entry_vwap: float = 0.0
    day_high_at_entry: float = 0.0
    prev_close: float = 0.0
    vol_ratio: float = 0.0
    month_trading_val: int = 0
    is_prev_day_lu: bool = False
    is_disposition: bool = False
    had_circuit_breaker: bool = False
    group_limit_up_count: int = 0
    market_entry_chg_pct: float = 0.0
    # TP slice tracking
    first_tp_time_raw: int = 0
    tp_slices_filled: int = 0
    tp_realized_pnl: float = 0.0
