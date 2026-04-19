"""Rolling history provider for parquet batch replay mode.

Reuses already-loaded prior sessions across adjacent dates, and loads only the
newly required prior day when the replay date advances by one session.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_history_loader import (
    _find_history_files,
    load_parquet_history_day,
)


class ParquetRollingHistoryProvider:
    """Maintain a rolling prior-session history window for one market."""

    def __init__(
        self,
        market_type: str,
        data_dir: str | Path,
        *,
        use_cache: bool = True,
        write_cache: bool = True,
        cache_root: str | Path | None = None,
    ) -> None:
        self.market_type = market_type
        self.data_dir = str(data_dir)
        self.use_cache = use_cache
        self.write_cache = write_cache
        self.cache_root = cache_root

        self._dates: deque[str] = deque()
        self._vol_cum: deque[LinearVolumeTracker] = deque()
        self._trading_val: deque[dict[str, int]] = deque()

    def get_history(self, target_date: str) -> HistoryWindow:
        """Return history window for ``target_date`` with maximal reuse."""
        needed_files = _find_history_files(self.market_type, target_date, self.data_dir)
        needed_dates = [d for _, d in needed_files]
        if not needed_dates:
            return HistoryWindow()

        current: dict[str, tuple[LinearVolumeTracker, dict[str, int]]] = {
            date: (self._vol_cum[idx], self._trading_val[idx])
            for idx, date in enumerate(self._dates)
        }

        vol_cum: list[LinearVolumeTracker] = []
        trading_val: list[dict[str, int]] = []
        source_dates: list[str] = []

        for date in needed_dates:
            entry = current.get(date)
            if entry is None:
                tracker, tv = load_parquet_history_day(
                    self.market_type,
                    date,
                    self.data_dir,
                    use_cache=self.use_cache,
                    write_cache=self.write_cache,
                    cache_root=self.cache_root,
                )
            else:
                tracker, tv = entry
            vol_cum.append(tracker)
            trading_val.append(tv)
            source_dates.append(date)

        self._dates = deque(source_dates)
        self._vol_cum = deque(vol_cum)
        self._trading_val = deque(trading_val)

        return HistoryWindow(
            vol_cum=vol_cum,
            trading_val=trading_val,
            source_dates=source_dates,
        )
