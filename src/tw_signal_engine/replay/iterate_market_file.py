"""Iterate one replay file and yield MarketTick events."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tw_signal_engine.market_data.parse_format6_replay_rows import parse_trade_line
from tw_signal_engine.records.market_event_records import MarketTick


def _extract_symbol_fast(line: str) -> str:
    """Extract symbol from a Trade line using index-based scanning.

    Format: Trade,SYMBOL,... — find the first comma after 'Trade,' and the second comma.
    """
    # "Trade," is 6 chars, symbol starts at index 6
    start = 6
    end = line.find(",", start)
    if end == -1:
        return ""
    sym = line[start:end]
    # Strip whitespace (rare but possible)
    if sym and (sym[0] == " " or sym[-1] == " "):
        sym = sym.strip()
    return sym


def iterate_market_file(
    market: str,
    date: str,
    data_dir: str = "./data/",
    tick_filter: set[str] | None = None,
) -> Iterator[MarketTick]:
    """Read a replay file line by line and yield valid MarketTick events.

    Handles the Trade/Depth line pairing logic from the C++ readFile.
    """
    filename = Path(data_dir) / f"{market}Quote.{date}"
    if not filename.exists():
        return

    _is_trade = _is_trade_line

    with open(filename, encoding="utf-8", errors="replace") as f:
        stored_line: str | None = None

        while True:
            if stored_line is not None:
                trade_line = stored_line
                stored_line = None
            else:
                trade_line = f.readline()
                if not trade_line:
                    break
                trade_line = trade_line.rstrip("\n")

            if not trade_line or not _is_trade(trade_line):
                continue

            # Quick symbol filter before full parse (index-based, no split)
            if tick_filter:
                sym = _extract_symbol_fast(trade_line)
                if sym not in tick_filter:
                    # Still need to read potential depth line
                    depth_line = f.readline()
                    if depth_line:
                        depth_line = depth_line.rstrip("\n")
                        if _is_trade(depth_line):
                            stored_line = depth_line
                    continue

            # Try to read depth line
            depth_line = f.readline()
            if depth_line:
                depth_line = depth_line.rstrip("\n")
            else:
                depth_line = ""

            # If "depth" line is actually next trade, store it
            if _is_trade(depth_line):
                stored_line = depth_line
                depth_line = ""

            # Verify trade/depth match (check same symbol+time region)
            if depth_line and len(trade_line) > 25 and len(depth_line) > 25:
                if trade_line[5:25] != depth_line[5:25]:
                    depth_line = ""

            tick = parse_trade_line(trade_line, depth_line, market)
            if tick is not None and tick.status_code == 0:
                yield tick


def _is_trade_line(line: str) -> bool:
    """Check if a line is a Trade line (starts with 'Tr')."""
    return len(line) >= 2 and line[0] == "T" and line[1] == "r"
