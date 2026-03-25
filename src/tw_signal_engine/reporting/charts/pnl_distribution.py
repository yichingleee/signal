"""PnL distribution histogram chart."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import LOSS, NEUTRAL, WIN, save_and_close


def plot_pnl_distribution(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_pnl_distribution.png — histogram of trade PnLs."""
    if len(trades) < 2:
        return

    import numpy as np

    from tw_signal_engine.reporting.charts._style import new_figure

    fig, ax = new_figure()

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    n_bins = min(50, max(10, len(pnls) // 5))

    if wins:
        ax.hist(wins, bins=n_bins, color=WIN, alpha=0.7, label=f"Wins ({len(wins)})")
    if losses:
        ax.hist(losses, bins=n_bins, color=LOSS, alpha=0.7, label=f"Losses ({len(losses)})")

    mean_pnl = sum(pnls) / len(pnls)
    sorted_pnls = sorted(pnls)
    n = len(pnls)
    median_pnl = sorted_pnls[n // 2] if n % 2 == 1 else (sorted_pnls[n // 2 - 1] + sorted_pnls[n // 2]) / 2

    ax.axvline(mean_pnl, color=NEUTRAL, linestyle="--", linewidth=1.5, label=f"Mean: {mean_pnl:.0f}")
    ax.axvline(median_pnl, color="black", linestyle=":", linewidth=1.5, label=f"Median: {median_pnl:.0f}")

    # Annotate skew and kurtosis
    arr = np.array(pnls)
    std = float(np.std(arr))
    if std > 0 and n >= 3:
        skew = float(np.mean(((arr - mean_pnl) / std) ** 3))
        kurt = float(np.mean(((arr - mean_pnl) / std) ** 4)) - 3.0
        ax.text(0.98, 0.95, f"Skew: {skew:.2f}\nKurt: {kurt:.2f}",
                transform=ax.transAxes, ha="right", va="top", fontsize=9,
                bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8})

    ax.set_xlabel("PnL")
    ax.set_ylabel("Count")
    ax.set_title("PnL Distribution")
    ax.legend(loc="upper left")

    save_and_close(fig, str(Path(log_dir) / "chart_pnl_distribution.png"))
