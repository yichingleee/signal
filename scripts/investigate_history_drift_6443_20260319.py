"""Focused investigation for 6443 MonthTradingVal / VolRatio drift on 20260319.

This script compares text-ground-truth history inputs against parquet history inputs,
then captures replay-time screening context for symbol 6443 (plus evidence-driven
neighbor symbols) without mutating replay outputs.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from tw_signal_engine.market_data.load_history_window import load_history_window
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_history_loader import load_parquet_history_window
from tw_signal_engine.market_data.parquet_io import PARQUET_STATUS_EQ_FILTERS, parquet_path
from tw_signal_engine.records.market_event_records import MarketTick
from tw_signal_engine.replay.iterate_market_file import iterate_market_file
from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay
from tw_signal_engine.replay.session_hooks import ScreeningDetail, SessionHooks
from tw_signal_engine.state.symbol_state import IndexData

DAY_PER_MONTH = 20
ENCODINGS = ("utf-8-sig", "cp950", "big5hkscs")
MARKET_ALIASES = {
    "T": "TSE",
    "O": "OTC",
    "TSE": "TSE",
    "TWSE": "TSE",
    "OTC": "OTC",
    "TPEX": "OTC",
}


@dataclass(slots=True)
class SymbolMetadata:
    symbol: str
    name: str
    market: str
    market_raw: str
    source_file: Path
    encoding: str
    row_preview: list[str]


@dataclass(slots=True)
class ReplayCapture:
    rows: list[dict[str, Any]]
    neighbors: set[str]


def _raw_time_to_us(raw_time: int) -> int:
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return (hours * 3600 + minutes * 60 + seconds) * 1_000_000 + micros


def _raw_time_to_label(raw_time: int) -> str:
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{micros:06d}"


def _raw_time_to_hours(raw_time: int) -> float:
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return hours + minutes / 60.0 + seconds / 3600.0 + micros / 3_600_000_000.0


def _canonical_market(value: str) -> str:
    key = value.strip().upper()
    try:
        return MARKET_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported market code {value!r}; expected one of {sorted(MARKET_ALIASES)}") from exc


def _resolve_symbol_metadata(
    date: str,
    symbol: str,
    text_files_dir: Path,
    symbols_dir: Path,
) -> SymbolMetadata:
    candidates = [
        text_files_dir / f"Symbols_{date}.csv",
        symbols_dir / f"Symbols_{date}.csv",
    ]
    visited: set[Path] = set()
    for path in candidates:
        if path in visited:
            continue
        visited.add(path)
        if not path.exists():
            continue
        raw = path.read_bytes()
        for encoding in ENCODINGS:
            try:
                content = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            for row in csv.reader(content.splitlines()):
                if not row:
                    continue
                if row[0].strip() != symbol:
                    continue
                if len(row) < 3:
                    raise ValueError(f"Malformed symbol row for {symbol} in {path}")
                market_raw = row[2].strip()
                return SymbolMetadata(
                    symbol=symbol,
                    name=(row[1].strip() if len(row) > 1 else ""),
                    market=_canonical_market(market_raw),
                    market_raw=market_raw,
                    source_file=path,
                    encoding=encoding,
                    row_preview=row[:9],
                )
    raise FileNotFoundError(
        f"Symbol {symbol} not found in Symbols_{date}.csv under {text_files_dir} or {symbols_dir}"
    )


def _tracker_final_cum(tracker: LinearVolumeTracker, symbol: str) -> int:
    nodes = tracker.data_store.get(symbol)
    if not nodes:
        return 0
    return nodes[-1].cumulative_qty


def _tracker_row_count(tracker: LinearVolumeTracker, symbol: str) -> int:
    return len(tracker.data_store.get(symbol, []))


def _history_day_metrics(history: Any, symbol: str) -> dict[str, dict[str, int]]:
    by_date: dict[str, dict[str, int]] = {}
    for idx, source_date in enumerate(history.source_dates):
        tracker = history.vol_cum[idx]
        by_date[source_date] = {
            "final_cum": _tracker_final_cum(tracker, symbol),
            "trading_val": history.trading_val[idx].get(symbol, 0),
            "row_count": _tracker_row_count(tracker, symbol),
        }
    return by_date


def _choose_source_dates(text_by_date: dict[str, dict[str, int]], parq_by_date: dict[str, dict[str, int]]) -> list[str]:
    dates = set(text_by_date) | set(parq_by_date)
    return sorted(dates, reverse=True)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _load_text_symbol_ticks(
    date: str,
    market: str,
    symbol: str,
    text_data_dir: Path,
) -> list[tuple[int, int, int]]:
    ticks: list[tuple[int, int, int]] = []
    for tick in iterate_market_file(market, date, str(text_data_dir), tick_filter={symbol}):
        if tick.symbol != symbol:
            continue
        ticks.append((tick.match_time_str, tick.match_time_us, tick.match.qty))
    ticks.sort(key=lambda row: row[0])
    return ticks


def _load_parquet_symbol_ticks(
    date: str,
    market: str,
    symbol: str,
    parquet_root: Path,
) -> list[tuple[int, int, int]]:
    path = parquet_path(parquet_root, market, date)
    filters: list[tuple[str, str, object]] = list(PARQUET_STATUS_EQ_FILTERS)
    filters.extend([
        ("tradeVolume", ">", 0),
        ("symbol", "==", symbol),
    ])
    table = pq.read_table(str(path), columns=["time", "tradeVolume"], filters=filters)
    times = table.column("time").to_pylist()
    volumes = table.column("tradeVolume").to_pylist()
    ticks = [(int(raw_time), _raw_time_to_us(int(raw_time)), int(qty)) for raw_time, qty in zip(times, volumes)]
    ticks.sort(key=lambda row: row[0])
    return ticks


def _cumulative_by_timestamp(
    events: list[tuple[int, int, int]],
    timestamps: list[int],
) -> list[int]:
    cum = 0
    out: list[int] = []
    ptr = 0
    sorted_events = sorted(events, key=lambda row: row[0])
    for ts in timestamps:
        while ptr < len(sorted_events) and sorted_events[ptr][0] <= ts:
            cum += sorted_events[ptr][2]
            ptr += 1
        out.append(cum)
    return out


def _history_query_series(
    history: Any,
    symbol: str,
    timestamps_us: list[int],
) -> tuple[list[int], list[int], dict[str, list[int]]]:
    total = [0] * len(timestamps_us)
    per_day: dict[str, list[int]] = {}
    for i, source_date in enumerate(history.source_dates):
        tracker = history.vol_cum[i]
        values: list[int] = []
        for j, ts_us in enumerate(timestamps_us):
            value = tracker.query(symbol, ts_us)
            values.append(value)
            total[j] += value
        per_day[source_date] = values
    avg = [value // DAY_PER_MONTH if value > 0 else 1 for value in total]
    return total, avg, per_day


def _top_delta_dates(
    text_per_day: dict[str, list[int]],
    parq_per_day: dict[str, list[int]],
    row_idx: int,
    top_n: int = 3,
) -> str:
    pairs: list[tuple[str, int]] = []
    for source_date in sorted(set(text_per_day) | set(parq_per_day)):
        text_val = text_per_day.get(source_date, [0] * (row_idx + 1))[row_idx]
        parq_val = parq_per_day.get(source_date, [0] * (row_idx + 1))[row_idx]
        delta = parq_val - text_val
        if delta != 0:
            pairs.append((source_date, delta))
    pairs.sort(key=lambda item: abs(item[1]), reverse=True)
    top = pairs[:top_n]
    return " | ".join(f"{d}:{delta:+d}" for d, delta in top)


class _ReplayCollector:
    def __init__(self, data_source: str, focus_symbols: set[str]) -> None:
        self.data_source = data_source
        self.focus_symbols = focus_symbols
        self.rows: list[dict[str, Any]] = []
        self._last_row_idx_by_symbol: dict[str, int] = {}
        self._tick_seq = 0

    def on_tick(self, tick: MarketTick, idx: IndexData) -> None:
        if tick.symbol not in self.focus_symbols:
            return
        self._tick_seq += 1
        row: dict[str, Any] = {
            "data_source": self.data_source,
            "tick_seq": self._tick_seq,
            "symbol": tick.symbol,
            "market": tick.market,
            "match_time_raw": tick.match_time_str,
            "match_time": _raw_time_to_label(tick.match_time_str),
            "match_time_us": tick.match_time_us,
            "price_int": tick.match.price,
            "qty": tick.match.qty,
            "idx_vwap": idx.vwap,
            "idx_day_high_int": idx.day_high,
            "idx_day_low_int": idx.day_low,
            "match_type": "None",
            "qualified": False,
            "strong_group": False,
            "strong_single": False,
            "group_name": "",
            "group_rank": 0,
            "member_rank": 0,
            "raw_member_rank": 0,
            "m1_symbol": "",
            "vol_ratio": 0.0,
            "month_trading_val": 0,
            "ahead_symbol": "",
            "behind_symbol": "",
            "signal_a": False,
            "signal_b": False,
            "entry_executed": False,
            "exit_cause": "",
        }
        self.rows.append(row)
        self._last_row_idx_by_symbol[tick.symbol] = len(self.rows) - 1

    def on_screening_detail(self, detail: ScreeningDetail) -> None:
        idx = self._last_row_idx_by_symbol.get(detail.symbol)
        if idx is None:
            return
        row = self.rows[idx]
        if int(row["match_time_raw"]) != detail.match_time_str:
            return
        row.update(
            {
                "match_type": detail.match_type,
                "qualified": detail.qualified,
                "strong_group": detail.strong_group,
                "strong_single": detail.strong_single,
                "group_name": detail.group_name,
                "group_rank": detail.group_rank,
                "member_rank": detail.member_rank,
                "raw_member_rank": detail.raw_member_rank,
                "m1_symbol": detail.m1_symbol,
                "vol_ratio": detail.vol_ratio,
                "month_trading_val": detail.month_trading_val,
                "ahead_symbol": detail.ahead_symbol,
                "behind_symbol": detail.behind_symbol,
            }
        )

    def on_signal(self, symbol: str, signal_type: str, triggered: bool) -> None:
        idx = self._last_row_idx_by_symbol.get(symbol)
        if idx is None or not triggered:
            return
        if signal_type == "SignalA":
            self.rows[idx]["signal_a"] = True
        elif signal_type == "SignalB":
            self.rows[idx]["signal_b"] = True

    def on_entry(self, symbol: str, _trade: Any) -> None:
        idx = self._last_row_idx_by_symbol.get(symbol)
        if idx is None:
            return
        self.rows[idx]["entry_executed"] = True

    def on_exit(self, symbol: str, cause: str, _record: Any) -> None:
        idx = self._last_row_idx_by_symbol.get(symbol)
        if idx is None:
            return
        self.rows[idx]["exit_cause"] = cause


def _run_replay_capture(
    *,
    data_source: str,
    focus_symbols: set[str],
    trade_date: str,
    config_path: Path,
    text_data_dir: Path,
    text_files_dir: Path,
    group_file: Path,
    parquet_root: Path,
    history: Any,
) -> ReplayCapture:
    collector = _ReplayCollector(data_source=data_source, focus_symbols=focus_symbols)

    hooks = SessionHooks(
        on_tick=collector.on_tick,
        on_screening_detail=collector.on_screening_detail,
        on_signal=collector.on_signal,
        on_entry=collector.on_entry,
        on_exit=collector.on_exit,
    )

    run_daily_replay(
        trade_date=trade_date,
        config_path=str(config_path),
        data_dir=str(parquet_root if data_source == "parquet" else text_data_dir),
        files_dir=str(text_files_dir),
        group_file=str(group_file),
        history=history,
        hooks=hooks,
        no_charts=True,
        data_source=data_source,
        write_outputs=False,
    )

    neighbors: set[str] = set()
    for row in collector.rows:
        for field in ("ahead_symbol", "behind_symbol", "m1_symbol"):
            value = str(row[field]).strip()
            if value:
                neighbors.add(value)
    neighbors.discard("")
    neighbors.difference_update(focus_symbols)

    return ReplayCapture(rows=collector.rows, neighbors=neighbors)


def _choose_neighbor_symbols(
    target_symbol: str,
    pass_rows: list[dict[str, Any]],
    top_n: int = 8,
) -> list[str]:
    counter: Counter[str] = Counter()
    for row in pass_rows:
        if row["symbol"] != target_symbol:
            continue
        for field in ("ahead_symbol", "behind_symbol", "m1_symbol"):
            sym = str(row[field]).strip()
            if not sym or sym == target_symbol:
                continue
            counter[sym] += 1
    return [sym for sym, _ in counter.most_common(top_n)]


def _attempt_plots(
    output_dir: Path,
    source_rows: list[dict[str, Any]],
    volratio_rows: list[dict[str, Any]],
) -> tuple[list[str], str | None]:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - environment-dependent fallback
        return [], f"matplotlib unavailable ({exc})"

    generated: list[str] = []

    # 1) MonthTradingVal per source date
    dates = [row["source_date"] for row in source_rows]
    text_vals = [int(row["text_trading_val"]) for row in source_rows]
    parq_vals = [int(row["parquet_trading_val"]) for row in source_rows]
    x = list(range(len(dates)))
    width = 0.42

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.bar([i - width / 2 for i in x], text_vals, width=width, label="Text", alpha=0.85)
    ax.bar([i + width / 2 for i in x], parq_vals, width=width, label="Parquet", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(dates, rotation=45, ha="right")
    ax.set_ylabel("Trading Value")
    ax.set_title("6443 Prior-Session Trading Value Contributions")
    ax.legend()
    fig.tight_layout()
    p1 = output_dir / "chart-monthtradingval-source-days.png"
    fig.savefig(p1, dpi=180)
    plt.close(fig)
    generated.append(p1.name)

    # 2) VolRatio timeline
    t_hours = [_raw_time_to_hours(int(row["timestamp_raw"])) for row in volratio_rows]
    text_avg = [int(row["text_history_avg_volume"]) for row in volratio_rows]
    parq_avg = [int(row["parquet_history_avg_volume"]) for row in volratio_rows]
    text_cum = [int(row["text_current_cum_volume"]) for row in volratio_rows]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(t_hours, text_avg, label="Text history avg cum volume", linewidth=1.8)
    ax.plot(t_hours, parq_avg, label="Parquet history avg cum volume", linewidth=1.8)
    ax.plot(t_hours, text_cum, label="Current-day text cum volume", linewidth=1.2, alpha=0.8)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Volume")
    ax.set_title("6443 VolRatio Inputs Over Time")
    ax.legend()
    fig.tight_layout()
    p2 = output_dir / "chart-volratio-timeline.png"
    fig.savefig(p2, dpi=180)
    plt.close(fig)
    generated.append(p2.name)

    # 3) VolRatio drift hotspots
    drift = [abs(float(row["volratio_delta"])) for row in volratio_rows]
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(t_hours, drift, linewidth=1.6, label="|Parquet - Text| VolRatio")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Absolute VolRatio delta")
    ax.set_title("6443 VolRatio Drift Hotspots")

    hotspot_rows = sorted(volratio_rows, key=lambda row: abs(float(row["volratio_delta"])), reverse=True)[:3]
    for row in hotspot_rows:
        xh = _raw_time_to_hours(int(row["timestamp_raw"]))
        yh = abs(float(row["volratio_delta"]))
        ax.scatter([xh], [yh], s=36)
        label = str(row["top_denominator_delta_dates"]) or "no denominator drift"
        ax.annotate(label, (xh, yh), textcoords="offset points", xytext=(6, 8), fontsize=8)

    ax.legend()
    fig.tight_layout()
    p3 = output_dir / "chart-volratio-drift-hotspots.png"
    fig.savefig(p3, dpi=180)
    plt.close(fig)
    generated.append(p3.name)

    return generated, None


def _summarize_replay_drift(target_symbol: str, replay_rows: list[dict[str, Any]]) -> dict[str, Any]:
    text_rows = [r for r in replay_rows if r["symbol"] == target_symbol and r["data_source"] == "text"]
    parq_rows = [r for r in replay_rows if r["symbol"] == target_symbol and r["data_source"] == "parquet"]

    text_by_ts: dict[int, dict[str, Any]] = {}
    parq_by_ts: dict[int, dict[str, Any]] = {}

    for row in text_rows:
        text_by_ts[int(row["match_time_raw"])] = row
    for row in parq_rows:
        parq_by_ts[int(row["match_time_raw"])] = row

    common_ts = sorted(set(text_by_ts) & set(parq_by_ts))
    screening_diff = 0
    rank_diff = 0
    neighbor_diff = 0
    for ts in common_ts:
        t = text_by_ts[ts]
        p = parq_by_ts[ts]
        if t["match_type"] != p["match_type"]:
            screening_diff += 1
        if int(t["group_rank"]) != int(p["group_rank"]) or int(t["member_rank"]) != int(p["member_rank"]):
            rank_diff += 1
        if (t["ahead_symbol"], t["behind_symbol"]) != (p["ahead_symbol"], p["behind_symbol"]):
            neighbor_diff += 1

    return {
        "text_tick_rows": len(text_rows),
        "parquet_tick_rows": len(parq_rows),
        "common_timestamp_rows": len(common_ts),
        "screening_diff_rows": screening_diff,
        "rank_diff_rows": rank_diff,
        "neighbor_diff_rows": neighbor_diff,
    }


def _render_report(
    *,
    output_dir: Path,
    metadata: SymbolMetadata,
    args: argparse.Namespace,
    source_rows: list[dict[str, Any]],
    month_rows: list[dict[str, Any]],
    volratio_rows: list[dict[str, Any]],
    replay_rows: list[dict[str, Any]],
    replay_summary: dict[str, Any],
    neighbor_symbols: list[str],
    chart_files: list[str],
    plot_error: str | None,
) -> str:
    month_total_text = int(month_rows[-1]["text_month_total"])
    month_total_parq = int(month_rows[-1]["parquet_month_total"])
    month_avg_text = int(month_rows[-1]["text_month_avg"])
    month_avg_parq = int(month_rows[-1]["parquet_month_avg"])
    month_avg_delta = int(month_rows[-1]["month_avg_delta"])
    month_total_delta = int(month_rows[-1]["month_total_delta"])

    top_source_days = sorted(source_rows, key=lambda row: abs(int(row["trading_val_delta"])), reverse=True)[:5]
    top_vr = sorted(volratio_rows, key=lambda row: abs(float(row["volratio_delta"])), reverse=True)[:5]

    numerator_drift = sum(1 for row in volratio_rows if int(row["current_cum_delta"]) != 0)
    denominator_drift = sum(1 for row in volratio_rows if int(row["history_avg_delta"]) != 0)
    positive_day_delta = sum(max(int(row["trading_val_delta"]), 0) for row in source_rows)

    root_causes: list[str] = []
    if month_avg_delta != 0 or denominator_drift > 0:
        root_causes.append("direct history mismatch")
    if numerator_drift > 0:
        root_causes.append("replay stream-shape mismatch")
    if replay_summary["screening_diff_rows"] > 0 and (
        replay_summary["rank_diff_rows"] > 0 or replay_summary["neighbor_diff_rows"] > 0
    ):
        root_causes.append("indirect group-state drift")
    if not root_causes:
        root_causes = ["no material drift observed"]

    conclusion = (
        f"For {metadata.symbol} on {args.date}, treating text history as ground truth, the evidence indicates "
        f"{', '.join(root_causes)}. "
        f"MonthTradingVal text/parquet averages are {month_avg_text:,} vs {month_avg_parq:,} "
        f"(delta {month_avg_delta:+,}), and VolRatio drift peaks are documented in "
        "`volratio-timestamp-attribution.csv`."
    )

    lines: list[str] = []
    lines.append(f"# 6443 history drift investigation ({args.date})")
    lines.append("")
    lines.append(conclusion)
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- Symbol: `{metadata.symbol}` ({metadata.name})")
    lines.append(f"- Symbol market (resolved): `{metadata.market}` (raw code `{metadata.market_raw}`)")
    lines.append(f"- Symbol source file: `{metadata.source_file}` (encoding `{metadata.encoding}`)")
    lines.append(f"- Symbol row preview: `{metadata.row_preview}`")
    lines.append(f"- Text data dir: `{args.text_data_dir}`")
    lines.append(f"- Parquet root: `{args.parquet_root}`")
    lines.append(f"- Group file: `{args.group_file}`")
    lines.append("")
    lines.append("## Generated artifacts")
    lines.append("")
    lines.append("- [source-day-attribution.csv](source-day-attribution.csv)")
    lines.append("- [monthtradingval-decomposition.csv](monthtradingval-decomposition.csv)")
    lines.append("- [volratio-timestamp-attribution.csv](volratio-timestamp-attribution.csv)")
    lines.append("- [replay-context-6443.csv](replay-context-6443.csv)")
    if chart_files:
        for name in chart_files:
            lines.append(f"- [{name}]({name})")
    elif plot_error is not None:
        lines.append(f"- Plotting skipped: {plot_error}")
    lines.append("")

    lines.append("## MonthTradingVal attribution")
    lines.append("")
    lines.append("Text is treated as ground truth in this experiment, so any positive parquet delta is interpreted as parquet over-counting history relative to the legacy replay input.")
    lines.append("")
    lines.append(f"- Text month total over 20-day denominator: `{month_total_text:,}`")
    lines.append(f"- Parquet month total over 20-day denominator: `{month_total_parq:,}`")
    lines.append(f"- Month total delta (parquet - text): `{month_total_delta:+,}`")
    lines.append(f"- Text month average: `{month_avg_text:,}`")
    lines.append(f"- Parquet month average: `{month_avg_parq:,}`")
    lines.append(f"- Average delta (parquet - text): `{month_avg_delta:+,}`")
    lines.append("")
    lines.append("Largest per-source-date trading-value deltas (parquet - text):")
    lines.append("")
    for row in top_source_days:
        day_delta = int(row["trading_val_delta"])
        contribution = (day_delta / positive_day_delta * 100.0) if positive_day_delta > 0 else 0.0
        lines.append(
            f"- `{row['source_date']}` text={int(row['text_trading_val']):,} "
            f"parquet={int(row['parquet_trading_val']):,} delta={day_delta:+,} "
            f"({contribution:.1f}% of positive month-total delta)"
        )
    lines.append("")

    lines.append("## VolRatio attribution")
    lines.append("")
    lines.append(f"- Timestamps analyzed: `{len(volratio_rows):,}`")
    lines.append(f"- Rows with numerator drift (current-day cumulative volume): `{numerator_drift:,}`")
    lines.append(f"- Rows with denominator drift (history average cumulative volume): `{denominator_drift:,}`")
    if numerator_drift == 0 and denominator_drift > 0:
        lines.append("- Interpretation: `VolRatio` drift comes entirely from the history denominator in this experiment; current-day 6443 cumulative volume is identical between text and parquet.")
    lines.append("")
    lines.append("Largest absolute VolRatio deltas:")
    lines.append("")
    for row in top_vr:
        lines.append(
            f"- `{row['timestamp']}` text={float(row['text_volratio']):.4f} "
            f"parquet={float(row['parquet_volratio']):.4f} delta={float(row['volratio_delta']):+.4f} "
            f"(top denominator contributors: `{row['top_denominator_delta_dates']}`)"
        )
    lines.append("")

    lines.append("## Replay-context evidence")
    lines.append("")
    lines.append(f"- Replay rows captured for `{metadata.symbol}` (text): `{replay_summary['text_tick_rows']:,}`")
    lines.append(f"- Replay rows captured for `{metadata.symbol}` (parquet): `{replay_summary['parquet_tick_rows']:,}`")
    lines.append(f"- Shared timestamps between text/parquet target rows: `{replay_summary['common_timestamp_rows']:,}`")
    lines.append(f"- Screening decision mismatches on shared timestamps: `{replay_summary['screening_diff_rows']:,}`")
    lines.append(f"- Rank mismatches on shared timestamps: `{replay_summary['rank_diff_rows']:,}`")
    lines.append(f"- Neighbor-ahead/behind mismatches on shared timestamps: `{replay_summary['neighbor_diff_rows']:,}`")
    if neighbor_symbols:
        lines.append(f"- Evidence-driven neighbor symbols captured: `{', '.join(neighbor_symbols)}`")
    else:
        lines.append("- Evidence-driven neighbor symbols captured: none")
    lines.append("")

    if chart_files:
        lines.append("## Visualizations")
        lines.append("")
        for name in chart_files:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"![{name}]({name})")
            lines.append("")

    lines.append("## Recommended follow-up")
    lines.append("")
    lines.append(
        "Use `monthtradingval-decomposition.csv` and `volratio-timestamp-attribution.csv` to pinpoint the smallest "
        "loader or stream-shaping change that removes the dominant delta dates/timestamps, then validate that change "
        "with this same script before broader parquet migration updates."
    )
    lines.append("")

    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return conclusion


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Investigate MonthTradingVal/VolRatio drift for 6443 on 20260319")
    parser.add_argument("--date", default="20260319", help="Trade date YYYYMMDD")
    parser.add_argument("--symbol", default="6443", help="Target symbol")
    parser.add_argument(
        "--market",
        default="",
        help="Optional market override (TSE/OTC). If omitted, derive from Symbols_YYYYMMDD.csv.",
    )
    parser.add_argument("--text-data-dir", default="exec/data", help="Directory containing TSEQuote/OTCQuote files")
    parser.add_argument("--text-files-dir", default="exec/files", help="Directory containing Symbols_YYYYMMDD.csv")
    parser.add_argument(
        "--parquet-root",
        default="/Users/liyijing/Projects/Trading/market-data/tick-data",
        help="Parquet root containing TWSE/ and TPEX/",
    )
    parser.add_argument(
        "--symbols-dir",
        default="/Users/liyijing/Projects/Trading/market-data/symbols",
        help="Fallback Symbols_YYYYMMDD.csv directory",
    )
    parser.add_argument(
        "--group-file",
        default="/Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv",
        help="Group membership CSV for replay-context capture",
    )
    parser.add_argument("--config", default="exec/cfg/parameter.cfg", help="Replay config path")
    parser.add_argument(
        "--output-dir",
        default="artifacts/history-drift/6443-20260319",
        help="Output artifact directory",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    text_data_dir = Path(args.text_data_dir)
    text_files_dir = Path(args.text_files_dir)
    parquet_root = Path(args.parquet_root)
    symbols_dir = Path(args.symbols_dir)
    group_file = Path(args.group_file)
    config_path = Path(args.config)
    output_dir = Path(args.output_dir)

    for path in (text_data_dir, text_files_dir, parquet_root, group_file, config_path):
        if not path.exists():
            raise FileNotFoundError(f"Required path not found: {path}")

    metadata = _resolve_symbol_metadata(
        date=args.date,
        symbol=args.symbol,
        text_files_dir=text_files_dir,
        symbols_dir=symbols_dir,
    )
    market = _canonical_market(args.market) if args.market else metadata.market

    # Load and merge both-market histories exactly as replay_session does.
    text_otc = load_history_window("OTC", args.date, str(text_data_dir), use_cache=False)
    text_tse = load_history_window("TSE", args.date, str(text_data_dir), use_cache=False)
    parq_otc = load_parquet_history_window("OTC", args.date, parquet_root)
    parq_tse = load_parquet_history_window("TSE", args.date, parquet_root)

    text_merged = _merge_history_windows(text_otc, text_tse)
    parq_merged = _merge_history_windows(parq_otc, parq_tse)

    text_by_date = _history_day_metrics(text_merged, args.symbol)
    parq_by_date = _history_day_metrics(parq_merged, args.symbol)
    source_dates = _choose_source_dates(text_by_date, parq_by_date)

    source_rows: list[dict[str, Any]] = []
    for source_date in source_dates:
        t = text_by_date.get(source_date, {"final_cum": 0, "trading_val": 0, "row_count": 0})
        p = parq_by_date.get(source_date, {"final_cum": 0, "trading_val": 0, "row_count": 0})
        source_rows.append(
            {
                "source_date": source_date,
                "market": market,
                "text_final_cum_volume": t["final_cum"],
                "parquet_final_cum_volume": p["final_cum"],
                "final_cum_volume_delta": p["final_cum"] - t["final_cum"],
                "text_trading_val": t["trading_val"],
                "parquet_trading_val": p["trading_val"],
                "trading_val_delta": p["trading_val"] - t["trading_val"],
                "text_row_count": t["row_count"],
                "parquet_row_count": p["row_count"],
                "row_count_delta": p["row_count"] - t["row_count"],
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    source_day_csv = output_dir / "source-day-attribution.csv"
    _write_csv(
        source_day_csv,
        source_rows,
        [
            "source_date",
            "market",
            "text_final_cum_volume",
            "parquet_final_cum_volume",
            "final_cum_volume_delta",
            "text_trading_val",
            "parquet_trading_val",
            "trading_val_delta",
            "text_row_count",
            "parquet_row_count",
            "row_count_delta",
        ],
    )

    # MonthTradingVal decomposition (StrongGroup formula: floor(total / 20)).
    text_month_total = sum(int(row["text_trading_val"]) for row in source_rows)
    parq_month_total = sum(int(row["parquet_trading_val"]) for row in source_rows)
    text_month_avg = text_month_total // DAY_PER_MONTH
    parq_month_avg = parq_month_total // DAY_PER_MONTH

    month_rows: list[dict[str, Any]] = []
    for row in source_rows:
        month_rows.append(
            {
                "source_date": row["source_date"],
                "text_trading_val": row["text_trading_val"],
                "parquet_trading_val": row["parquet_trading_val"],
                "trading_val_delta": row["trading_val_delta"],
                "text_month_total": text_month_total,
                "parquet_month_total": parq_month_total,
                "month_total_delta": parq_month_total - text_month_total,
                "text_month_avg": text_month_avg,
                "parquet_month_avg": parq_month_avg,
                "month_avg_delta": parq_month_avg - text_month_avg,
                "per_day_delta_over_20": float(row["trading_val_delta"]) / DAY_PER_MONTH,
                "decomposition_identity": (
                    "parquet_month_avg - text_month_avg = "
                    "sum(per-day trading_val_delta) // 20"
                ),
            }
        )

    month_rows.append(
        {
            "source_date": "__SUMMARY__",
            "text_trading_val": text_month_total,
            "parquet_trading_val": parq_month_total,
            "trading_val_delta": parq_month_total - text_month_total,
            "text_month_total": text_month_total,
            "parquet_month_total": parq_month_total,
            "month_total_delta": parq_month_total - text_month_total,
            "text_month_avg": text_month_avg,
            "parquet_month_avg": parq_month_avg,
            "month_avg_delta": parq_month_avg - text_month_avg,
            "per_day_delta_over_20": float(parq_month_total - text_month_total) / DAY_PER_MONTH,
            "decomposition_identity": (
                f"({parq_month_total} - {text_month_total}) // {DAY_PER_MONTH} = {parq_month_avg - text_month_avg}"
            ),
        }
    )

    month_csv = output_dir / "monthtradingval-decomposition.csv"
    _write_csv(
        month_csv,
        month_rows,
        [
            "source_date",
            "text_trading_val",
            "parquet_trading_val",
            "trading_val_delta",
            "text_month_total",
            "parquet_month_total",
            "month_total_delta",
            "text_month_avg",
            "parquet_month_avg",
            "month_avg_delta",
            "per_day_delta_over_20",
            "decomposition_identity",
        ],
    )

    # VolRatio timestamp attribution.
    text_ticks = _load_text_symbol_ticks(args.date, market, args.symbol, text_data_dir)
    parq_ticks = _load_parquet_symbol_ticks(args.date, market, args.symbol, parquet_root)

    timestamp_raws = sorted({row[0] for row in text_ticks} | {row[0] for row in parq_ticks})
    timestamp_us = [_raw_time_to_us(ts) for ts in timestamp_raws]

    text_cum = _cumulative_by_timestamp(text_ticks, timestamp_raws)
    parq_cum = _cumulative_by_timestamp(parq_ticks, timestamp_raws)

    text_hist_total, text_hist_avg, text_hist_per_day = _history_query_series(text_merged, args.symbol, timestamp_us)
    parq_hist_total, parq_hist_avg, parq_hist_per_day = _history_query_series(parq_merged, args.symbol, timestamp_us)

    volratio_rows: list[dict[str, Any]] = []
    for idx, ts_raw in enumerate(timestamp_raws):
        t_avg = text_hist_avg[idx]
        p_avg = parq_hist_avg[idx]
        t_vr = (text_cum[idx] / t_avg) if t_avg > 0 else 0.0
        p_vr = (parq_cum[idx] / p_avg) if p_avg > 0 else 0.0
        volratio_rows.append(
            {
                "timestamp_raw": ts_raw,
                "timestamp": _raw_time_to_label(ts_raw),
                "text_current_cum_volume": text_cum[idx],
                "parquet_current_cum_volume": parq_cum[idx],
                "current_cum_delta": parq_cum[idx] - text_cum[idx],
                "text_history_total_volume": text_hist_total[idx],
                "parquet_history_total_volume": parq_hist_total[idx],
                "history_total_delta": parq_hist_total[idx] - text_hist_total[idx],
                "text_history_avg_volume": t_avg,
                "parquet_history_avg_volume": p_avg,
                "history_avg_delta": p_avg - t_avg,
                "text_volratio": t_vr,
                "parquet_volratio": p_vr,
                "volratio_delta": p_vr - t_vr,
                "top_denominator_delta_dates": _top_delta_dates(text_hist_per_day, parq_hist_per_day, idx),
            }
        )

    volratio_csv = output_dir / "volratio-timestamp-attribution.csv"
    _write_csv(
        volratio_csv,
        volratio_rows,
        [
            "timestamp_raw",
            "timestamp",
            "text_current_cum_volume",
            "parquet_current_cum_volume",
            "current_cum_delta",
            "text_history_total_volume",
            "parquet_history_total_volume",
            "history_total_delta",
            "text_history_avg_volume",
            "parquet_history_avg_volume",
            "history_avg_delta",
            "text_volratio",
            "parquet_volratio",
            "volratio_delta",
            "top_denominator_delta_dates",
        ],
    )

    # Replay-context capture pass 1: target symbol only.
    focus_pass1 = {args.symbol}
    pass1_text = _run_replay_capture(
        data_source="text",
        focus_symbols=focus_pass1,
        trade_date=args.date,
        config_path=config_path,
        text_data_dir=text_data_dir,
        text_files_dir=text_files_dir,
        group_file=group_file,
        parquet_root=parquet_root,
        history=text_merged,
    )
    pass1_parq = _run_replay_capture(
        data_source="parquet",
        focus_symbols=focus_pass1,
        trade_date=args.date,
        config_path=config_path,
        text_data_dir=text_data_dir,
        text_files_dir=text_files_dir,
        group_file=group_file,
        parquet_root=parquet_root,
        history=parq_merged,
    )

    neighbor_symbols = _choose_neighbor_symbols(args.symbol, pass1_text.rows + pass1_parq.rows)
    replay_rows = pass1_text.rows + pass1_parq.rows

    replay_rows.sort(key=lambda row: (str(row["data_source"]), int(row["match_time_raw"]), int(row["tick_seq"])))

    replay_csv = output_dir / "replay-context-6443.csv"
    replay_fields = [
        "data_source",
        "tick_seq",
        "symbol",
        "market",
        "match_time_raw",
        "match_time",
        "match_time_us",
        "price_int",
        "qty",
        "idx_vwap",
        "idx_day_high_int",
        "idx_day_low_int",
        "match_type",
        "qualified",
        "strong_group",
        "strong_single",
        "group_name",
        "group_rank",
        "member_rank",
        "raw_member_rank",
        "m1_symbol",
        "vol_ratio",
        "month_trading_val",
        "ahead_symbol",
        "behind_symbol",
        "signal_a",
        "signal_b",
        "entry_executed",
        "exit_cause",
    ]
    _write_csv(replay_csv, replay_rows, replay_fields)

    replay_summary = _summarize_replay_drift(args.symbol, replay_rows)

    chart_files, plot_error = _attempt_plots(output_dir, source_rows, volratio_rows)

    conclusion = _render_report(
        output_dir=output_dir,
        metadata=metadata,
        args=args,
        source_rows=source_rows,
        month_rows=month_rows,
        volratio_rows=volratio_rows,
        replay_rows=replay_rows,
        replay_summary=replay_summary,
        neighbor_symbols=neighbor_symbols,
        chart_files=chart_files,
        plot_error=plot_error,
    )

    print(f"[INFO] Symbol metadata: market={metadata.market} raw_market={metadata.market_raw} file={metadata.source_file}")
    print(f"[INFO] Conclusion: {conclusion}")
    print("[INFO] Wrote artifacts:")
    for name in [
        "report.md",
        "source-day-attribution.csv",
        "monthtradingval-decomposition.csv",
        "volratio-timestamp-attribution.csv",
        "replay-context-6443.csv",
        *chart_files,
    ]:
        print(f"  - {output_dir / name}")


if __name__ == "__main__":
    main()
