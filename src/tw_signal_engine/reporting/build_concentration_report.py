"""Generate report_concentration.csv for PnL concentration analysis."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord


def _top_contributions(
    sorted_items: list[tuple[str, float]],
    total_pnl: float,
) -> list[tuple[str, float, float]]:
    """Return items sorted by abs PnL desc with cumulative % contribution."""
    by_abs = sorted(sorted_items, key=lambda x: abs(x[1]), reverse=True)
    result: list[tuple[str, float, float]] = []
    cum = 0.0
    for name, pnl in by_abs:
        cum += pnl
        pct = cum / total_pnl * 100.0 if total_pnl != 0 else 0.0
        result.append((name, pnl, pct))
    return result


def _percentile_contributions(
    pnls_sorted_desc: list[float],
    total_pnl: float,
) -> dict[str, float]:
    """Compute contribution of top 1%, 5%, 10% of trades."""
    n = len(pnls_sorted_desc)
    result: dict[str, float] = {}
    for label, pct in [("Top 1%", 0.01), ("Top 5%", 0.05), ("Top 10%", 0.10)]:
        k = max(1, int(n * pct))
        top_sum = sum(pnls_sorted_desc[:k])
        result[label] = top_sum / total_pnl * 100.0 if total_pnl != 0 else 0.0
    remainder = sum(pnls_sorted_desc[max(1, int(n * 0.10)):])
    result["Remainder"] = remainder / total_pnl * 100.0 if total_pnl != 0 else 0.0
    return result


def write_concentration_report(completed_trades: list[TradeRecord], log_dir: str) -> None:
    """Write report_concentration.csv."""
    if not completed_trades:
        return

    path = Path(log_dir) / "report_concentration.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    total_pnl = sum(t.pnl for t in completed_trades)

    # By symbol
    by_symbol: dict[str, float] = defaultdict(float)
    for t in completed_trades:
        by_symbol[t.symbol] += t.pnl

    # By date
    by_date: dict[str, float] = defaultdict(float)
    for t in completed_trades:
        by_date[t.trade_date or "unknown"] += t.pnl

    # By group
    by_group: dict[str, float] = defaultdict(float)
    for t in completed_trades:
        by_group[t.group_name or "none"] += t.pnl

    with open(path, "w", newline="") as f:
        w = csv.writer(f)

        # Section 1: Top symbols
        w.writerow(["Section", "Name", "PnL", "CumulativePnL%"])
        sym_items = _top_contributions(list(by_symbol.items()), total_pnl)
        for name, pnl, cum_pct in sym_items[:20]:  # Top 20
            w.writerow(["TopSymbols", name, f"{pnl:.0f}", f"{cum_pct:.1f}%"])

        # Section 2: Top dates
        w.writerow([])
        w.writerow(["Section", "Name", "PnL", "CumulativePnL%"])
        date_items = _top_contributions(list(by_date.items()), total_pnl)
        for name, pnl, cum_pct in date_items[:20]:
            w.writerow(["TopDates", name, f"{pnl:.0f}", f"{cum_pct:.1f}%"])

        # Section 3: Top groups
        w.writerow([])
        w.writerow(["Section", "Name", "PnL", "CumulativePnL%"])
        grp_items = _top_contributions(list(by_group.items()), total_pnl)
        for name, pnl, cum_pct in grp_items[:20]:
            w.writerow(["TopGroups", name, f"{pnl:.0f}", f"{cum_pct:.1f}%"])

        # Section 4: Contribution percentiles
        w.writerow([])
        w.writerow(["Section", "Percentile", "ContributionPnL%"])
        # Sort individual trade PnLs by absolute value descending
        sorted_pnls = sorted([t.pnl for t in completed_trades], key=abs, reverse=True)
        pct_contrib = _percentile_contributions(sorted_pnls, total_pnl)
        for label, pct in pct_contrib.items():
            w.writerow(["Percentiles", label, f"{pct:.1f}%"])

    print(f"[Report] {path}")
