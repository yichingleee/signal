"""Build and load binary volume caches for history-window acceleration.

Cache format: msgpack-serialized dict per market/date with:
- schema_version: int
- market: str
- date: str
- source_size: int (source file byte size for staleness check)
- source_mtime: float (source file mtime for staleness check)
- symbols: dict[str, SymbolCacheEntry]
  where each entry has:
    - vol_timeline: list of [timestamp_us, cumulative_qty] pairs
    - trading_val: int (total trading value)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker, TickNode
from tw_signal_engine.market_data.parse_history_trades import iter_history_trades

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
CACHE_DIR_NAME = "volcache"


def _cache_path(data_dir: str, market_type: str, date: str) -> Path:
    return Path(data_dir) / CACHE_DIR_NAME / f"{market_type}_{date}.json"


def _source_path(data_dir: str, market_type: str, date: str) -> Path:
    return Path(data_dir) / f"{market_type}Quote.{date}"


def build_cache(market_type: str, date: str, data_dir: str = "./data/") -> Path:
    """Build a cache file for one market/date from the raw replay file.

    Returns the path to the written cache file.
    """
    source = _source_path(data_dir, market_type, date)
    if not source.exists():
        raise FileNotFoundError(f"Source replay file not found: {source}")

    stat = source.stat()

    # Parse the file with lightweight parser
    vol_tracker = LinearVolumeTracker()
    trading_val: dict[str, int] = {}

    for trade in iter_history_trades(str(source)):
        vol_tracker.on_tick(trade.symbol, trade.match_time_us, trade.qty)
        trading_val[trade.symbol] = (
            trading_val.get(trade.symbol, 0) + trade.qty * trade.price // 10
        )

    # Serialize
    symbols_data: dict[str, dict[str, object]] = {}
    for sym, nodes in vol_tracker.data_store.items():
        symbols_data[sym] = {
            "vol_timeline": [[n.timestamp, n.cumulative_qty] for n in nodes],
            "trading_val": trading_val.get(sym, 0),
        }

    cache_data = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "market": market_type,
        "date": date,
        "source_size": stat.st_size,
        "source_mtime": stat.st_mtime,
        "symbols": symbols_data,
    }

    cache_file = _cache_path(data_dir, market_type, date)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache_data, separators=(",", ":")), encoding="utf-8")
    logger.info("Built cache: %s", cache_file)
    return cache_file


def is_cache_valid(market_type: str, date: str, data_dir: str = "./data/") -> bool:
    """Check if a cache file exists and is fresh relative to the source file."""
    cache_file = _cache_path(data_dir, market_type, date)
    if not cache_file.exists():
        return False

    source = _source_path(data_dir, market_type, date)
    if not source.exists():
        return False

    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    if raw.get("schema_version") != CACHE_SCHEMA_VERSION:
        return False

    stat = source.stat()
    if raw.get("source_size") != stat.st_size:
        return False
    if raw.get("source_mtime") != stat.st_mtime:
        return False

    return True


def load_cache(
    market_type: str,
    date: str,
    data_dir: str = "./data/",
) -> tuple[LinearVolumeTracker, dict[str, int]]:
    """Load a cached history day.

    Returns (vol_tracker, trading_val) matching the shape produced by
    _parse_vol_cum_from_file.
    """
    cache_file = _cache_path(data_dir, market_type, date)
    raw = json.loads(cache_file.read_text(encoding="utf-8"))

    vol_tracker = LinearVolumeTracker()
    trading_val: dict[str, int] = {}

    for sym, entry in raw["symbols"].items():
        nodes = [TickNode(timestamp=pair[0], cumulative_qty=pair[1]) for pair in entry["vol_timeline"]]
        vol_tracker.data_store[sym] = nodes
        trading_val[sym] = entry["trading_val"]

    return vol_tracker, trading_val


def ensure_caches(
    market_type: str,
    dates: list[str],
    data_dir: str = "./data/",
) -> None:
    """Ensure cache files exist for all given dates, building any that are missing or stale."""
    for date in dates:
        source = _source_path(data_dir, market_type, date)
        if not source.exists():
            continue
        if not is_cache_valid(market_type, date, data_dir):
            logger.info("Cache miss for %s %s, rebuilding...", market_type, date)
            build_cache(market_type, date, data_dir)
