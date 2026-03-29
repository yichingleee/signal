"""Decision funnel horizontal bar chart."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.reporting.charts._style import ACCENT, save_and_close
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


def plot_funnel(funnel: FunnelTracker, log_dir: str) -> None:
    """Generate chart_funnel.png — horizontal bar chart showing pipeline stages."""
    from tw_signal_engine.reporting.charts._style import new_figure

    stages = [
        ("Universe", funnel.universe_count),
        ("Valid Group", funnel.valid_group_symbols),
        ("Signal Triggered", funnel.signal_triggered),
        ("Passed Filters", funnel.signal_triggered - funnel.entry_filter_blocked),
        ("Executed", funnel.executed_trades),
    ]

    # Filter out zero stages
    stages = [(name, count) for name, count in stages if count > 0]
    if not stages:
        return

    fig, ax = new_figure(width=10, height=5)

    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]

    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, values, color=ACCENT, alpha=0.8)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Count")
    ax.set_title("Decision Funnel")

    # Add pass rate labels
    for i, (bar, val) in enumerate(zip(bars, values)):
        rate = val / values[0] * 100 if values[0] > 0 else 0
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,} ({rate:.1f}%)", va="center", fontsize=9)

    save_and_close(fig, str(Path(log_dir) / "chart_funnel.png"))
