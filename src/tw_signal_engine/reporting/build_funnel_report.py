"""Generate report_funnel.csv from FunnelTracker data."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


def write_funnel_report(funnel: FunnelTracker, log_dir: str) -> None:
    """Write report_funnel.csv with pipeline stage counts and block reasons."""
    path = Path(log_dir) / "report_funnel.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    stages = [
        ("Universe", funnel.universe_count),
        ("Valid Group Symbols", funnel.valid_group_symbols),
        ("Group Qualified Ticks", funnel.group_qualified_ticks),
        ("Signal Triggered", funnel.signal_triggered),
        ("Entry Filter Blocked", funnel.entry_filter_blocked),
        ("Executed Trades", funnel.executed_trades),
    ]

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        # Section 1: Pipeline stages
        w.writerow(["Section", "Stage", "Count", "PassRate", "CumulativePassRate"])
        base = funnel.universe_count if funnel.universe_count > 0 else 1
        prev = base
        for name, count in stages:
            pass_rate = count / prev * 100.0 if prev > 0 else 0.0
            cum_rate = count / base * 100.0 if base > 0 else 0.0
            w.writerow(["Pipeline", name, count, f"{pass_rate:.1f}%", f"{cum_rate:.1f}%"])
            prev = count if count > 0 else prev

        # Section 2: Block reason breakdown
        w.writerow([])
        w.writerow(["Section", "Reason", "Count", "Percentage"])
        total_blocked = funnel.entry_filter_blocked
        for reason, count in sorted(funnel.entry_filter_reasons.items(), key=lambda x: -x[1]):
            pct = count / total_blocked * 100.0 if total_blocked > 0 else 0.0
            w.writerow(["BlockReasons", reason, count, f"{pct:.1f}%"])

    print(f"[Report] {path}")
