"""Abstract base for market data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from tw_signal_engine.records.market_event_records import MarketTick


class MarketDataProvider(ABC):
    """Abstract source of MarketTick events."""

    @abstractmethod
    def iterate_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects in chronological order."""
