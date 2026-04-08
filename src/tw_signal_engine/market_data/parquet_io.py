"""Shared helpers for the parquet market-data ingestion path.

These primitives are imported by ``parquet_history_loader`` and
``parquet_replay_provider``. They centralize:

* the canonical column projections (so the file is read once with the
  smallest possible footprint),
* the float -> ``int * 10000`` price conversion (which must use ``round``,
  never ``int``, to dodge IEEE-754 quantization errors), and
* the schema assertion (so a feed change surfaces with a clear error
  instead of a silently corrupt cumulative volume).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

PARQUET_REPLAY_COLUMNS: list[str] = [
    "symbol",
    "time",
    "matchFlag",
    "tradePrice",
    "tradeVolume",
    "buyPrice1",
    "sellPrice1",
]

PARQUET_HISTORY_COLUMNS: list[str] = [
    "symbol",
    "time",
    "tradePrice",
    "tradeVolume",
]

# Legacy status_code==0-equivalent rows in parquet:
# - matchFlag "Y" rows only
# - regular session (>= 09:00)
PARQUET_STATUS_EQ_FILTERS: list[tuple[str, str, object]] = [
    ("matchFlag", "==", "Y"),
    ("time", ">=", 90_000_000_000),
]


_REPLAY_SCHEMA: dict[str, pa.DataType] = {
    "symbol": pa.string(),
    "time": pa.int64(),
    "matchFlag": pa.string(),
    "tradePrice": pa.float64(),
    "tradeVolume": pa.int32(),
    "buyPrice1": pa.float64(),
    "sellPrice1": pa.float64(),
}


_MARKET_TO_PARQUET_DIR: dict[str, str] = {
    "TSE": "TWSE",
    "OTC": "TPEX",
}


def to_int_price(price: float) -> int:
    """Convert a parquet float price (e.g. 31.55) to int * 10000 (315500).

    Always uses ``round``; never ``int``. The float ``31.55 * 10000`` lands at
    ``315499.99…`` and ``int()`` truncates to ``315499``, off by one. This
    helper is the single conversion site so the rule is easy to audit.
    """
    return round(price * 10000)


def assert_replay_schema(table: pa.Table) -> None:
    """Validate that ``table`` carries every replay column with the right type.

    Raises ``ValueError`` listing missing columns and any column whose pyarrow
    type does not match the expected mapping.
    """
    schema = table.schema
    missing: list[str] = []
    mistyped: list[str] = []
    for column, expected in _REPLAY_SCHEMA.items():
        if column not in schema.names:
            missing.append(column)
            continue
        actual = schema.field(column).type
        if not actual.equals(expected):
            mistyped.append(f"{column}: expected {expected}, got {actual}")
    if missing or mistyped:
        parts: list[str] = []
        if missing:
            parts.append(f"missing columns: {missing}")
        if mistyped:
            parts.append(f"mistyped columns: {mistyped}")
        raise ValueError("parquet replay schema mismatch — " + "; ".join(parts))


def parquet_path(root: str | Path, market: str, date: str) -> Path:
    """Map ``("TSE", "20260326")`` to ``<root>/TWSE/20260326.parquet``.

    Mapping: ``TSE`` -> ``TWSE``, ``OTC`` -> ``TPEX``. Any other market raises
    ``ValueError``.
    """
    try:
        subdir = _MARKET_TO_PARQUET_DIR[market]
    except KeyError as exc:
        raise ValueError(
            f"unknown market {market!r}; expected one of {sorted(_MARKET_TO_PARQUET_DIR)}"
        ) from exc
    return Path(root) / subdir / f"{date}.parquet"
