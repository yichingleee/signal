"""Generate report_rolling.csv — rolling 20-day window metrics."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.session_time import duration_sec


def write_rolling_metrics_report(
    all_trades: list[TradeRecord],
    log_dir: str,
    window: int = 20,
) -> None:
    """Write report_rolling.csv with rolling window metrics."""
    if not all_trades:
        return

    path = Path(log_dir) / "report_rolling.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Group trades by date
    by_date: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in all_trades:
        by_date[t.trade_date or "unknown"].append(t)

    sorted_dates = sorted(by_date.keys())
    if len(sorted_dates) < 1:
        return

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["EndDate", "WindowDays", "HitRate", "Expectancy", "ProfitFactor", "AvgHoldDuration"])

        for i in range(len(sorted_dates)):
            start_idx = max(0, i - window + 1)
            window_dates = sorted_dates[start_idx:i + 1]
            window_trades: list[TradeRecord] = []
            for d in window_dates:
                window_trades.extend(by_date[d])

            if not window_trades:
                continue

            n = len(window_trades)
            wins = sum(1 for t in window_trades if t.pnl > 0)
            hit_rate = wins / n * 100.0
            avg_pnl = sum(t.pnl for t in window_trades) / n

            gross_win = sum(t.pnl for t in window_trades if t.pnl > 0)
            gross_loss = sum(t.pnl for t in window_trades if t.pnl <= 0)
            pf = gross_win / (-gross_loss) if gross_loss != 0 else 0.0

            total_dur = sum(duration_sec(t.entry_time_raw, t.exit_time_raw) for t in window_trades)
            avg_dur = total_dur / n

            w.writerow([
                sorted_dates[i],
                len(window_dates),
                f"{hit_rate:.1f}%",
                f"{avg_pnl:.0f}",
                f"{pf:.2f}",
                f"{avg_dur:.0f}s",
            ])

    print(f"[Report] {path}")
