"""Twenty-day cumulative-volume history loader fed by the parquet tick root.

Drop-in replacement for ``load_history_window`` that produces the same
``HistoryWindow`` shape but reads from the new parquet root at
``/Users/liyijing/Projects/Trading/market-data/tick-data/`` instead of the
legacy ``TSEQuote.YYYYMMDD`` / ``OTCQuote.YYYYMMDD`` text files.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow.parquet as pq

from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_io import (
    PARQUET_HISTORY_COLUMNS,
    PARQUET_STATUS_EQ_FILTERS,
    parquet_path,
    to_int_price,
)

logger = logging.getLogger(__name__)

DAY_PER_MONTH = 20


def _convert_raw_time_to_us(raw_time: int) -> int:
    """Convert ``HHMMSSffffff`` to microseconds since midnight."""
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return (hours * 3600 + minutes * 60 + seconds) * 1_000_000 + micros


def _find_history_files(
    market_type: str,
    date: str,
    root: str | Path,
    require_target_file: bool = True,
) -> list[tuple[Path, str]]:
    """Locate up to 20 prior-session parquet files for ``market_type``.

    Returns a list of ``(path, file_date)`` tuples, newest first. The target
    replay date is excluded from the history window. ``require_target_file``
    matches the legacy text-loader contract: when True, the target date's own
    parquet file must exist or a ``FileNotFoundError`` is raised.
    """
    target_path = parquet_path(root, market_type, date)
    market_dir = target_path.parent
    if not market_dir.exists():
        raise FileNotFoundError(f"Parquet market directory not found: {market_dir}")

    if require_target_file and not target_path.exists():
        raise FileNotFoundError(f"Missing parquet file for {market_type} on {date}: {target_path}")

    date_file_map: dict[str, Path] = {}
    for entry in market_dir.iterdir():
        name = entry.name
        if not name.endswith(".parquet"):
            continue
        stem = name[: -len(".parquet")]
        if len(stem) == 8 and stem.isdigit():
            date_file_map[stem] = entry

    sorted_dates = sorted(date_file_map.keys())
    prior_dates = [d for d in sorted_dates if d < date]
    selected = prior_dates[-DAY_PER_MONTH:]
    selected.reverse()  # newest first
    return [(date_file_map[d], d) for d in selected]


def _load_one_day(
    path: Path,
) -> tuple[LinearVolumeTracker, dict[str, int]]:
    """Read a single prior-session parquet file into a tracker + value map.

    Mirrors the semantics of ``_parse_vol_cum_from_file`` in the legacy text
    loader: per-symbol cumulative volume nodes plus a ``qty * price // 10``
    trading-value running total per symbol.
    """
    table = pq.read_table(
        str(path),
        columns=PARQUET_HISTORY_COLUMNS,
        filters=PARQUET_STATUS_EQ_FILTERS,
    )
    table = table.sort_by([("symbol", "ascending"), ("time", "ascending")])

    symbols = table.column("symbol").to_pylist()
    times = table.column("time").to_pylist()
    prices = table.column("tradePrice").to_pylist()
    volumes = table.column("tradeVolume").to_pylist()

    tracker = LinearVolumeTracker()
    trading_val: dict[str, int] = {}

    for sym, raw_time, price, qty in zip(symbols, times, prices, volumes):
        ts_us = _convert_raw_time_to_us(raw_time)
        tracker.on_tick(sym, ts_us, qty)
        price_int = to_int_price(price)
        trading_val[sym] = trading_val.get(sym, 0) + qty * price_int // 10

    return tracker, trading_val


def load_parquet_history_window(
    market_type: str,
    date: str,
    root: str | Path,
    require_target_file: bool = True,
) -> HistoryWindow:
    """Load up to 20 prior-session parquet files into a ``HistoryWindow``.

    Returns the same shape as the legacy ``load_history_window``: index 0 is
    the most recent prior session, index 19 is the oldest. The target replay
    date is NOT included in history.

    When ``require_target_file`` is False, allows the caller to load history
    on a date whose own parquet file is absent (matches the existing
    text-loader contract for live mode).
    """
    files = _find_history_files(
        market_type,
        date,
        root,
        require_target_file=require_target_file,
    )

    vol_cum: list[LinearVolumeTracker] = []
    trading_val: list[dict[str, int]] = []
    source_dates: list[str] = []

    for path, file_date in files:
        tracker, tv = _load_one_day(path)
        vol_cum.append(tracker)
        trading_val.append(tv)
        source_dates.append(file_date)

    return HistoryWindow(
        vol_cum=vol_cum,
        trading_val=trading_val,
        source_dates=source_dates,
    )
