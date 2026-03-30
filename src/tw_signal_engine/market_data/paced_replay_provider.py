"""Paced replay provider — wraps any provider with wall-clock delays."""

from __future__ import annotations

import time
from collections.abc import Iterator

from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.records.market_event_records import MarketTick


class PacedReplayProvider(MarketDataProvider):
    """Wraps another provider with wall-clock delays to simulate live pacing.

    Uses match_time_us differences scaled by speed to insert sleep delays.
    """

    def __init__(
        self,
        inner: MarketDataProvider,
        speed: float = 1.0,
    ) -> None:
        self.inner = inner
        self.speed = speed

    def iterate_ticks(self) -> Iterator[MarketTick]:
        start_wall: float | None = None
        start_data: float | None = None

        for tick in self.inner.iterate_ticks():
            data_time_sec = tick.match_time_us / 1_000_000.0

            if start_wall is None:
                start_wall = time.time()
                start_data = data_time_sec
            else:
                assert start_data is not None
                target_delay = (data_time_sec - start_data) / self.speed
                actual_delay = time.time() - start_wall
                sleep_needed = target_delay - actual_delay
                if sleep_needed > 0:
                    time.sleep(sleep_needed)

            yield tick
