"""Per-minute state snapshot writer for time-travel replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.apply_market_gate import MarketGate
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalAState, SignalBState


def _time_str_to_minutes(match_time_str: int) -> int:
    """Convert match_time_str (e.g. 93000000000) to minutes since midnight (e.g. 570)."""
    raw = match_time_str // 1_000_000  # strip microseconds → HMMSS
    raw //= 100  # strip seconds
    minutes = raw % 100
    hours = raw // 100
    return hours * 60 + minutes


def _minutes_to_hhmm(minutes: int) -> str:
    """Convert minutes since midnight to HH:MM string."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _time_str_to_hhmmss(match_time_str: int) -> str:
    """Convert match_time_str to HH:MM:SS string."""
    raw = match_time_str // 1_000_000
    seconds = raw % 100
    raw //= 100
    minutes = raw % 100
    hours = raw // 100
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _serialize_signal_a(state: SignalAState) -> dict[str, Any]:
    return {
        "symbol": state.symbol,
        "forbidden": state.forbidden,
        "triggered": state.triggered,
        "near_vwap": state.near_vwap,
        "low_since_near": state.low_since_near,
        "near_vwap_time": state.near_vwap_time,
        "near_vwap_pv_ratio": state.near_vwap_pv_ratio,
    }


def _serialize_signal_b(state: SignalBState) -> dict[str, Any]:
    return {
        "symbol": state.symbol,
        "forbidden": state.forbidden,
        "in_buffer_zone": state.in_buffer_zone,
        "in_trade_zone": state.in_trade_zone,
        "enter_market": state.enter_market,
        "rolling_low_val": state.rolling_low_val,
        "rolling_sum_ratio": state.rolling_sum_ratio,
    }


