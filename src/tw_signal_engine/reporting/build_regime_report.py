"""Generate report_regime.csv — performance by market state and entry hour."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord


def _market_state_bucket(chg_pct: float) -> str:
    """Classify 0050 open change % into market state bucket."""
    if chg_pct < -1.0:
        return "<-1%"
    if chg_pct < 0.0:
        return "-1% to 0%"
    if chg_pct < 1.0:
        return "0% to 1%"
    return ">1%"


def _group_rank_bucket(rank: int) -> str:
    """Classify group rank into bucket."""
    if rank <= 0:
        return "none"
    if rank <= 5:
        return "1-5"
    if rank <= 10:
        return "6-10"
    return "11-20"


def _compute_bucket_stats(trades: list[TradeRecord]) -> dict[str, str]:
    """Compute per-bucket stats."""
    n = len(trades)
    if n == 0:
        return {"Count": "0", "WinRate": "0.0%", "TotalPnL": "0", "AvgReturn%": "0.00%", "ProfitFactor": "0.00"}
    wins = sum(1 for t in trades if t.pnl > 0)
    total_pnl = sum(t.pnl for t in trades)
    avg_ret = sum(t.return_pct for t in trades) / n
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = sum(t.pnl for t in trades if t.pnl <= 0)
    pf = gross_win / (-gross_loss) if gross_loss != 0 else 0.0
    return {
        "Count": str(n),
        "WinRate": f"{wins / n * 100:.1f}%",
        "TotalPnL": f"{total_pnl:.0f}",
        "AvgReturn%": f"{avg_ret:.2f}%",
        "ProfitFactor": f"{pf:.2f}",
    }


def write_regime_report(
    all_trades: list[TradeRecord],
    log_dir: str,
) -> None:
    """Write report_regime.csv with performance by market state, entry hour, and group rank."""
    if not all_trades:
        return

    path = Path(log_dir) / "report_regime.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Dimension 1: Market state (0050 open chg%)
    by_market: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in all_trades:
        bucket = _market_state_bucket(t.market_entry_chg_pct)
        by_market[bucket].append(t)

    # Dimension 2: Entry hour
    by_hour: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in all_trades:
        by_hour[t.entry_hour_bucket or "unknown"].append(t)

    # Dimension 3: Group rank
    by_rank: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in all_trades:
        bucket = _group_rank_bucket(t.group_rank)
        by_rank[bucket].append(t)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Dimension", "Bucket", "Count", "WinRate", "TotalPnL", "AvgReturn%", "ProfitFactor"])

        market_order = ["<-1%", "-1% to 0%", "0% to 1%", ">1%"]
        for bucket in market_order:
            stats = _compute_bucket_stats(by_market.get(bucket, []))
            w.writerow(["MarketState", bucket, stats["Count"], stats["WinRate"],
                        stats["TotalPnL"], stats["AvgReturn%"], stats["ProfitFactor"]])

        hour_order = ["09:00-09:15", "09:15-09:30", "09:30-10:00", "10:00+"]
        for bucket in hour_order:
            stats = _compute_bucket_stats(by_hour.get(bucket, []))
            w.writerow(["EntryHour", bucket, stats["Count"], stats["WinRate"],
                        stats["TotalPnL"], stats["AvgReturn%"], stats["ProfitFactor"]])

        rank_order = ["1-5", "6-10", "11-20", "none"]
        for bucket in rank_order:
            stats = _compute_bucket_stats(by_rank.get(bucket, []))
            w.writerow(["GroupRank", bucket, stats["Count"], stats["WinRate"],
                        stats["TotalPnL"], stats["AvgReturn%"], stats["ProfitFactor"]])

    print(f"[Report] {path}")
