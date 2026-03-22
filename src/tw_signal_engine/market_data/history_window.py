"""Named result object for historical data loaded by load_history_window."""

from __future__ import annotations

from dataclasses import dataclass, field

from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker


@dataclass(slots=True)
class HistoryWindow:
    """Holds the prior-session history needed by screeners.

    vol_cum: list of LinearVolumeTracker, one per prior session (index 0 = most recent prior day).
    trading_val: list of dicts mapping symbol -> total trading value for that day.
    source_dates: the dates used to build this window (newest first), for debugging.
    """

    vol_cum: list[LinearVolumeTracker] = field(default_factory=list)
    trading_val: list[dict[str, int]] = field(default_factory=list)
    source_dates: list[str] = field(default_factory=list)

    @property
    def num_days(self) -> int:
        return len(self.vol_cum)
