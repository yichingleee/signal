"""Lightweight parser for history loading.

Extracts only (symbol, match_time_us, price, qty) from Trade lines,
avoiding full MarketTick + QuotePair allocation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(slots=True)
class HistoryTrade:
    """Minimal trade record for history-window construction."""

    symbol: str
    match_time_us: int
    price: int
    qty: int


def _convert_raw_time_to_us(raw_time: int) -> int:
    """Convert HMMSS000000 format to microseconds since midnight."""
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return (hours * 3600 + minutes * 60 + seconds) * 1_000_000 + micros


def parse_history_trade(line: str) -> HistoryTrade | None:
    """Parse a Trade line into a lightweight HistoryTrade.

    Trade format: Trade,SYMBOL,MATCHTIME,STATUSCODE,PRICE,QTY,...
    Returns None for non-trade lines or status_code != 0.
    """
    if len(line) < 2 or line[0] != "T" or line[1] != "r":
        return None

    parts = line.split(",", 6)
    if len(parts) < 6:
        return None

    symbol = parts[1].strip()
    if not symbol:
        return None

    try:
        raw_time = int(parts[2])
        status_code = int(parts[3])
        price = int(parts[4])
        qty = int(parts[5])
    except (ValueError, IndexError):
        return None

    if status_code != 0:
        return None

    return HistoryTrade(
        symbol=symbol,
        match_time_us=_convert_raw_time_to_us(raw_time),
        price=price,
        qty=qty,
    )


def iter_history_trades(filename: str) -> Iterator[HistoryTrade]:
    """Iterate trade records from a replay file for history loading."""
    try:
        with open(filename, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or len(line) < 2 or line[0] != "T" or line[1] != "r":
                    continue
                trade = parse_history_trade(line)
                if trade is not None:
                    yield trade
    except FileNotFoundError:
        pass