class SnapshotWriter:
    """Captures per-minute engine state snapshots and writes to Parquet."""

    def __init__(self, date: str, output_dir: str = "./cache/replay/") -> None:
        self.date = date
        self.output_dir = output_dir
        self._rows: list[dict[str, Any]] = []
        self._last_trade_count: int = 0

    def capture(
        self,
        match_time_str: int,
        strong_group: StrongGroupEvaluator,
        signal_a_map: dict[str, SignalAState],
        signal_b_map: dict[str, SignalBState],
        pos: PositionState,
        market_gate: MarketGate,
        completed_trades: list[TradeRecord],
        dashboard_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Capture current state as a snapshot row at a minute boundary."""
        minutes = _time_str_to_minutes(match_time_str)

        # Serialize group screening state
        groups_data: list[dict[str, Any]] = []
        for gain, name in strong_group.group_rank.iter_ranked():
            groups_data.append({"group": name, "gain": round(gain, 6)})

        # Serialize active signals
        signals_a = {
            sym: _serialize_signal_a(s)
            for sym, s in signal_a_map.items()
            if s.triggered or s.near_vwap
        }
        signals_b = {
            sym: _serialize_signal_b(s)
            for sym, s in signal_b_map.items()
            if s.in_buffer_zone or s.in_trade_zone or s.enter_market
        }

        # Serialize positions
        positions: dict[str, dict[str, Any]] = {}
        for sym, qty in pos.stocks.items():
            if abs(qty) > 0.001:
                positions[sym] = {
                    "qty": qty,
                    "cash": pos.symbol_cash.get(sym, 0),
                    "signal_type": "",
                    "side": "short" if qty < 0 else "long",
                }
                if sym in pos.open_trades:
                    ot = pos.open_trades[sym]
                    positions[sym]["signal_type"] = ot.signal_type
                    positions[sym]["entry_price"] = ot.entry_price
                    positions[sym]["side"] = ot.side

        # New trades since last snapshot
        new_trade_count = len(completed_trades) - self._last_trade_count
        new_trades: list[dict[str, Any]] = []
        if new_trade_count > 0:
            for tr in completed_trades[-new_trade_count:]:
                new_trades.append({
                    "symbol": tr.symbol,
                    "side": tr.side,
                    "signal_type": tr.signal_type,
                    "pnl": tr.pnl,
                    "return_pct": tr.return_pct,
                    "leave_cause": tr.final_leave_cause,
                })
        self._last_trade_count = len(completed_trades)

        dashboard_groups: list[dict[str, Any]] = []
        dashboard_singles: list[dict[str, Any]] = []
        dashboard_vwap: list[dict[str, Any]] = []
        dashboard_signal_a: dict[str, Any] = {}
        if dashboard_snapshot is not None:
            groups_raw = dashboard_snapshot.get("groups")
            singles_raw = dashboard_snapshot.get("singles")
            vwap_raw = dashboard_snapshot.get("vwap_monitor")
            signal_a_raw = dashboard_snapshot.get("signal_a")
            if isinstance(groups_raw, list):
                dashboard_groups = [g for g in groups_raw if isinstance(g, dict)]
            if isinstance(singles_raw, list):
                dashboard_singles = [s for s in singles_raw if isinstance(s, dict)]
            if isinstance(vwap_raw, list):
                dashboard_vwap = [v for v in vwap_raw if isinstance(v, dict)]
            if isinstance(signal_a_raw, dict):
                dashboard_signal_a = signal_a_raw

        self._rows.append({
            "timestamp": minutes,
            "time_str": _minutes_to_hhmm(minutes),
            "market_time": _time_str_to_hhmmss(match_time_str),
            "strong_groups": json.dumps(groups_data, ensure_ascii=False),
            "signals_a": json.dumps(signals_a, ensure_ascii=False),
            "signals_b": json.dumps(signals_b, ensure_ascii=False),
            "positions": json.dumps(positions, ensure_ascii=False),
            "completed_trades": json.dumps(new_trades, ensure_ascii=False),
            "market_disabled": market_gate.market_disabled,
            "total_trades": len(completed_trades),
            "dashboard_groups": json.dumps(dashboard_groups, ensure_ascii=False),
            "dashboard_singles": json.dumps(dashboard_singles, ensure_ascii=False),
            "dashboard_vwap": json.dumps(dashboard_vwap, ensure_ascii=False),
            "dashboard_signal_a": json.dumps(dashboard_signal_a, ensure_ascii=False),
        })

    def finalize(self) -> Path | None:
        """Write all snapshots to Parquet. Returns path or None if no data."""
        if not self._rows:
            return None
        df = pd.DataFrame(self._rows)
        path = Path(self.output_dir) / f"ReplayData_{self.date}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        return path


class SignalSnapshotWriter:
    """Accumulates signal events and writes to Parquet."""

    def __init__(self, date: str, output_dir: str = "./cache/replay/") -> None:
        self.date = date
        self.output_dir = output_dir
        self._entries: list[dict[str, Any]] = []
        self._exits: list[dict[str, Any]] = []

    def on_entry(self, symbol: str, trade: EntryTrade) -> None:
        self._entries.append({
            "symbol": symbol,
            "signal_type": trade.signal_type,
            "enter_cause": trade.enter_cause,
            "entry_time_raw": trade.entry_time_raw,
            "entry_price": trade.entry_price,
            "entry_vwap": trade.entry_vwap,
            "group_name": trade.group_name,
            "group_rank": trade.group_rank,
            "member_rank": trade.member_rank,
            "date": self.date,
        })

    def on_exit(self, symbol: str, cause: str, record: TradeRecord) -> None:
        self._exits.append({
            "symbol": symbol,
            "signal_type": record.signal_type,
            "enter_cause": record.enter_cause,
            "leave_cause": cause,
            "entry_time_raw": record.entry_time_raw,
            "exit_time_raw": record.exit_time_raw,
            "pnl": record.pnl,
            "return_pct": record.return_pct,
            "entry_price": record.entry_price,
            "entry_vwap": record.entry_vwap,
            "group_name": record.group_name,
            "date": self.date,
        })

    def finalize(self) -> Path | None:
        """Write signal records to Parquet. Returns path or None if no data."""
        rows = self._entries + self._exits
        if not rows:
            return None
        df = pd.DataFrame(rows)
        path = Path(self.output_dir) / f"ReplaySignals_{self.date}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        return path
