"""MAE vs MFE scatter chart."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import ACCENT, LOSS, NEUTRAL, WIN, save_and_close

# Color map for leave causes
CAUSE_COLORS: dict[str, str] = {
    "takeProfit": WIN,
    "stopLoss": LOSS,
    "bailout": "#f39c12",
    "timeExit": ACCENT,
    "timeLimitUp": NEUTRAL,
}


def plot_mae_mfe_scatter(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_mae_mfe.png — MAE% vs MFE% scatter by leave cause."""
    if len(trades) < 2:
        return

    from tw_signal_engine.reporting.charts._style import new_figure

    fig, ax = new_figure()

    # Group by leave cause
    by_cause: dict[str, tuple[list[float], list[float]]] = {}
    for t in trades:
        cause = t.final_leave_cause
        if cause not in by_cause:
            by_cause[cause] = ([], [])
        by_cause[cause][0].append(t.mae_pct)
        by_cause[cause][1].append(t.mfe_pct)

    for cause, (mae, mfe) in by_cause.items():
        color = CAUSE_COLORS.get(cause, NEUTRAL)
        ax.scatter(mae, mfe, c=color, alpha=0.6, s=20, label=cause, edgecolors="none")

    # Diagonal breakeven line
    all_vals = [t.mae_pct for t in trades] + [t.mfe_pct for t in trades]
    if all_vals:
        lim = max(abs(min(all_vals)), abs(max(all_vals))) * 1.1
        ax.plot([-lim, lim], [-lim, lim], color="gray", linewidth=0.5, linestyle="--", alpha=0.5)

    ax.set_xlabel("MAE%")
    ax.set_ylabel("MFE%")
    ax.set_title("MAE vs MFE by Leave Cause")
    ax.legend(loc="upper left", fontsize=8)

    save_and_close(fig, str(Path(log_dir) / "chart_mae_mfe.png"))
