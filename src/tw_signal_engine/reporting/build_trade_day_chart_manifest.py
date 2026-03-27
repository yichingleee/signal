"""Manifest writer for generated per-symbol trade-day charts."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.reporting.charts.trade_day_models import TradeMarker


def write_trade_day_chart_manifest(
    log_dir: str,
    generated_symbols: list[str],
    markers_by_symbol: dict[str, list[TradeMarker]],
) -> None:
    """Write report_trade_day_charts.csv for discoverability."""
    if not generated_symbols:
        return

    path = Path(log_dir) / "report_trade_day_charts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "ChartFile", "TradeCount", "SignalCount", "EntryCount", "ExitCount"])

        for symbol in sorted(set(generated_symbols)):
            markers = markers_by_symbol.get(symbol, [])
            signal_count = sum(1 for marker in markers if marker.kind == "signal")
            entry_count = sum(1 for marker in markers if marker.kind == "entry")
            exit_count = sum(1 for marker in markers if marker.kind == "exit")
            trade_count = min(signal_count, entry_count, exit_count)

            writer.writerow(
                [
                    symbol,
                    f"chart_trade_day_{symbol}.png",
                    trade_count,
                    signal_count,
                    entry_count,
                    exit_count,
                ]
            )

    print(f"[Report] {path}")
