"""Regime heatmap chart — entry hour x market state."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import save_and_close


def _market_bucket(chg: float) -> str:
    if chg < -1.0:
        return "<-1%"
    if chg < 0.0:
        return "-1%~0%"
    if chg < 1.0:
        return "0%~1%"
    return ">1%"


def plot_regime_heatmap(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_regime_heatmap.png — hour x market state heatmap."""
    if len(trades) < 2:
        return

    import numpy as np

    from tw_signal_engine.reporting.charts._style import new_figure

    hours = ["09:00-09:15", "09:15-09:30", "09:30-10:00", "10:00+"]
    markets = ["<-1%", "-1%~0%", "0%~1%", ">1%"]

    grid: dict[tuple[str, str], list[float]] = defaultdict(list)
    count_grid: dict[tuple[str, str], int] = defaultdict(int)

    for t in trades:
        h = t.entry_hour_bucket or "unknown"
        if h not in hours:
            h = "10:00+"
        m = _market_bucket(t.market_entry_chg_pct)
        grid[(m, h)].append(t.return_pct)
        count_grid[(m, h)] += 1

    data = np.zeros((len(markets), len(hours)))
    for i, m in enumerate(markets):
        for j, h in enumerate(hours):
            vals = grid.get((m, h), [])
            data[i, j] = sum(vals) / len(vals) if vals else 0.0

    fig, ax = new_figure(width=10, height=6)
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(hours)))
    ax.set_xticklabels(hours)
    ax.set_yticks(range(len(markets)))
    ax.set_yticklabels(markets)
    ax.set_xlabel("Entry Hour")
    ax.set_ylabel("Market State (0050 Chg%)")
    ax.set_title("Avg Return% by Regime")
    fig.colorbar(im, ax=ax, label="Avg Return%")

    # Text annotations
    for i, m in enumerate(markets):
        for j, h in enumerate(hours):
            n = count_grid.get((m, h), 0)
            val = data[i, j]
            ax.text(j, i, f"{val:.2f}%\n(n={n})", ha="center", va="center", fontsize=7)

    save_and_close(fig, str(Path(log_dir) / "chart_regime_heatmap.png"))
