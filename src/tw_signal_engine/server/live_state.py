"""Thread-safe live engine state for API consumption."""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Any

from tw_signal_engine.records.market_event_records import MarketTick, TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.session_hooks import SessionHooks
from tw_signal_engine.server.dashboard_snapshot import (
    DashboardSnapshot,
    SignalAMonitorSnapshot,
)
from tw_signal_engine.state.symbol_state import IndexData


class LiveState:
    """Thread-safe container for live engine state, updated via hooks.

    The engine runs in a background thread and updates this state via callbacks.
    The API reads from this state in the main (asyncio) thread.
    All reads/writes are protected by a lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tick_count: int = 0
        self._last_time_str: int = 0
        self._last_prices: dict[str, int] = {}
        self._last_indices: dict[str, dict[str, float]] = {}
        self._active_entries: dict[str, dict[str, Any]] = {}
        self._completed_trades: list[dict[str, Any]] = []
        self._recent_signals: list[dict[str, Any]] = []
        self._screening_hits: list[dict[str, Any]] = []
        self._market_disabled: bool = False
        self._dashboard_snapshot: DashboardSnapshot | None = None
        self._engine_status: str = "starting"
        self._fatal_error: str | None = None
        self._fatal_traceback: str | None = None

    def build_hooks(self) -> SessionHooks:
        """Create SessionHooks that update this live state."""
        return SessionHooks(
            on_tick=self._on_tick,
            on_screening=self._on_screening,
            on_signal=self._on_signal,
            on_entry=self._on_entry,
            on_exit=self._on_exit,
        )

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            status: dict[str, Any] = {
                "mode": "live",
                "tick_count": self._tick_count,
                "last_time_str": self._last_time_str,
                "engine_status": self._engine_status,
            }
            if self._fatal_error is not None:
                status["fatal_error"] = self._fatal_error
            if self._fatal_traceback is not None:
                status["fatal_traceback"] = self._fatal_traceback
            return status

    def get_positions(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._active_entries)

    def get_completed_trades(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._completed_trades)

    def get_recent_signals(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent_signals[-100:])

    def get_screening_hits(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._screening_hits[-100:])

    def _on_tick(self, tick: MarketTick, idx: IndexData) -> None:
        with self._lock:
            if self._engine_status == "starting":
                self._engine_status = "running"
            self._tick_count += 1
            self._last_time_str = tick.match_time_str
            self._last_prices[tick.symbol] = tick.match.price
            self._last_indices[tick.symbol] = {
                "vwap": idx.vwap,
                "day_high": idx.day_high,
                "day_low": idx.day_low,
            }

    def _on_screening(self, symbol: str, match_type: str, qualified: bool) -> None:
        with self._lock:
            self._screening_hits.append({
                "symbol": symbol,
                "match_type": match_type,
                "qualified": qualified,
                "time_str": self._last_time_str,
            })
            # Keep bounded
            if len(self._screening_hits) > 500:
                self._screening_hits = self._screening_hits[-200:]

    def _on_signal(self, symbol: str, signal_type: str, triggered: bool) -> None:
        with self._lock:
            self._recent_signals.append({
                "symbol": symbol,
                "signal_type": signal_type,
                "triggered": triggered,
                "time_str": self._last_time_str,
            })
            if len(self._recent_signals) > 500:
                self._recent_signals = self._recent_signals[-200:]

    def _on_entry(self, symbol: str, trade: EntryTrade) -> None:
        with self._lock:
            self._active_entries[symbol] = {
                "symbol": symbol,
                "side": trade.side,
                "signal_type": trade.signal_type,
                "enter_cause": trade.enter_cause,
                "entry_time_raw": trade.entry_time_raw,
                "entry_price": trade.entry_price,
                "entry_vwap": trade.entry_vwap,
                "group_name": trade.group_name,
                "entry_qty": trade.entry_qty,
            }

    def _on_exit(self, symbol: str, cause: str, record: TradeRecord) -> None:
        with self._lock:
            self._active_entries.pop(symbol, None)
            self._completed_trades.append({
                "symbol": record.symbol,
                "side": record.side,
                "signal_type": record.signal_type,
                "pnl": record.pnl,
                "return_pct": record.return_pct,
                "leave_cause": cause,
                "entry_time_raw": record.entry_time_raw,
                "exit_time_raw": record.exit_time_raw,
            })

    def mark_engine_running(self) -> None:
        with self._lock:
            if self._engine_status == "starting":
                self._engine_status = "running"

    def mark_engine_stopped(self) -> None:
        with self._lock:
            if self._engine_status != "fatal":
                self._engine_status = "stopped"

    def set_fatal_error(self, message: str, traceback_text: str) -> None:
        with self._lock:
            self._engine_status = "fatal"
            self._fatal_error = message
            self._fatal_traceback = traceback_text

    # ── Dashboard snapshot methods ───────────────────────────────────

    def update_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Called from on_minute hook with the latest snapshot."""
        with self._lock:
            self._dashboard_snapshot = snapshot

    def get_dashboard_groups(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(g) for g in self._dashboard_snapshot.groups]

    def get_dashboard_singles(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(s) for s in self._dashboard_snapshot.singles]

    def get_dashboard_vwap(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(v) for v in self._dashboard_snapshot.vwap_monitor]

    def get_dashboard_signal_a(self) -> dict[str, Any]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return asdict(SignalAMonitorSnapshot())
            return asdict(self._dashboard_snapshot.signal_a)

    def get_dashboard_snapshot_dict(self) -> dict[str, Any] | None:
        with self._lock:
            if self._dashboard_snapshot is None:
                return None
            return self._dashboard_snapshot.to_dict()
