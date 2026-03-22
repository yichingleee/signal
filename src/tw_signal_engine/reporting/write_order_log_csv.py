"""Raw trade log CSV writer."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

LOG_HEADER = [
    "Action", "Symbol", "Time", "Price", "Cash", "SymbolCash",
    "SignalType", "EnterCause", "LeaveCause", "RemainingQty", "GroupInfo",
]


class OrderLogWriter:
    """Writes order_log CSV files (main + per-symbol).

    Writes are buffered and flushed on close (or explicit flush).
    """

    def __init__(self, log_dir: str, date: str) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.date = date

        # Main log (buffered)
        self._main_path = self.log_dir / f"order_log_{date}.csv"
        self._main_f: io.TextIOWrapper = open(self._main_path, "w", newline="", buffering=8192)
        self._main_w: Any = csv.writer(self._main_f)
        self._main_w.writerow(LOG_HEADER)

        self._symbol_files: dict[str, tuple[io.TextIOWrapper, Any]] = {}

    def _get_symbol_writer(self, symbol: str) -> Any:
        if symbol not in self._symbol_files:
            path = self.log_dir / f"order_log_{self.date}_{symbol}.csv"
            f: io.TextIOWrapper = open(path, "w", newline="", buffering=8192)
            w: Any = csv.writer(f)
            w.writerow(LOG_HEADER)
            self._symbol_files[symbol] = (f, w)
        return self._symbol_files[symbol][1]

    def write_entry(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        signal_type: str,
        cause: str,
        remaining_qty: float,
        group_info: str,
    ) -> None:
        row = [
            "enter", symbol, str(time_str), str(price),
            f"{cash:.0f}", f"{symbol_cash:.0f}",
            signal_type, cause, "-", f"{remaining_qty:.0f}", group_info,
        ]
        self._main_w.writerow(row)
        sw = self._get_symbol_writer(symbol)
        sw.writerow(row)

    def write_leave(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        cause: str,
        remaining_qty: float,
    ) -> None:
        row = [
            "leave", symbol, str(time_str), str(price),
            f"{cash:.0f}", f"{symbol_cash:.0f}",
            "-", "-", cause, f"{remaining_qty:.0f}", "",
        ]
        self._main_w.writerow(row)
        sw = self._get_symbol_writer(symbol)
        sw.writerow(row)

    def close(self) -> None:
        self._main_f.close()
        for f, _ in self._symbol_files.values():
            f.close()
        self._symbol_files.clear()
