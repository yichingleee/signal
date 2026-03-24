"""Rolling metrics chart — batch only."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import ACCENT, LOSS, save_and_close


def plot_rolling_metrics(trades: list[TradeRecord], log_dir: str, window: int = 20) -> None:
    """Generate chart_rolling_metrics.png — rolling win rate + expectancy."""
    if len(trades) < 2:
        return

    import matplotlib.pyplot as plt

    # Group by date
    by_date: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        by_date[t.trade_date or "unknown"].append(t)

    sorted_dates = sorted(by_date.keys())
    if len(sorted_dates) < 2:
        return

    dates_labels: list[str] = []
    win_rates: list[float] = []
    expectancies: list[float] = []

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
        win_rates.append(wins / n * 100.0)
        expectancies.append(sum(t.pnl for t in window_trades) / n)
        dates_labels.append(sorted_dates[i])

    if not dates_labels:
        return

    fig, ax1 = plt.subplots(figsize=(12, 6), dpi=150)
    ax2 = ax1.twinx()

    x = range(len(dates_labels))
    ax1.plot(x, win_rates, color=ACCENT, linewidth=1.5, label="Win Rate %")
    ax2.plot(x, expectancies, color=LOSS, linewidth=1.5, label="Expectancy")

    ax1.set_ylabel("Win Rate %", color=ACCENT)
    ax2.set_ylabel("Expectancy (PnL/trade)", color=LOSS)
    ax1.set_xlabel("Date")
    ax1.set_title(f"Rolling {window}-Day Metrics")

    # Show only some tick labels to avoid clutter
    step = max(1, len(dates_labels) // 15)
    ax1.set_xticks([i for i in x if i % step == 0])
    ax1.set_xticklabels([dates_labels[i] for i in x if i % step == 0], rotation=45, fontsize=8)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    ax1.spines["top"].set_visible(False)

    save_and_close(fig, str(Path(log_dir) / "chart_rolling_metrics.png"))
