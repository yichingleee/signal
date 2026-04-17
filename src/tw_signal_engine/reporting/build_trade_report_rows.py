"""Generate report_trades.csv from completed trade records."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.session_time import duration_sec, fmt_duration, fmt_time


def write_trade_report(
    completed_trades: list[TradeRecord],
    log_dir: str,
    market_open_chg_pct: float = 0.0,
) -> None:
    """Write report_trades.csv."""
    path = Path(log_dir) / "report_trades.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Symbol", "Side", "SignalType", "EnterCause", "EntryTime", "ExitTime", "LeaveCause",
            "PnL", "Return%", "HoldingDuration",
            "GroupName", "GroupRank", "MemberRank", "RawMemberRank", "M1Symbol",
            "EntryPrice", "EntryVWAP", "DayHigh", "PrevClose", "0050OpenChg%",
            "VolRatio", "MonthTradingVal",
            "IsPrevDayLU", "IsDisposition", "HadCircuitBreaker", "GroupLimitUpCount", "0050EntryChg%",
            # New columns
            "MAE%", "MFE%", "MAEPrice", "MFEPrice",
            "TimeToFirstTP", "TPSlicesFilled",
            "GrossPnL", "Commission", "Tax", "Slippage", "NetPnL",
            "TPPnL", "ResidualPnL",
            "TradeDate", "EntryHourBucket",
        ])
        for t in completed_trades:
            dur = duration_sec(t.entry_time_raw, t.exit_time_raw)
            w.writerow([
                t.symbol, t.side, t.signal_type, t.enter_cause,
                fmt_time(t.entry_time_raw), fmt_time(t.exit_time_raw),
                t.final_leave_cause,
                f"{t.pnl:.0f}", f"{t.return_pct:.2f}%", fmt_duration(dur),
                t.group_name, t.group_rank, t.member_rank, t.raw_member_rank,
                t.m1_symbol if t.member_rank > 1 else "",
                f"{t.entry_price:.2f}", f"{t.entry_vwap:.2f}",
                f"{t.day_high_at_entry:.2f}", f"{t.prev_close:.2f}",
                f"{market_open_chg_pct:.3f}",
                f"{t.vol_ratio:.2f}", str(t.month_trading_val),
                1 if t.is_prev_day_lu else 0,
                1 if t.is_disposition else 0,
                1 if t.had_circuit_breaker else 0,
                t.group_limit_up_count,
                f"{t.market_entry_chg_pct:.3f}",
                # New columns
                f"{t.mae_pct:.3f}", f"{t.mfe_pct:.3f}",
                f"{t.mae_price:.2f}", f"{t.mfe_price:.2f}",
                str(t.time_to_first_tp_sec), str(t.tp_slices_filled),
                f"{t.gross_pnl:.0f}", f"{t.commission:.0f}", f"{t.tax:.0f}", f"{t.slippage:.0f}", f"{t.net_pnl:.0f}",
                f"{t.tp_pnl:.0f}", f"{t.residual_pnl:.0f}",
                t.trade_date, t.entry_hour_bucket,
            ])
    print(f"[Report] {path}")
