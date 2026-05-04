"""Build/load helpers for precomputed 0050 parquet sidecars.

The parquet replay feed omits 00* symbols (including 0050). This module
extracts 0050 ticks from legacy text replay files once, stores them in small
per-date parquet artifacts, and loads those artifacts back as ``MarketTick``
objects for market-gate and entry-filter logic.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.replay.iterate_market_file import iterate_market_file

DEFAULT_0050_SIDECAR_DIR_NAME = "0050-sidecar"
SIDECAR_SCHEMA_VERSION = 1
SIDECAR_SYMBOL = "0050"
SIDECAR_ENV_VAR = "TW_SIGNAL_0050_SIDECAR_DIR"

_SIDECAR_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("market", pa.string()),
        pa.field("match_time_str", pa.int64()),
        pa.field("match_time_us", pa.int64()),
        pa.field("status_code", pa.int32()),
        pa.field("trade_code", pa.int32()),
        pa.field("price", pa.int64()),
        pa.field("qty", pa.int64()),
        pa.field("bid_price", pa.int64()),
        pa.field("ask_price", pa.int64()),
        pa.field("trade_at", pa.int8()),
    ]
)


@dataclass(frozen=True)
class Build0050SidecarResult:
    date: str
    path: Path
    row_count: int
    elapsed_sec: float
    status: str
    message: str = ""


def default_sidecar_root(data_dir: str | Path) -> Path:
    override = os.environ.get(SIDECAR_ENV_VAR)
    if override:
        return Path(override)
    return Path(data_dir).parent / DEFAULT_0050_SIDECAR_DIR_NAME


def sidecar_path(sidecar_root: str | Path, date: str) -> Path:
    return Path(sidecar_root) / SIDECAR_SYMBOL / f"{date}.parquet"


def sidecar_meta_path(sidecar_root: str | Path, date: str) -> Path:
    return Path(sidecar_root) / SIDECAR_SYMBOL / f"{date}.meta.json"


def _text_source_path(text_data_dir: str | Path, date: str) -> Path:
    return Path(text_data_dir) / f"TSEQuote.{date}"


def _assert_sidecar_schema(schema_or_table: pa.Schema | pa.Table) -> None:
    schema = schema_or_table if isinstance(schema_or_table, pa.Schema) else schema_or_table.schema
    missing: list[str] = []
    mistyped: list[str] = []
    for field in _SIDECAR_SCHEMA:
        if field.name not in schema.names:
            missing.append(field.name)
            continue
        actual = schema.field(field.name).type
        if not actual.equals(field.type):
            mistyped.append(f"{field.name}: expected {field.type}, got {actual}")
    if missing or mistyped:
        parts: list[str] = []
        if missing:
            parts.append(f"missing columns: {missing}")
        if mistyped:
            parts.append(f"mistyped columns: {mistyped}")
        raise ValueError("0050 sidecar schema mismatch — " + "; ".join(parts))


def _read_metadata(path: Path) -> dict[str, object] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def is_sidecar_fresh(date: str, text_data_dir: str | Path, sidecar_root: str | Path) -> bool:
    source_path = _text_source_path(text_data_dir, date)
    if not source_path.exists():
        return False

    parquet_path = sidecar_path(sidecar_root, date)
    meta_path = sidecar_meta_path(sidecar_root, date)
    if not parquet_path.exists() or not meta_path.exists():
        return False

    metadata = _read_metadata(meta_path)
    if metadata is None:
        return False

    source_stat = source_path.stat()
    return (
        metadata.get("source_size") == source_stat.st_size
        and metadata.get("source_mtime_ns") == source_stat.st_mtime_ns
        and metadata.get("schema_version") == SIDECAR_SCHEMA_VERSION
    )


def discover_text_dates(text_data_dir: str | Path, start: str, end: str) -> list[str]:
    root = Path(text_data_dir)
    if not root.exists():
        return []

    dates: list[str] = []
    for candidate in root.glob("TSEQuote.*"):
        suffix = candidate.name.split(".")[-1]
        if len(suffix) == 8 and suffix.isdigit() and start <= suffix <= end:
            dates.append(suffix)
    dates.sort()
    return dates


def _build_sidecar_table(date: str, text_data_dir: str | Path) -> tuple[pa.Table, int, int | None, int | None]:
    rows: list[tuple[MarketTick, int]] = []
    for idx, tick in enumerate(iterate_market_file("TSE", date, str(text_data_dir), {SIDECAR_SYMBOL})):
        rows.append((tick, idx))

    rows.sort(key=lambda item: (item[0].match_time_str, item[1]))

    symbols: list[str] = []
    markets: list[str] = []
    match_time_strs: list[int] = []
    match_time_uses: list[int] = []
    status_codes: list[int] = []
    trade_codes: list[int] = []
    prices: list[int] = []
    qtys: list[int] = []
    bid_prices: list[int] = []
    ask_prices: list[int] = []
    trade_ats: list[int] = []

    for tick, _ in rows:
        symbols.append(tick.symbol)
        markets.append(tick.market)
        match_time_strs.append(tick.match_time_str)
        match_time_uses.append(tick.match_time_us)
        status_codes.append(tick.status_code)
        trade_codes.append(tick.trade_code)
        prices.append(tick.match.price)
        qtys.append(tick.match.qty)
        bid_prices.append(tick.bid[0].price)
        ask_prices.append(tick.ask[0].price)
        trade_ats.append(tick.trade_at)

    table = pa.table(
        {
            "symbol": pa.array(symbols, type=pa.string()),
            "market": pa.array(markets, type=pa.string()),
            "match_time_str": pa.array(match_time_strs, type=pa.int64()),
            "match_time_us": pa.array(match_time_uses, type=pa.int64()),
            "status_code": pa.array(status_codes, type=pa.int32()),
            "trade_code": pa.array(trade_codes, type=pa.int32()),
            "price": pa.array(prices, type=pa.int64()),
            "qty": pa.array(qtys, type=pa.int64()),
            "bid_price": pa.array(bid_prices, type=pa.int64()),
            "ask_price": pa.array(ask_prices, type=pa.int64()),
            "trade_at": pa.array(trade_ats, type=pa.int8()),
        },
        schema=_SIDECAR_SCHEMA,
    )

    first_time = match_time_strs[0] if match_time_strs else None
    last_time = match_time_strs[-1] if match_time_strs else None
    return table, len(rows), first_time, last_time


def _tmp_path(final_path: Path) -> Path:
    return final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")


def build_0050_sidecar(
    date: str,
    text_data_dir: str | Path,
    sidecar_root: str | Path,
    force: bool = False,
) -> Build0050SidecarResult:
    started = time.perf_counter()
    output_path = sidecar_path(sidecar_root, date)
    meta_path = sidecar_meta_path(sidecar_root, date)

    if not force and is_sidecar_fresh(date, text_data_dir, sidecar_root):
        meta = _read_metadata(meta_path) or {}
        row_count_value = meta.get("row_count", 0)
        row_count = row_count_value if isinstance(row_count_value, int) else 0
        elapsed = time.perf_counter() - started
        return Build0050SidecarResult(
            date=date,
            path=output_path,
            row_count=row_count,
            elapsed_sec=elapsed,
            status="skipped_fresh",
            message="metadata and source stat match",
        )

    source_path = _text_source_path(text_data_dir, date)
    if not source_path.exists():
        elapsed = time.perf_counter() - started
        return Build0050SidecarResult(
            date=date,
            path=output_path,
            row_count=0,
            elapsed_sec=elapsed,
            status="failed",
            message=f"missing source file: {source_path}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    table, row_count, first_time, last_time = _build_sidecar_table(date, text_data_dir)
    _assert_sidecar_schema(table)

    tmp_parquet = _tmp_path(output_path)
    pq.write_table(table, str(tmp_parquet), compression="snappy")
    tmp_parquet.replace(output_path)

    source_stat = source_path.stat()
    metadata: dict[str, object] = {
        "date": date,
        "source_path": str(source_path),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "row_count": row_count,
        "first_match_time_str": first_time,
        "last_match_time_str": last_time,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "schema_version": SIDECAR_SCHEMA_VERSION,
    }

    tmp_meta = _tmp_path(meta_path)
    with tmp_meta.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_meta.replace(meta_path)

    elapsed = time.perf_counter() - started
    return Build0050SidecarResult(
        date=date,
        path=output_path,
        row_count=row_count,
        elapsed_sec=elapsed,
        status="built",
    )


def _is_sorted_non_decreasing(values: list[int]) -> bool:
    return all(left <= right for left, right in zip(values, values[1:]))


def load_0050_sidecar(date: str, sidecar_root: str | Path) -> Iterator[MarketTick]:
    path = sidecar_path(sidecar_root, date)
    if not path.exists():
        raise FileNotFoundError(path)

    _assert_sidecar_schema(pq.read_schema(str(path)))
    table = pq.read_table(str(path))
    _assert_sidecar_schema(table)

    times = table.column("match_time_str").to_pylist()
    if not _is_sorted_non_decreasing(times):
        table = table.sort_by([("match_time_str", "ascending")])
        times = table.column("match_time_str").to_pylist()

    symbols = table.column("symbol").to_pylist()
    markets = table.column("market").to_pylist()
    time_us = table.column("match_time_us").to_pylist()
    status_codes = table.column("status_code").to_pylist()
    trade_codes = table.column("trade_code").to_pylist()
    prices = table.column("price").to_pylist()
    qtys = table.column("qty").to_pylist()
    bid_prices = table.column("bid_price").to_pylist()
    ask_prices = table.column("ask_price").to_pylist()
    trade_ats = table.column("trade_at").to_pylist()

    for sym, market, t_str, t_us, status, trade_code, price, qty, bid, ask, trade_at in zip(
        symbols,
        markets,
        times,
        time_us,
        status_codes,
        trade_codes,
        prices,
        qtys,
        bid_prices,
        ask_prices,
        trade_ats,
    ):
        tick = MarketTick(
            symbol=sym,
            market=market,
            match_time_str=t_str,
            match_time_us=t_us,
            status_code=status,
            trade_code=trade_code,
            match=QuotePair(price=price, qty=qty),
            trade_at=trade_at,
        )
        tick.bid[0].price = bid
        tick.ask[0].price = ask
        yield tick
