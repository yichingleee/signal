"""Abstract base for market data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from tw_signal_engine.records.market_event_records import MarketTick


@dataclass
class LiveFeedStatus:
    """Structured status for live-capable market data providers."""

    source: str = "redis"
    connected: bool = False
    subscribed_channels: int = 0
    last_message_at: str = ""
    last_tick_time_raw: int = 0
    reconnect_count: int = 0
    parse_error_count: int = 0
    ignored_message_count: int = 0
    dropped_tick_count: int = 0
    queue_depth: int = 0
    last_error: str = ""


class MarketDataProvider(ABC):
    """Abstract source of MarketTick events."""

    @abstractmethod
    def iterate_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects in chronological order."""

    def start_listener(self) -> None:
        """Optionally start background I/O before iterate_ticks is called (default: no-op)."""

    def get_status(self) -> LiveFeedStatus | None:
        """Return structured live feed status when supported."""
        return None
