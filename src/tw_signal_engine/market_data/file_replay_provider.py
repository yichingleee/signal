"""File-based replay provider — wraps merge_market_streams."""

from __future__ import annotations

from collections.abc import Iterator

from tw_signal_engine.market_data.market_data_records import NumTracker
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.records.market_event_records import MarketTick
from tw_signal_engine.replay.merge_market_streams import merge_market_streams


class FileReplayProvider(MarketDataProvider):
    """Yields MarketTick events from OTC + TSE replay files merged by time."""

    def __init__(
        self,
        otc_date: str,
        tse_date: str,
        data_dir: str = "./data/",
        tick_filter: set[str] | None = None,
        prev_day_limit_up: dict[str, bool] | None = None,
        num_tracker: NumTracker | None = None,
    ) -> None:
        self.otc_date = otc_date
        self.tse_date = tse_date
        self.data_dir = data_dir
        self.tick_filter = tick_filter
        self.prev_day_limit_up = prev_day_limit_up
        self.num_tracker = num_tracker

    def iterate_ticks(self) -> Iterator[MarketTick]:
        yield from merge_market_streams(
            "OTC",
            self.otc_date,
            "TSE",
            self.tse_date,
            data_dir=self.data_dir,
            tick_filter=self.tick_filter,
            prev_day_limit_up=self.prev_day_limit_up,
            num_tracker=self.num_tracker,
        )
