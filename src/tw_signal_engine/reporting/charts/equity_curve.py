"""Equity curve + drawdown chart."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts._style import ACCENT, LOSS, save_and_close


def plot_equity_curve(trades: list[TradeRecord], log_dir: str) -> None:
    """Generate chart_equity_curve.png — cumulative PnL + drawdown."""
    if len(trades) < 2:
        return

    from tw_signal_engine.reporting.charts._style import new_figure_2axes

    fig, ax1, ax2 = new_figure_2axes()

    cum_pnl: list[float] = []
    drawdown: list[float] = []
    total = 0.0
    peak = 0.0
    for t in trades:
        total += t.pnl
        cum_pnl.append(total)
        if total > peak:
            peak = total
        drawdown.append(total - peak)

    x = list(range(len(trades)))

    ax1.plot(x, cum_pnl, color=ACCENT, linewidth=1.5)
    ax1.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    ax1.set_ylabel("Cumulative PnL")
    ax1.set_title("Equity Curve")

    ax2.fill_between(x, drawdown, color=LOSS, alpha=0.5)
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Trade #")

    save_and_close(fig, str(Path(log_dir) / "chart_equity_curve.png"))
