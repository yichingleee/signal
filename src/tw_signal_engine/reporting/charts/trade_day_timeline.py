"""Per-symbol intraday chart with price/VWAP and trade lifecycle annotations."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.replay.session_time import fmt_time
from tw_signal_engine.reporting.charts._style import (
    ACCENT,
    PRIMARY,
    marker_annotation_style,
    new_figure,
    save_and_close,
)
from tw_signal_engine.reporting.charts.trade_day_models import SymbolTradeDay, TradeMarker

SIGNAL_COLOR = "#f39c12"
ENTRY_COLOR = "#27ae60"
EXIT_COLOR = "#c0392b"

_KIND_PRIORITY = {"signal": 0, "entry": 1, "exit": 2}
_KIND_STYLE = {
    "signal": ("^", SIGNAL_COLOR, "Signal"),
    "entry": ("o", ENTRY_COLOR, "Entry"),
    "exit": ("X", EXIT_COLOR, "Exit"),
}
_LABEL_Y_OFFSETS = (20, -26, 34, -40, 48, -54)
_CLUSTER_TIME_GAP = 2_000_000  # 2s in match_time_str units


def _marker_sort_key(marker: TradeMarker) -> tuple[int, int, str]:
    return (marker.time_raw, _KIND_PRIORITY.get(marker.kind, 99), marker.label)


def _iter_marker_tiers(markers: list[TradeMarker]) -> list[tuple[TradeMarker, int]]:
    tiered: list[tuple[TradeMarker, int]] = []
    prev_time: int | None = None
    cluster_idx = 0

    for marker in markers:
        if prev_time is None or abs(marker.time_raw - prev_time) > _CLUSTER_TIME_GAP:
            cluster_idx = 0
        else:
            cluster_idx += 1
        tiered.append((marker, cluster_idx % len(_LABEL_Y_OFFSETS)))
        prev_time = marker.time_raw
    return tiered


def plot_trade_day_timeline(symbol_day: SymbolTradeDay, log_dir: str) -> None:
    """Render chart_trade_day_<symbol>.png for one traded symbol."""
    if not symbol_day.points or not symbol_day.markers:
        return

    fig, ax = new_figure(width=14, height=7)

    times = [point.time_raw for point in symbol_day.points]
    prices = [point.price for point in symbol_day.points]
    vwaps = [point.vwap for point in symbol_day.points]

    ax.plot(times, prices, color=PRIMARY, linewidth=1.2, label="Price")
    ax.plot(times, vwaps, color=ACCENT, linewidth=1.1, linestyle="--", label="Session VWAP")

    markers = sorted(symbol_day.markers, key=_marker_sort_key)
    for kind in ("signal", "entry", "exit"):
        style = _KIND_STYLE.get(kind)
        if style is None:
            continue
        marker_shape, color, legend_label = style
        kind_markers = [marker for marker in markers if marker.kind == kind]
        if not kind_markers:
            continue
        ax.scatter(
            [marker.time_raw for marker in kind_markers],
            [marker.price for marker in kind_markers],
            marker=marker_shape,
            c=color,
            s=45,
            zorder=4,
            label=legend_label,
        )

    annotate_style = marker_annotation_style()
    for marker, tier in _iter_marker_tiers(markers):
        ax.annotate(
            marker.label,
            xy=(marker.time_raw, marker.price),
            xytext=(8, _LABEL_Y_OFFSETS[tier]),
            textcoords="offset points",
            ha="left",
            va="center",
            arrowprops={"arrowstyle": "-", "color": "#7f8c8d", "lw": 0.6},
            **annotate_style,
        )

    tick_step = max(1, len(times) // 8)
    tick_times = [times[i] for i in range(0, len(times), tick_step)]
    if tick_times[-1] != times[-1]:
        tick_times.append(times[-1])
    ax.set_xticks(tick_times)
    ax.set_xticklabels([fmt_time(tick) for tick in tick_times], rotation=25, ha="right")

    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    ax.set_title(f"{symbol_day.symbol} Intraday Price vs VWAP")
    ax.grid(alpha=0.2)
    ax.legend(loc="best", fontsize=8)

    output = Path(log_dir) / f"chart_trade_day_{symbol_day.symbol}.png"
    save_and_close(fig, str(output))
