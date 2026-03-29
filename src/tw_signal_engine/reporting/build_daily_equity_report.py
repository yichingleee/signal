"""Generate report_daily.csv — daily equity curve and risk metrics across batch."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord


def _max_concurrent_and_capital(trades: list[TradeRecord]) -> tuple[int, float]:
    """Compute max concurrent positions and peak capital utilized for a day."""
    events: list[tuple[int, int]] = []  # (time, +1 or -1)
    for t in trades:
        events.append((t.entry_time_raw, 1))
        events.append((t.exit_time_raw, -1))
    events.sort()

    max_concurrent = 0
    current = 0
    for _, delta in events:
        current += delta
        if current > max_concurrent:
            max_concurrent = current

    # Approximate capital: each position uses one unit of position_cash
    # Derive position_cash from the first trade with nonzero return
    position_cash = 0.0
    for t in trades:
        if t.return_pct != 0:
            position_cash = t.pnl / t.return_pct * 100
            break

    capital_utilized = max_concurrent * position_cash
    return max_concurrent, capital_utilized


def write_daily_equity_report(
    all_trades: list[TradeRecord],
    log_dir: str,
) -> None:
    """Write report_daily.csv with per-date equity, drawdown, and daily stats."""
    if not all_trades:
        return

    path = Path(log_dir) / "report_daily.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Group trades by date
    by_date: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in all_trades:
        by_date[t.trade_date or "unknown"].append(t)

    cum_pnl = 0.0
    peak = 0.0

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Date", "Trades", "GrossPnL", "NetPnL", "CumPnL",
            "Drawdown", "DrawdownPct", "WinRate", "AvgReturn%",
            "ConcurrentPositions", "CapitalUtilized",
        ])

        for date in sorted(by_date.keys()):
            trades = by_date[date]
            n = len(trades)
            gross = sum(t.gross_pnl for t in trades)
            net = sum(t.net_pnl for t in trades)
            day_pnl = sum(t.pnl for t in trades)
            cum_pnl += day_pnl
            if cum_pnl > peak:
                peak = cum_pnl
            dd = peak - cum_pnl
            dd_pct = dd / peak * 100.0 if peak > 0 else 0.0
            wins = sum(1 for t in trades if t.pnl > 0)
            win_rate = wins / n * 100.0 if n > 0 else 0.0
            avg_ret = sum(t.return_pct for t in trades) / n if n > 0 else 0.0
            max_conc, capital = _max_concurrent_and_capital(trades)

            w.writerow([
                date, n,
                f"{gross:.0f}", f"{net:.0f}", f"{cum_pnl:.0f}",
                f"{dd:.0f}", f"{dd_pct:.1f}%",
                f"{win_rate:.1f}%", f"{avg_ret:.2f}%",
                str(max_conc), f"{capital:.0f}",
            ])

    print(f"[Report] {path}")
