"""Immutable market event records."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QuotePair:
    price: int = 0  # price * 10000
    qty: int = 0


@dataclass(slots=True)
class MarketTick:
    """A single parsed tick from replay data. Prices are int * 10000."""

    symbol: str = ""
    market: str = ""
    match_time_str: int = 0  # e.g. 91500000000
    match_time_us: int = 0  # microseconds since midnight
    status_code: int = 0
    trade_code: int = 0
    match: QuotePair = field(default_factory=QuotePair)
    bid: list[QuotePair] = field(default_factory=lambda: [QuotePair() for _ in range(5)])
    ask: list[QuotePair] = field(default_factory=lambda: [QuotePair() for _ in range(5)])
    trade_at: int = 0  # 1=inner(bid), 2=outer(ask), 0=unknown
    is_limit_up_locked: bool = False
    is_limit_down_locked: bool = False
    prev_limit_up: bool = False
    volatility_pause: bool = False
    total_match_qty: int = 0
    total_bid_qty: int = 0
    total_ask_qty: int = 0


@dataclass(slots=True)
class TradeRecord:
    """Completed trade for report generation."""

    symbol: str = ""
    side: str = "long"
    signal_type: str = ""  # "SignalA", "SignalB", "SignalBoth"
    enter_cause: str = ""  # "StrongGroup", "StrongSingle", "Both"
    final_leave_cause: str = ""
    entry_time_raw: int = 0
    exit_time_raw: int = 0
    pnl: float = 0.0
    return_pct: float = 0.0
    had_take_profit: bool = False
    group_name: str = ""
    group_rank: int = 0
    member_rank: int = 0
    raw_member_rank: int = 0
    m1_symbol: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
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
    # Trade path fields
    mae_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_price: float = 0.0
    mfe_price: float = 0.0
    time_to_first_tp_sec: int = 0
    tp_slices_filled: int = 0
    tp_pnl: float = 0.0
    residual_pnl: float = 0.0
    # Cost model fields
    gross_pnl: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0
    net_pnl: float = 0.0
    # Context fields
    trade_date: str = ""
    exit_trade_date: str = ""
    is_overnight: bool = False
    entry_hour_bucket: str = ""
