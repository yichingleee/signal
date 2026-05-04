"""Optional callbacks invoked by the replay/live session at key points."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tw_signal_engine.records.market_event_records import MarketTick, TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.state.symbol_state import IndexData


@dataclass(slots=True)
class ScreeningDetail:
    """Expanded screening snapshot for diagnostic investigations."""

    symbol: str = ""
    match_time_str: int = 0
    match_time_us: int = 0
    vwap: float = 0.0
    day_high: int = 0
    day_low: int = 0
    match_type: str = "None"
    qualified: bool = False
    strong_group: bool = False
    strong_single: bool = False
    group_name: str = ""
    group_rank: int = 0
    member_rank: int = 0
    raw_member_rank: int = 0
    m1_symbol: str = ""
    vol_ratio: float = 0.0
    month_trading_val: int = 0
    ahead_symbol: str = ""
    behind_symbol: str = ""


@dataclass
class SessionHooks:
    """Optional callbacks invoked during the replay/live event loop.

    All callbacks default to None — when None, they are skipped with zero overhead.
    """

    on_tick: Callable[[MarketTick, IndexData], None] | None = None
    on_screening: Callable[[str, str, bool], None] | None = None
    on_screening_detail: Callable[[ScreeningDetail], None] | None = None
    on_signal: Callable[[str, str, bool], None] | None = None
    on_entry: Callable[[str, EntryTrade], None] | None = None
    on_exit: Callable[[str, str, TradeRecord], None] | None = None
    on_minute: Callable[[int], None] | None = None
