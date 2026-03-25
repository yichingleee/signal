"""Generate report_trade_paths.csv with per-trade path analysis."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.session_time import fmt_time


def write_trade_path_report(completed_trades: list[TradeRecord], log_dir: str) -> None:
    """Write report_trade_paths.csv — one row per trade with MAE/MFE and TP details."""
    if not completed_trades:
        return

    path = Path(log_dir) / "report_trade_paths.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Symbol", "EntryTime", "MAE%", "MFE%",
            "TimeToTP(sec)", "TPSlices", "TPPnL", "ResidualPnL",
            "PeakUnrealizedPnL", "TroughUnrealizedPnL", "LeaveCause",
        ])
        for t in completed_trades:
            # Peak/trough unrealized are approximations based on MFE/MAE
            # MFE% is how high price went relative to entry
            # MAE% is how low price went relative to entry
            peak_unrealized = t.mfe_pct  # proxy: max favorable excursion %
            trough_unrealized = t.mae_pct  # proxy: max adverse excursion %
            w.writerow([
                t.symbol,
                fmt_time(t.entry_time_raw),
                f"{t.mae_pct:.3f}",
                f"{t.mfe_pct:.3f}",
                str(t.time_to_first_tp_sec),
                str(t.tp_slices_filled),
                f"{t.tp_pnl:.0f}",
                f"{t.residual_pnl:.0f}",
                f"{peak_unrealized:.3f}",
                f"{trough_unrealized:.3f}",
                t.final_leave_cause,
            ])
    print(f"[Report] {path}")
