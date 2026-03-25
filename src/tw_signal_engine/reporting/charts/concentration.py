"""Concentration / Lorenz-style chart."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import ACCENT, NEUTRAL, save_and_close


def plot_concentration(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_concentration.png — sorted trades vs cumulative PnL."""
    if len(trades) < 2:
        return

    import numpy as np

    from tw_signal_engine.reporting.charts._style import new_figure

    fig, ax = new_figure()

    pnls = sorted([t.pnl for t in trades], reverse=True)
    total = sum(pnls)
    if total == 0:
        return

    cum = np.cumsum(pnls)
    cum_pct = cum / total * 100.0
    x = np.arange(1, len(pnls) + 1) / len(pnls) * 100.0

    ax.plot(x, cum_pct, color=ACCENT, linewidth=2)
    # Uniform reference line
    ax.plot([0, 100], [0, 100], color=NEUTRAL, linestyle="--", linewidth=1)

    # Annotate top 5% and 10%
    n = len(pnls)
    for pct_label, pct in [("5%", 0.05), ("10%", 0.10)]:
        k = max(1, int(n * pct))
        top_sum = sum(pnls[:k])
        contrib = top_sum / total * 100
        ax.axvline(pct * 100, color=NEUTRAL, linestyle=":", alpha=0.5)
        ax.annotate(f"Top {pct_label}: {contrib:.0f}%",
                    xy=(pct * 100, contrib),
                    xytext=(pct * 100 + 5, contrib - 10),
                    fontsize=8, arrowprops={"arrowstyle": "->", "color": "gray"})

    ax.set_xlabel("% of Trades (sorted by PnL desc)")
    ax.set_ylabel("Cumulative PnL %")
    ax.set_title("PnL Concentration")
    ax.set_xlim(0, 100)

    save_and_close(fig, str(Path(log_dir) / "chart_concentration.png"))
