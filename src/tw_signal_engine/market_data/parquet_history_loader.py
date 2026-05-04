"""Twenty-day cumulative-volume history loader fed by the parquet tick root.

Produces the same ``HistoryWindow`` shape as the text loader, while enforcing
the parquet source contract independently from legacy text output.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_history_cache import (
    BuildParquetHistoryCacheResult,
    default_parquet_history_cache_root,
    is_parquet_history_cache_fresh,
    load_parquet_history_cache,
    read_parquet_history_cache_metadata,
    write_parquet_history_cache,
)
from tw_signal_engine.market_data.parquet_io import (
    PARQUET_HISTORY_COLUMNS,
    PARQUET_STATUS_EQ_FILTERS,
    assert_history_schema,
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
) -> tuple[LinearVolumeTracker, dict[str, int], int]:
    """Read a single prior-session parquet file into a tracker + value map.

    Mirrors the semantics of ``_parse_vol_cum_from_file`` in the legacy text
    loader: per-symbol cumulative volume nodes plus a ``qty * price // 10``
    trading-value running total per symbol.
    """
    assert_history_schema(pq.read_schema(str(path)))
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
        if qty < 0:
            raise ValueError(f"parquet history source contract violation: negative tradeVolume for {sym} in {path}")
        ts_us = _convert_raw_time_to_us(raw_time)
        tracker.on_tick(sym, ts_us, qty)
        price_int = to_int_price(price)
        trading_val[sym] = trading_val.get(sym, 0) + qty * price_int // 10

    return tracker, trading_val, table.num_rows


def build_parquet_history_day_cache(
    market_type: str,
    date: str,
    root: str | Path,
    *,
    cache_root: str | Path | None = None,
    force: bool = False,
) -> BuildParquetHistoryCacheResult:
    """Build one parquet history cache entry for ``(market_type, date)``."""
    started = time.perf_counter()
    source_path = parquet_path(root, market_type, date)
    resolved_cache_root = cache_root or default_parquet_history_cache_root(root)

    if not source_path.exists():
        elapsed = time.perf_counter() - started
        return BuildParquetHistoryCacheResult(
            market=market_type,
            date=date,
            path=source_path,
            row_count=0,
            elapsed_sec=elapsed,
            status="failed",
            message=f"missing source file: {source_path}",
        )

    if not force and is_parquet_history_cache_fresh(market_type, date, root, resolved_cache_root):
        meta = read_parquet_history_cache_metadata(market_type, date, resolved_cache_root) or {}
        row_count_value = meta.get("row_count", 0)
        row_count = row_count_value if isinstance(row_count_value, int) else 0
        elapsed = time.perf_counter() - started
        return BuildParquetHistoryCacheResult(
            market=market_type,
            date=date,
            path=source_path,
            row_count=row_count,
            elapsed_sec=elapsed,
            status="skipped_fresh",
            message="metadata and source stat match",
        )

    tracker, trading_val, row_count = _load_one_day(source_path)
    cache_path = write_parquet_history_cache(
        market_type=market_type,
        date=date,
        parquet_root=root,
        cache_root=resolved_cache_root,
        tracker=tracker,
        trading_val=trading_val,
        row_count=row_count,
    )
    elapsed = time.perf_counter() - started
    return BuildParquetHistoryCacheResult(
        market=market_type,
        date=date,
        path=cache_path,
        row_count=row_count,
        elapsed_sec=elapsed,
        status="built",
    )


def load_parquet_history_day(
    market_type: str,
    date: str,
    root: str | Path,
    *,
    use_cache: bool = True,
    write_cache: bool = True,
    cache_root: str | Path | None = None,
) -> tuple[LinearVolumeTracker, dict[str, int]]:
    """Load one day of prior-session history, optionally via day cache."""
    source_path = parquet_path(root, market_type, date)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    resolved_cache_root = cache_root or default_parquet_history_cache_root(root)
    if use_cache and is_parquet_history_cache_fresh(market_type, date, root, resolved_cache_root):
        try:
            return load_parquet_history_cache(market_type, date, resolved_cache_root)
        except (OSError, ValueError):
            logger.warning(
                "Parquet history cache unreadable for %s %s; reparsing source",
                market_type,
                date,
            )

    tracker, trading_val, row_count = _load_one_day(source_path)

    if use_cache and write_cache:
        try:
            write_parquet_history_cache(
                market_type=market_type,
                date=date,
                parquet_root=root,
                cache_root=resolved_cache_root,
                tracker=tracker,
                trading_val=trading_val,
                row_count=row_count,
            )
        except OSError:
            logger.warning("Failed to write parquet history cache for %s %s", market_type, date)

    return tracker, trading_val


def load_parquet_history_window(
    market_type: str,
    date: str,
    root: str | Path,
    require_target_file: bool = True,
    use_cache: bool = True,
    write_cache: bool = True,
    cache_root: str | Path | None = None,
) -> HistoryWindow:
    """Load up to 20 prior-session parquet files into a ``HistoryWindow``.

    Returns the same shape as the legacy ``load_history_window``: index 0 is
    the most recent prior session, index 19 is the oldest. The target replay
    date is NOT included in history.

    When ``require_target_file`` is False, allows the caller to load history on
    a date whose own parquet file is absent (matches the existing text-loader
    contract for live mode).

    When ``use_cache`` is True, each prior day is loaded from the binary cache
    when fresh. On cache miss/staleness the loader reparses parquet and, when
    ``write_cache`` is True, rewrites the day cache artifact.
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

    for _path, file_date in files:
        tracker, tv = load_parquet_history_day(
            market_type,
            file_date,
            root,
            use_cache=use_cache,
            write_cache=write_cache,
            cache_root=cache_root,
        )
        vol_cum.append(tracker)
        trading_val.append(tv)
        source_dates.append(file_date)

    return HistoryWindow(
        vol_cum=vol_cum,
        trading_val=trading_val,
        source_dates=source_dates,
    )
