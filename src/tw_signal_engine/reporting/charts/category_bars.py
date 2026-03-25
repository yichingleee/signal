"""Category bar charts — PnL by signal type, enter cause, leave cause."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import LOSS, WIN, save_and_close


def plot_category_bars(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_category_pnl.png — 3 grouped bar charts."""
    if not trades:
        return

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(18, 6), dpi=150)

    categories = [
        ("Signal Type", {k: v for k, v in _group_pnl(trades, "signal_type").items()}),
        ("Enter Cause", {k: v for k, v in _group_pnl(trades, "enter_cause").items()}),
        ("Leave Cause", {k: v for k, v in _group_pnl(trades, "final_leave_cause").items()}),
    ]

    for ax, (title, data) in zip(axes, categories):
        labels = list(data.keys())
        values = list(data.values())
        colors = [WIN if v > 0 else LOSS for v in values]
        bars = ax.bar(labels, values, color=colors, alpha=0.8)
        ax.set_title(title)
        ax.set_ylabel("Total PnL")
        ax.axhline(y=0, color="gray", linewidth=0.5)
        ax.tick_params(axis="x", rotation=45)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{val:.0f}", ha="center", va="bottom" if val > 0 else "top", fontsize=8)

    save_and_close(fig, str(Path(log_dir) / "chart_category_pnl.png"))


def _group_pnl(trades: list[TradeRecord], attr: str) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for t in trades:
        result[getattr(t, attr)] += t.pnl
    return dict(sorted(result.items(), key=lambda x: -abs(x[1])))
