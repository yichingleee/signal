"""Generate report_summary.csv."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.session_time import duration_sec, fmt_duration


def write_summary_report(completed_trades: list[TradeRecord], log_dir: str) -> None:
    """Write report_summary.csv and print terminal summary."""
    if not completed_trades:
        print("[Report] No completed trades.")
        return

    total = len(completed_trades)
    total_pnl = 0.0
    win_count = 0
    gross_win = 0.0
    gross_loss = 0.0
    max_win = float("-inf")
    max_loss = float("inf")
    max_consec_win = 0
    max_consec_loss = 0
    cur_consec = 0
    last_win = False
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    total_hold_sec = 0.0
    avg_return = 0.0

    # Cost aggregations
    total_gross_pnl = 0.0
    total_commission = 0.0
    total_tax = 0.0
    total_net_pnl = 0.0
    net_gross_win = 0.0
    net_gross_loss = 0.0
    avg_net_return = 0.0

    for i, t in enumerate(completed_trades):
        total_pnl += t.pnl
        cum_pnl += t.pnl
        if cum_pnl > peak:
            peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd
        if t.pnl > max_win:
            max_win = t.pnl
        if t.pnl < max_loss:
            max_loss = t.pnl

        is_win = t.pnl > 0
        if is_win:
            win_count += 1
            gross_win += t.pnl
        else:
            gross_loss += t.pnl

        if i == 0:
            cur_consec = 1
            last_win = is_win
        elif is_win == last_win:
            cur_consec += 1
        else:
            cur_consec = 1
            last_win = is_win

        if is_win and cur_consec > max_consec_win:
            max_consec_win = cur_consec
        if not is_win and cur_consec > max_consec_loss:
            max_consec_loss = cur_consec

        avg_return += t.return_pct
        total_hold_sec += duration_sec(t.entry_time_raw, t.exit_time_raw)

        # Cost aggregations
        total_gross_pnl += t.gross_pnl
        total_commission += t.commission
        total_tax += t.tax
        total_net_pnl += t.net_pnl
        if t.net_pnl > 0:
            net_gross_win += t.net_pnl
        else:
            net_gross_loss += t.net_pnl
        # Net return: approximate from net_pnl / position_cash
        if t.return_pct != 0 and t.pnl != 0:
            avg_net_return += t.net_pnl / t.pnl * t.return_pct if t.pnl != 0 else 0.0

    loss_count = total - win_count
    avg_win = gross_win / win_count if win_count > 0 else 0
    avg_loss = gross_loss / loss_count if loss_count > 0 else 0
    profit_factor = gross_win / (-gross_loss) if gross_loss != 0 else 0
    avg_return /= total
    avg_net_return /= total

    net_profit_factor = net_gross_win / (-net_gross_loss) if net_gross_loss != 0 else 0

    path = Path(log_dir) / "report_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Metric", "Value"])
        w.writerow(["Total Trades", str(total)])
        w.writerow(["Total PnL", f"{total_pnl:.0f}"])
        w.writerow(["Win Rate", f"{win_count * 100.0 / total:.1f}%"])
        w.writerow(["Win Count", str(win_count)])
        w.writerow(["Loss Count", str(loss_count)])
        w.writerow(["Avg Win", f"{avg_win:.0f}"])
        w.writerow(["Avg Loss", f"{avg_loss:.0f}"])
        w.writerow(["Profit Factor", f"{profit_factor:.2f}"])
        w.writerow(["Max Single Win", f"{max_win:.0f}"])
        w.writerow(["Max Single Loss", f"{max_loss:.0f}"])
        w.writerow(["Max Consecutive Wins", str(max_consec_win)])
        w.writerow(["Max Consecutive Losses", str(max_consec_loss)])
        w.writerow(["Max Drawdown", f"{max_dd:.0f}"])
        w.writerow(["Avg Holding Duration", fmt_duration(int(total_hold_sec / total))])
        w.writerow(["Avg Return%", f"{avg_return:.2f}%"])
        # Cost model rows (always shown)
        w.writerow(["Total Gross PnL", f"{total_gross_pnl:.0f}"])
        w.writerow(["Total Commission", f"{total_commission:.0f}"])
        w.writerow(["Total Tax", f"{total_tax:.0f}"])
        w.writerow(["Total Net PnL", f"{total_net_pnl:.0f}"])
        w.writerow(["Net Profit Factor", f"{net_profit_factor:.2f}"])
        w.writerow(["Avg Net Return%", f"{avg_net_return:.2f}%"])
    print(f"[Report] {path}")

    # Terminal summary
    print(f"\n{'=' * 10} Backtest Report {'=' * 10}")
    print(f"  Total Trades:    {total}")
    print(f"  Total PnL:       {total_pnl:.0f}")
    print(f"  Win Rate:        {win_count * 100.0 / total:.1f}%")
    print(f"  Profit Factor:   {profit_factor:.2f}")
    print(f"  Max Drawdown:    {max_dd:.0f}")
    print(f"  Avg Return:      {avg_return:.2f}%")
    if total_commission > 0 or total_tax > 0:
        print(f"  Net PnL:         {total_net_pnl:.0f}")
        print(f"  Net PF:          {net_profit_factor:.2f}")
    print("=" * 37)
