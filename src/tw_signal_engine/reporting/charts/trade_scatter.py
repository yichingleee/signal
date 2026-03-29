"""Trade scatter chart — return% vs holding duration."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.session_time import duration_sec
from tw_signal_engine.reporting.charts._style import ACCENT, LOSS, NEUTRAL, WIN, save_and_close

CAUSE_COLORS: dict[str, str] = {
    "takeProfit": WIN,
    "stopLoss": LOSS,
    "bailout": "#f39c12",
    "timeExit": ACCENT,
    "timeLimitUp": NEUTRAL,
}


def plot_trade_scatter(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_trade_scatter.png — return% vs holding duration."""
    if len(trades) < 2:
        return

    from tw_signal_engine.reporting.charts._style import new_figure

    fig, ax = new_figure()

    by_cause: dict[str, tuple[list[float], list[float]]] = {}
    for t in trades:
        dur_min = duration_sec(t.entry_time_raw, t.exit_time_raw) / 60.0
        cause = t.final_leave_cause
        if cause not in by_cause:
            by_cause[cause] = ([], [])
        by_cause[cause][0].append(dur_min)
        by_cause[cause][1].append(t.return_pct)

    for cause, (durations, returns) in by_cause.items():
        color = CAUSE_COLORS.get(cause, NEUTRAL)
        ax.scatter(durations, returns, c=color, alpha=0.6, s=20, label=cause, edgecolors="none")

    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Holding Duration (minutes)")
    ax.set_ylabel("Return%")
    ax.set_title("Return% vs Holding Duration")
    ax.legend(loc="upper right", fontsize=8)

    save_and_close(fig, str(Path(log_dir) / "chart_trade_scatter.png"))
