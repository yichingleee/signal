"""Load prior-session history window of cumulative volume/value data."""

from __future__ import annotations

import logging
from pathlib import Path

from tw_signal_engine.market_data.build_volume_caches import (
    is_cache_valid,
    load_cache,
)
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parse_history_trades import iter_history_trades

logger = logging.getLogger(__name__)

DAY_PER_MONTH = 20


def _find_history_files(market_type: str, date: str, data_dir: str = "./data/") -> list[tuple[str, str]]:
    """Find up to 20 prior-session replay files for the given market, before date.

    Returns list of (filepath, date_str) tuples, newest first.
    The target replay date is excluded from history.
    """
    data_path = Path(data_dir)
    prefix = f"{market_type}Quote"
    target_file = data_path / f"{prefix}.{date}"
    date_file_map: dict[str, str] = {}

    if not data_path.exists():
        raise FileNotFoundError(f"Replay data directory not found: {data_path}")

    for entry in data_path.iterdir():
        name = entry.name
        if name.startswith(prefix) and "." in name:
            file_date = name.split(".")[-1]
            if len(file_date) == 8:
                date_file_map[file_date] = str(entry)

    if date not in date_file_map:
        raise FileNotFoundError(f"Missing replay file for {market_type} on {date}: {target_file}")

    sorted_dates = sorted(date_file_map.keys())
    # Only prior sessions (strictly before the target date)
    prior_dates = [d for d in sorted_dates if d < date]

    # Take up to DAY_PER_MONTH most recent prior sessions
    selected = prior_dates[-DAY_PER_MONTH:]
    selected.reverse()  # newest first
    return [(date_file_map[d], d) for d in selected]


def _parse_vol_cum_from_file(
    filename: str,
    vol_tracker: LinearVolumeTracker,
    trading_val: dict[str, int],
) -> None:
    """Read a replay file and populate cumulative volume and trading-value data.

    Uses the lightweight history parser (no MarketTick allocation).
    """
    for trade in iter_history_trades(filename):
        vol_tracker.on_tick(trade.symbol, trade.match_time_us, trade.qty)
        trading_val[trade.symbol] = (
            trading_val.get(trade.symbol, 0) + trade.qty * trade.price // 10
        )


def _load_one_day(
    market_type: str,
    file_date: str,
    filepath: str,
    data_dir: str,
    use_cache: bool,
) -> tuple[LinearVolumeTracker, dict[str, int]]:
    """Load one day of history, using cache if available and valid."""
    if use_cache:
        if is_cache_valid(market_type, file_date, data_dir):
            logger.debug("Cache hit: %s %s", market_type, file_date)
            return load_cache(market_type, file_date, data_dir)
        else:
            logger.info("Cache miss: %s %s, falling back to text parse", market_type, file_date)

    # No cache: parse from text
    tracker = LinearVolumeTracker()
    tv: dict[str, int] = {}
    _parse_vol_cum_from_file(filepath, tracker, tv)
    return tracker, tv


def load_history_window(
    market_type: str,
    date: str,
    data_dir: str = "./data/",
    use_cache: bool = True,
) -> HistoryWindow:
    """Load prior-session history window.

    Returns a HistoryWindow with up to 20 prior sessions.
    Index 0 = most recent prior session, index 19 = oldest.
    The target replay date is NOT included in history.

    When use_cache is True (default), attempts to load from binary cache,
    building the cache on first access or when stale.
    """
    files = _find_history_files(market_type, date, data_dir)

    vol_cum: list[LinearVolumeTracker] = []
    trading_val: list[dict[str, int]] = []
    source_dates: list[str] = []

    for filepath, file_date in files:
        tracker, tv = _load_one_day(market_type, file_date, filepath, data_dir, use_cache)
        vol_cum.append(tracker)
        trading_val.append(tv)
        source_dates.append(file_date)

    return HistoryWindow(
        vol_cum=vol_cum,
        trading_val=trading_val,
        source_dates=source_dates,
    )
