"""Rolling history provider for batch replay mode.

Maintains a sliding window of prior-session history, advancing one day at a time
so adjacent dates share already-loaded sessions instead of rebuilding from scratch.
"""

from __future__ import annotations

import logging
from collections import deque

from tw_signal_engine.market_data.build_volume_caches import (
    is_cache_valid,
    load_cache,
)
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.load_history_window import (
    _find_history_files,
)
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker

logger = logging.getLogger(__name__)


class RollingHistoryProvider:
    """Maintains a rolling window of history across batch dates.

    For each new date, reuses already-loaded sessions and only loads
    the newly needed prior session(s).
    """

    def __init__(self, market_type: str, data_dir: str, use_cache: bool = True) -> None:
        self.market_type = market_type
        self.data_dir = data_dir
        self.use_cache = use_cache

        # Current window state: newest-first deques
        self._dates: deque[str] = deque()
        self._vol_cum: deque[LinearVolumeTracker] = deque()
        self._trading_val: deque[dict[str, int]] = deque()

    def get_history(self, target_date: str) -> HistoryWindow:
        """Get the history window for target_date, reusing loaded sessions."""
        needed_files = _find_history_files(self.market_type, target_date, self.data_dir)
        needed_dates = [d for _, d in needed_files]

        if not needed_dates:
            return HistoryWindow()

        # Find overlap with current window
        current_set = set(self._dates)
        to_load = [d for d in needed_dates if d not in current_set]
        to_drop = current_set - set(needed_dates)

        # Drop dates no longer needed (from the oldest end)
        while self._dates and self._dates[-1] in to_drop:
            self._dates.pop()
            self._vol_cum.pop()
            self._trading_val.pop()

        # Load new dates
        filepath_map = {d: fp for fp, d in needed_files}
        for date in to_load:
            tracker, tv = self._load_one(date, filepath_map.get(date, ""))
            # Insert at the correct position (maintain newest-first order)
            self._dates.appendleft(date)
            self._vol_cum.appendleft(tracker)
            self._trading_val.appendleft(tv)

        # Rebuild in the correct order (newest first, matching needed_dates)
        date_to_idx: dict[str, int] = {}
        for i, d in enumerate(self._dates):
            date_to_idx[d] = i

        vol_cum: list[LinearVolumeTracker] = []
        trading_val: list[dict[str, int]] = []
        source_dates: list[str] = []

        for d in needed_dates:
            idx = date_to_idx.get(d)
            if idx is not None:
                vol_cum.append(self._vol_cum[idx])
                trading_val.append(self._trading_val[idx])
                source_dates.append(d)

        return HistoryWindow(
            vol_cum=vol_cum,
            trading_val=trading_val,
            source_dates=source_dates,
        )

    def _load_one(self, date: str, filepath: str) -> tuple[LinearVolumeTracker, dict[str, int]]:
        """Load a single day, preferring cache."""
        if self.use_cache:
            if is_cache_valid(self.market_type, date, self.data_dir):
                return load_cache(self.market_type, date, self.data_dir)
            logger.info("Cache miss: %s %s, falling back to text parse", self.market_type, date)

        from tw_signal_engine.market_data.load_history_window import _parse_vol_cum_from_file

        tracker = LinearVolumeTracker()
        tv: dict[str, int] = {}
        _parse_vol_cum_from_file(filepath, tracker, tv)
        return tracker, tv
