"""Optional callbacks invoked by the replay/live session at key points."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tw_signal_engine.records.market_event_records import MarketTick, TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.state.symbol_state import IndexData


@dataclass
class SessionHooks:
    """Optional callbacks invoked during the replay/live event loop.

    All callbacks default to None — when None, they are skipped with zero overhead.
    """

    on_tick: Callable[[MarketTick, IndexData], None] | None = None
    on_screening: Callable[[str, str, bool], None] | None = None
    on_signal: Callable[[str, str, bool], None] | None = None
    on_entry: Callable[[str, EntryTrade], None] | None = None
    on_exit: Callable[[str, str, TradeRecord], None] | None = None
    on_minute: Callable[[int], None] | None = None
