"""Backfill-then-live provider — replays file up to now, then switches to Redis."""

from __future__ import annotations

from collections.abc import Iterator

from tw_signal_engine.market_data.file_replay_provider import FileReplayProvider
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.market_data.redis_live_provider import RedisLiveProvider
from tw_signal_engine.records.market_event_records import MarketTick


class BackfillThenLiveProvider(MarketDataProvider):
    """Replays today's file up to current time, then switches to Redis live.

    Computes the cutover point from wall-clock time, replays all file ticks
    before that point, then yields from the Redis live provider.
    """

    def __init__(
        self,
        file_provider: FileReplayProvider,
        redis_provider: RedisLiveProvider,
        cutover_time_str: int | None = None,
    ) -> None:
        self.file_provider = file_provider
        self.redis_provider = redis_provider
        self._cutover_time_str = cutover_time_str

    def iterate_ticks(self) -> Iterator[MarketTick]:
        cutover = self._cutover_time_str
        if cutover is None:
            cutover = self._compute_cutover()

        # Phase 1: replay file ticks up to cutover
        seen_keys: set[tuple[str, int]] = set()
        for tick in self.file_provider.iterate_ticks():
            if tick.match_time_str >= cutover:
                break
            seen_keys.add((tick.symbol, tick.match_time_str))
            yield tick

        # Phase 2: switch to Redis live, dedup overlap
        for tick in self.redis_provider.iterate_ticks():
            key = (tick.symbol, tick.match_time_str)
            if key in seen_keys:
                continue
            yield tick

    def stop(self) -> None:
        """Signal stop to the Redis provider."""
        self.redis_provider.stop()

    @staticmethod
    def _compute_cutover() -> int:
        """Compute cutover time_str from current wall-clock time.

        Returns a match_time_str value 30 seconds before now to allow overlap.
        """
        from datetime import datetime

        now = datetime.now()
        # match_time_str format: HMMSS000000
        h, m, s = now.hour, now.minute, now.second
        # Subtract 30 seconds for overlap
        total_sec = h * 3600 + m * 60 + s - 30
        if total_sec < 0:
            total_sec = 0
        h2 = total_sec // 3600
        m2 = (total_sec % 3600) // 60
        s2 = total_sec % 60
        return (h2 * 10000 + m2 * 100 + s2) * 1_000_000
