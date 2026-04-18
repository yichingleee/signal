"""Records for cross-day overnight holding carry."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.state.symbol_state import IndexData


@dataclass(slots=True)
class OvernightHolding:
    entry_trade: EntryTrade
    qty: float
    entry_idx: IndexData
    entry_signal_type: str
    carry_from_date: str
    limit_up_price: int
