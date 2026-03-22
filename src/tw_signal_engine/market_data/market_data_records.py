"""Volume tracker and cumulative data structures for historical data."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class TickNode:
    timestamp: int = 0
    cumulative_qty: int = 0


class LinearVolumeTracker:
    """Cumulative volume/value tracker with amortized O(1) query using cursor."""

    def __init__(self) -> None:
        self.data_store: dict[str, list[TickNode]] = {}
        self._cursors: dict[str, int] = {}

    def on_tick(self, symbol: str, timestamp: int, qty: int) -> None:
        history = self.data_store.setdefault(symbol, [])
        current_total = history[-1].cumulative_qty if history else 0
        history.append(TickNode(timestamp=timestamp, cumulative_qty=current_total + qty))

    def query(self, symbol: str, timestamp: int) -> int:
        history = self.data_store.get(symbol)
        if not history:
            return 0

        cursor = self._cursors.get(symbol, 0)
        while cursor + 1 < len(history) and history[cursor + 1].timestamp <= timestamp:
            cursor += 1
        self._cursors[symbol] = cursor

        if history[cursor].timestamp > timestamp:
            return 0
        return history[cursor].cumulative_qty


@dataclass
class NumTracker:
    """Sliding window trade count tracker (circuit breaker detection)."""

    window_size_us: int = 600_000_000  # 10 minutes default
    _symbol_trades: dict[str, deque[int]] = field(default_factory=dict)

    def on_tick(self, symbol: str, timestamp: int) -> int:
        if symbol not in self._symbol_trades:
            self._symbol_trades[symbol] = deque()
        timestamps = self._symbol_trades[symbol]
        timestamps.append(timestamp)
        cutoff = timestamp - self.window_size_us
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        return len(timestamps)
