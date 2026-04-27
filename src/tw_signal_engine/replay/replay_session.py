"""Top-level replay session: the main event loop."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config
from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig, SignalAShortConfig, TradeMode
from tw_signal_engine.execution.create_entry_trade import (
    EntryFilterEvaluation,
    evaluate_entry_filters,
    execute_entry,
    should_enter,
)
from tw_signal_engine.execution.signal_policy import describe_day_high_exit_policy, policy_for_signal
from tw_signal_engine.execution.trade_ledger import on_tick_exit
from tw_signal_engine.market_data.day_bar_loader import load_0050_open
from tw_signal_engine.market_data.file_replay_provider import FileReplayProvider
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.load_history_window import load_history_window
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker, NumTracker
from tw_signal_engine.market_data.parquet_history_loader import load_parquet_history_window
from tw_signal_engine.market_data.parquet_io import to_int_price
from tw_signal_engine.market_data.parquet_replay_provider import ParquetReplayProvider
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.market_data.proxy_0050_sidecar import (
    default_sidecar_root,
    load_0050_sidecar,
    sidecar_path,
)
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.records.overnight_records import OvernightHolding
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.reference_data.derive_prev_day_limit_up import derive_prev_day_limit_up
from tw_signal_engine.reference_data.load_group_membership import load_group_membership
from tw_signal_engine.reference_data.load_symbol_reference import load_symbol_reference
from tw_signal_engine.replay.apply_market_gate import MarketGate
from tw_signal_engine.replay.build_replay_universe import (
    build_replay_universe,
    extract_valid_group_symbols,
)
from tw_signal_engine.replay.iterate_market_file import iterate_market_file
from tw_signal_engine.replay.session_hooks import ScreeningDetail, SessionHooks
from tw_signal_engine.reporting.build_category_summary import write_category_report
from tw_signal_engine.reporting.build_daily_summary import write_summary_report
from tw_signal_engine.reporting.build_trade_report_rows import write_trade_report
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker
from tw_signal_engine.reporting.snapshot_writer import SignalSnapshotWriter, SnapshotWriter
from tw_signal_engine.reporting.write_order_log_csv import OrderLogWriter
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator
from tw_signal_engine.server.dashboard_snapshot import (
    ActivePosition,
    CompletedTrade,
    DashboardModuleStatus,
    DashboardSnapshot,
    PreparingEntry,
    SignalAMonitorSnapshot,
    SignalBMonitorEntry,
    SignalBMonitorSnapshot,
    SignalCounters,
    SignalDayHighEntryRow,
    SignalDayHighExitRow,
    SignalDayHighLogicFunnel,
    SignalDayHighLogicSnapshot,
    SignalDayHighMonitorEntry,
    SignalDayHighMonitorSnapshot,
    SignalDayHighPhase,
    SignalDayHighPhaseCounts,
    SignalDayHighSelectionRow,
    VWAPMonitorEntry,
)
from tw_signal_engine.signals.evaluate_signal_a import evaluate_signal_a
from tw_signal_engine.signals.evaluate_signal_a_short import evaluate_signal_a_short
from tw_signal_engine.signals.evaluate_signal_b import evaluate_signal_b
from tw_signal_engine.signals.evaluate_signal_day_high import evaluate_signal_day_high
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalAState, SignalBState, SignalDayHighState
from tw_signal_engine.state.symbol_state import IndexCalc, IndexData

SIGNAL_B_SHORT_MODE_WARNING = (
    "[WARN] SignalB is long-only and disabled in Strategy.trade_mode=short compatibility mode."
)
DAYHIGH_OVERNIGHT_MAP_WARNING = (
    "[WARN] Order.hold_overnight_on_limit_up=true but no overnight_holdings mapping was provided; "
    "locked-limit-up DayHigh positions will still force-close in standalone replay."
)


class _LeaveLogWriter(Protocol):
    def write_leave(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        cause: str,
        side: str,
        remaining_qty: float,
    ) -> None: ...


class _OrderLogWriterLike(_LeaveLogWriter, Protocol):
    def write_entry(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        signal_type: str,
        cause: str,
        side: str,
        remaining_qty: float,
        group_info: str,
    ) -> None: ...

    def close(self) -> None: ...


class _NullOrderLogWriter:
    """No-op order-log writer for diagnostic runs."""

    def write_entry(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        signal_type: str,
        cause: str,
        side: str,
        remaining_qty: float,
        group_info: str,
    ) -> None:
        return None

    def write_leave(
        self,
        symbol: str,
        time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        cause: str,
        side: str,
        remaining_qty: float,
    ) -> None:
        return None

    def close(self) -> None:
        return None


def _compute_log_dir(date: str, log_folder: str = "") -> str:
    if log_folder:
        return f"./log/{log_folder}/{date}/"
    now = datetime.now()
    return f"./log/{date}_{now.strftime('%H%M')}/"


def _symbols_file_missing(files_dir: str, trade_date: str) -> bool:
    symbols_path = Path(files_dir) / f"Symbols_{trade_date}.csv"
    return not symbols_path.exists()


def _find_0050_proxy_text_dir(trade_date: str, data_dir: str) -> str | None:
    """Find a legacy text replay root containing ``TSEQuote.<trade_date>``."""
    env_text_root = os.environ.get("TW_SIGNAL_DATA_DIR")
    candidate_roots = [
        Path(data_dir),
        Path(data_dir).parent / "tick-data",
        Path(env_text_root) if env_text_root else None,
        Path(__file__).resolve().parents[3] / "exec" / "data",
    ]
    seen: set[Path] = set()
    for root in candidate_roots:
        if root is None:
            continue
        if root in seen:
            continue
        seen.add(root)
        if (root / f"TSEQuote.{trade_date}").exists():
            return str(root)
    return None


def _finalize_open_positions(
    config: NormalizedStrategyConfig,
    pos: PositionState,
    last_price: dict[str, int],
    entry_signal_type: dict[str, str],
    entry_idx_map: dict[str, IndexData],
    completed_trades: list[TradeRecord],
    log_writer: _LeaveLogWriter,
    last_match_time_str: int,
    trade_date: str = "",
    hooks: SessionHooks | None = None,
    signal_snapshot_writer: SignalSnapshotWriter | None = None,
) -> None:
    dummy_tick = MarketTick()
    dummy_tick.match_time_str = last_match_time_str
    for symbol, qty in list(pos.stocks.items()):
        if abs(qty) <= 0.001:
            continue
        lp = last_price.get(symbol, 0)
        dummy_tick.symbol = symbol
        dummy_tick.match.price = lp
        dummy_tick.bid[0].price = lp
        dummy_tick.ask[0].price = lp
        sig_type = entry_signal_type.get(symbol, "")
        eidx = entry_idx_map.get(symbol, IndexData())
        entry = pos.open_trades.get(symbol)
        side = entry.side if entry is not None else "long"
        cause = on_tick_exit(
            config.execution, symbol, lp, lp,
            lp,
            dummy_tick.match_time_str, sig_type, eidx, pos, completed_trades,
            trade_date=trade_date,
        )
        if cause:
            log_writer.write_leave(
                symbol, dummy_tick.match_time_str, lp,
                pos.cash, pos.symbol_cash.get(symbol, 0), cause, side,
                pos.stocks.get(symbol, 0),
            )
            if hooks is not None and hooks.on_exit is not None and completed_trades:
                hooks.on_exit(symbol, cause, completed_trades[-1])
            if signal_snapshot_writer is not None and completed_trades:
                signal_snapshot_writer.on_exit(symbol, cause, completed_trades[-1])


def _merge_history_windows(otc: HistoryWindow, tse: HistoryWindow) -> HistoryWindow:
    """Merge OTC and TSE history windows into a single combined window.

    Both windows should have the same number of slots and corresponding dates.
    Creates new objects — never mutates the input windows (important for rolling reuse).
    """
    num_slots = max(len(otc.vol_cum), len(tse.vol_cum))
    merged_vol: list[LinearVolumeTracker] = []
    merged_tv: list[dict[str, int]] = []

    for i in range(num_slots):
        merged_tracker = LinearVolumeTracker()

        if i < len(otc.vol_cum):
            for sym, nodes in otc.vol_cum[i].data_store.items():
                merged_tracker.data_store[sym] = list(nodes)

        if i < len(tse.vol_cum):
            for sym, nodes in tse.vol_cum[i].data_store.items():
                if sym not in merged_tracker.data_store:
                    merged_tracker.data_store[sym] = list(nodes)
                else:
                    merged_tracker.data_store[sym].extend(nodes)

        merged_vol.append(merged_tracker)

        tv_merged: dict[str, int] = {}
        if i < len(otc.trading_val):
            tv_merged.update(otc.trading_val[i])
        if i < len(tse.trading_val):
            for sym, val in tse.trading_val[i].items():
                tv_merged[sym] = tv_merged.get(sym, 0) + val
        merged_tv.append(tv_merged)

    return HistoryWindow(
        vol_cum=merged_vol,
        trading_val=merged_tv,
        source_dates=otc.source_dates,
    )


def _parse_cost_model(cost_str: str) -> dict[str, float]:
    """Parse 'commission=0.001425,tax=0.0015' into dict."""
    result: dict[str, float] = {}
    if not cost_str:
        return result
    for part in cost_str.split(","):
        if "=" in part:
            key, val = part.split("=", 1)
            result[key.strip()] = float(val.strip())
    return result


def _apply_limit_up_lock_flag(tick: MarketTick, ref: ReferenceSymbol | None) -> None:
    """Set lock status using limit-up price plus depth-side queue evidence."""
    tick.is_limit_up_locked = False
    if ref is None:
        return
    limit_up = int(ref.limit_up_price * 10000 + 0.5)
    if limit_up <= 0:
        return
    has_no_ask_queue = tick.ask[0].price <= 0
    has_bid_queue = tick.bid[0].price > 0 or tick.total_bid_qty > 0
    tick.is_limit_up_locked = tick.match.price >= limit_up and has_no_ask_queue and has_bid_queue


def _format_match_time(match_time_str: int) -> str:
    raw = match_time_str // 1_000_000
    sec = raw % 100
    raw //= 100
    minute = raw % 100
    hour = raw // 100
    return f"{hour:02d}:{minute:02d}:{sec:02d}"


def _minute_bucket(match_time_str: int) -> int:
    """Convert raw match_time_str to HHMM minute bucket."""
    return match_time_str // 100_000_000


def _build_primary_group_map(symbol_to_groups: dict[str, list[str]]) -> dict[str, str]:
    primary_map: dict[str, str] = {}
    for symbol, groups in symbol_to_groups.items():
        if groups:
            primary_map[symbol] = groups[0]
    return primary_map


def _legacy_signal_a_short_config(config: NormalizedStrategyConfig) -> SignalAShortConfig:
    """Map legacy short-mode SignalA knobs to SignalAShortConfig."""
    return SignalAShortConfig(
        enabled=config.signal_a.enabled,
        vwap_near_ratio=config.signal_a.short_vwap_near_ratio,
        bounce_ratio=config.signal_a.bounce_ratio,
        entry_start_time=config.signal_a.entry_start_time,
        entry_end_time=config.signal_a.entry_end_time,
        pre_condition_start_time=config.signal_a.pre_condition_start_time,
        pre_condition_vwap_ratio=config.signal_a.short_pre_condition_vwap_ratio,
        trade_zone_max_increase_ratio=config.signal_a.trade_zone_max_increase_ratio,
        max_near_to_entry_us=config.signal_a.max_near_to_entry_us,
    )


def _phase_for_day_high_state(state: SignalDayHighState) -> SignalDayHighPhase:
    if state.triggered:
        return "triggered"
    if state.pullback_confirmed:
        return "pullback"
    if state.established_high > 0:
        return "tracking"
    return "exited"


def _is_day_high_product_spec_match(
    strong_group: StrongGroupEvaluator,
    symbol: str,
    config: NormalizedStrategyConfig,
) -> bool:
    """DayHigh may only consider the current strong-group M1/R1 candidate."""
    match_info = strong_group.last_match_info.get(symbol)
    if match_info is None or not match_info.group_name:
        return False
    group_valid_top_n = config.strong_group.group_valid_top_n or 10
    return (
        1 <= match_info.group_rank <= group_valid_top_n
        and match_info.member_rank == 1
        and match_info.raw_member_rank == 1
    )


def _default_entry_filter_evaluation() -> EntryFilterEvaluation:
    return EntryFilterEvaluation(
        allowed=True,
        block_reason=None,
        entry_time_limit=True,
        prev_day_limit_up=True,
        no_entry_friday=True,
        max_0050_entry_chg=True,
        max_0050_intra_chg=True,
        volatility_pause=True,
        already_holding=True,
        single_forbidden=True,
        max_entry_price=True,
    )


def _build_dashboard_snapshot(
    config: NormalizedStrategyConfig,
    match_time_str: int,
    tick_count: int,
    strong_group: StrongGroupEvaluator,
    strong_single: StrongSingleEvaluator,
    symbol_to_groups: dict[str, list[str]],
    f1_map: Mapping[str, object],
    latest_idx_map: dict[str, IndexData],
    last_price: dict[str, int],
    signal_a_map: dict[str, SignalAState],
    signal_a_short_map: dict[str, SignalAState],
    signal_b_map: dict[str, SignalBState],
    signal_day_high_map: dict[str, SignalDayHighState],
    day_high_entry_logic: dict[str, SignalDayHighEntryRow],
    day_high_limit_up_locked: dict[str, bool],
    pos: PositionState,
    completed_trades: list[TradeRecord],
    trade_mode: str,
) -> DashboardSnapshot:
    symbol_to_group = _build_primary_group_map(symbol_to_groups)

    vwap_rows: list[VWAPMonitorEntry] = []
    for symbol in sorted(latest_idx_map.keys()):
        idx = latest_idx_map[symbol]
        price_raw = last_price.get(symbol, 0)
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        match_info = strong_group.last_match_info.get(symbol)
        group_name = match_info.group_name if match_info is not None else symbol_to_group.get(symbol, "")
        state = signal_a_map.get(symbol)
        short_state = signal_a_short_map.get(symbol)
        signal_state = "idle"
        if state is not None:
            if state.triggered:
                signal_state = "triggered"
            elif state.near_vwap:
                signal_state = "near_vwap"
            elif state.forbidden:
                signal_state = "forbidden"
        elif short_state is not None:
            if short_state.triggered:
                signal_state = "triggered_short"
            elif short_state.near_vwap:
                signal_state = "near_vwap_short"
            elif short_state.forbidden:
                signal_state = "forbidden_short"
        status = "holding" if abs(pos.stocks.get(symbol, 0)) > 0.001 else ""
        vwap = idx.vwap
        vwap_rows.append(
            VWAPMonitorEntry(
                symbol=symbol,
                name=name,
                group_name=group_name,
                price=price_raw / 10000,
                vwap=vwap / 10000,
                vwap_pct=((price_raw - vwap) / vwap if vwap > 0 else 0.0),
                pv_ratio=(price_raw / vwap if vwap > 0 else 0.0),
                signal_a_state=signal_state,
                status=status,
            )
        )

    preparing: list[PreparingEntry] = []
    for symbol, state in signal_a_map.items():
        if not state.near_vwap or state.triggered or abs(pos.stocks.get(symbol, 0)) > 0.001:
            continue
        idx_for_symbol = latest_idx_map.get(symbol)
        if idx_for_symbol is None:
            continue
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        group_name = symbol_to_group.get(symbol, "")
        price_raw = last_price.get(symbol, 0)
        preparing.append(
            PreparingEntry(
                symbol=symbol,
                name=name,
                group_name=group_name,
                group_tag=group_name,
                order_price=price_raw / 10000,
                current_price=price_raw / 10000,
                distance_pct=(
                    (price_raw - idx_for_symbol.vwap) / idx_for_symbol.vwap
                    if idx_for_symbol.vwap > 0
                    else 0.0
                ),
                vwap=idx_for_symbol.vwap / 10000,
                day_low=idx_for_symbol.day_low / 10000 if idx_for_symbol.day_low > 0 else 0.0,
                near_vwap_pv_ratio=state.near_vwap_pv_ratio,
                side=trade_mode,
            )
        )
    for symbol, state in signal_a_short_map.items():
        if not state.near_vwap or state.triggered or abs(pos.stocks.get(symbol, 0)) > 0.001:
            continue
        idx_for_symbol = latest_idx_map.get(symbol)
        if idx_for_symbol is None:
            continue
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        group_name = symbol_to_group.get(symbol, "")
        price_raw = last_price.get(symbol, 0)
        preparing.append(
            PreparingEntry(
                symbol=symbol,
                name=name,
                group_name=group_name,
                group_tag=group_name,
                order_price=price_raw / 10000,
                current_price=price_raw / 10000,
                distance_pct=(
                    (price_raw - idx_for_symbol.vwap) / idx_for_symbol.vwap
                    if idx_for_symbol.vwap > 0
                    else 0.0
                ),
                vwap=idx_for_symbol.vwap / 10000,
                day_low=idx_for_symbol.day_low / 10000 if idx_for_symbol.day_low > 0 else 0.0,
                near_vwap_pv_ratio=state.near_vwap_pv_ratio,
                side="short",
            )
        )

    entered: list[ActivePosition] = []
    for symbol, entry in pos.open_trades.items():
        if entry.signal_type not in {"SignalA", "SignalAShort"}:
            continue
        price_raw = last_price.get(symbol, 0)
        if entry.entry_price > 0:
            if entry.side == "short":
                pnl_pct = (entry.entry_price - price_raw / 10000) / entry.entry_price
            else:
                pnl_pct = (price_raw / 10000 - entry.entry_price) / entry.entry_price
        else:
            pnl_pct = 0.0
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        entered.append(
            ActivePosition(
                symbol=symbol,
                name=name,
                group_name=entry.group_name,
                group_tag=entry.group_name,
                entry_price=entry.entry_price,
                current_price=price_raw / 10000,
                pnl_pct=pnl_pct,
                side=entry.side,
                qty=pos.stocks.get(symbol, 0),
                day_high=entry.day_high_at_entry,
                entry_time=str(entry.entry_time_raw),
            )
        )

    exited: list[CompletedTrade] = []
    for trade in completed_trades[-200:]:
        if trade.signal_type not in {"SignalA", "SignalAShort"}:
            continue
        ref = f1_map.get(trade.symbol)
        name = getattr(ref, "name", trade.symbol)
        exited.append(
            CompletedTrade(
                symbol=trade.symbol,
                name=name,
                group_name=trade.group_name,
                group_tag=trade.group_name,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                pnl_pct=trade.return_pct / 100.0,
                entry_time=str(trade.entry_time_raw),
                exit_time=str(trade.exit_time_raw),
                exit_cause=trade.final_leave_cause,
                side=trade.side,
            )
        )

    take_profit = sum(1 for trade in completed_trades if trade.final_leave_cause == "takeProfit")
    stop_loss = sum(1 for trade in completed_trades if trade.final_leave_cause == "stopLoss")
    forbidden = sum(1 for state in signal_a_map.values() if state.forbidden) + sum(
        1 for state in signal_a_short_map.values() if state.forbidden
    )
    counters = SignalCounters(
        qualified=sum(1 for state in signal_a_map.values() if state.near_vwap or state.triggered)
        + sum(1 for state in signal_a_short_map.values() if state.near_vwap or state.triggered),
        not_qualified=0,
        holding=sum(1 for entry in pos.open_trades.values() if entry.signal_type in {"SignalA", "SignalAShort"}),
        take_profit=take_profit,
        stop_loss=stop_loss,
        forbidden=forbidden,
    )
    signal_a_snapshot = SignalAMonitorSnapshot(
        preparing=preparing,
        entered=entered,
        exited=exited,
        counters=counters,
    )

    signal_b_rows: list[SignalBMonitorEntry] = []
    signal_b_symbols: set[str] = set()
    for symbol, signal_b_state in signal_b_map.items():
        if not (
            signal_b_state.forbidden
            or signal_b_state.in_buffer_zone
            or signal_b_state.in_trade_zone
            or signal_b_state.enter_market
        ):
            continue
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        group_name = symbol_to_group.get(symbol, "")
        status = (
            "triggered"
            if signal_b_state.enter_market
            else "trade_zone"
            if signal_b_state.in_trade_zone
            else "buffer_zone"
            if signal_b_state.in_buffer_zone
            else "forbidden"
        )
        signal_b_rows.append(
            SignalBMonitorEntry(
                symbol=symbol,
                name=name,
                group_name=group_name,
                forbidden=signal_b_state.forbidden,
                in_buffer_zone=signal_b_state.in_buffer_zone,
                in_trade_zone=signal_b_state.in_trade_zone,
                enter_market=signal_b_state.enter_market,
                rolling_low=signal_b_state.rolling_low_val / 10000
                if signal_b_state.rolling_low_val > 0
                else 0.0,
                rolling_sum_ratio=signal_b_state.rolling_sum_ratio,
                status=status,
            )
        )
        signal_b_symbols.add(symbol)
    for symbol, entry in pos.open_trades.items():
        if entry.signal_type != "SignalB" or symbol in signal_b_symbols:
            continue
        signal_b_open_state: SignalBState | None = signal_b_map.get(symbol)
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        signal_b_rows.append(
            SignalBMonitorEntry(
                symbol=symbol,
                name=name,
                group_name=entry.group_name,
                enter_market=True,
                rolling_low=(
                    signal_b_open_state.rolling_low_val / 10000
                    if signal_b_open_state and signal_b_open_state.rolling_low_val > 0
                    else 0.0
                ),
                rolling_sum_ratio=(signal_b_open_state.rolling_sum_ratio if signal_b_open_state else 0.0),
                status="holding",
            )
        )
    signal_b_snapshot = SignalBMonitorSnapshot(
        rows=signal_b_rows,
        buffer_zone=sum(1 for row in signal_b_rows if row.in_buffer_zone),
        trade_zone=sum(1 for row in signal_b_rows if row.in_trade_zone),
        triggered=sum(1 for row in signal_b_rows if row.enter_market),
        forbidden=sum(1 for row in signal_b_rows if row.forbidden),
    )

    day_high_rows: list[SignalDayHighMonitorEntry] = []
    day_high_symbols: set[str] = set()
    day_high_open_symbols: set[str] = {
        symbol for symbol, entry in pos.open_trades.items() if entry.signal_type == "SignalDayHigh"
    }
    day_high_preparing: list[PreparingEntry] = []

    def _fmt_price(raw: int) -> float:
        return raw / 10000 if raw > 0 else 0.0

    def _fmt_time(raw: int) -> str:
        return str(raw) if raw > 0 else ""

    def _is_current_day_high_selection(symbol: str) -> bool:
        explain_fn = getattr(strong_group, "explain_day_high_selection", None)
        if callable(explain_fn):
            return bool(
                explain_fn(
                    symbol=symbol,
                    idx=latest_idx_map.get(symbol),
                    price_raw=last_price.get(symbol, 0),
                ).selected
            )
        return _is_day_high_product_spec_match(strong_group, symbol, config)

    for symbol, day_high_state in signal_day_high_map.items():
        if symbol in day_high_open_symbols:
            continue
        if not _is_current_day_high_selection(symbol):
            continue
        if not (day_high_state.established_high > 0 or day_high_state.triggered or day_high_state.entries > 0):
            continue
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        group_name = symbol_to_group.get(symbol, "")
        phase = _phase_for_day_high_state(day_high_state)
        day_high_rows.append(
            SignalDayHighMonitorEntry(
                symbol=symbol,
                name=name,
                group_name=group_name,
                triggered=day_high_state.triggered,
                established_high=_fmt_price(day_high_state.established_high),
                established_high_time=_fmt_time(day_high_state.established_high_time),
                pullback_confirmed=day_high_state.pullback_confirmed,
                pullback_low=_fmt_price(day_high_state.pullback_low),
                pullback_time=_fmt_time(day_high_state.pullback_time),
                last_trigger_high=_fmt_price(day_high_state.last_trigger_high),
                last_trigger_high_time=_fmt_time(day_high_state.last_trigger_high_time),
                last_trigger_pullback_low=_fmt_price(day_high_state.last_trigger_pullback_low),
                last_trigger_pullback_time=_fmt_time(day_high_state.last_trigger_pullback_time),
                trigger_time=_fmt_time(day_high_state.last_trigger_time),
                phase=phase,
                entries=day_high_state.entries,
                status=phase,
            )
        )
        day_high_symbols.add(symbol)

        if phase in {"pullback", "triggered"}:
            idx_for_symbol = latest_idx_map.get(symbol)
            if idx_for_symbol is not None:
                price_raw = last_price.get(symbol, 0)
                current_price = price_raw / 10000
                established_high = (
                    _fmt_price(day_high_state.established_high)
                    if day_high_state.established_high > 0
                    else current_price
                )
                day_high_preparing.append(
                    PreparingEntry(
                        symbol=symbol,
                        name=name,
                        group_name=group_name,
                        group_tag=group_name,
                        order_price=established_high,
                        current_price=current_price,
                        distance_pct=(
                            (current_price - established_high) / established_high
                            if established_high > 0
                            else 0.0
                        ),
                        vwap=idx_for_symbol.vwap / 10000,
                        day_low=idx_for_symbol.day_low / 10000 if idx_for_symbol.day_low > 0 else 0.0,
                        stop_loss=describe_day_high_exit_policy(
                            config.execution,
                            entry_vwap=idx_for_symbol.vwap / 10000,
                        ).stop_price,
                        near_vwap_pv_ratio=0.0,
                        side="long",
                    )
                )

    day_high_entered: list[ActivePosition] = []
    for symbol, entry in pos.open_trades.items():
        if entry.signal_type != "SignalDayHigh":
            continue
        price_raw = last_price.get(symbol, 0)
        if entry.entry_price > 0:
            if entry.side == "short":
                pnl_pct = (entry.entry_price - price_raw / 10000) / entry.entry_price
            else:
                pnl_pct = (price_raw / 10000 - entry.entry_price) / entry.entry_price
        else:
            pnl_pct = 0.0
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        day_high_policy = describe_day_high_exit_policy(
            config.execution,
            entry_vwap=entry.entry_vwap,
            currently_limit_up_locked=day_high_limit_up_locked.get(symbol, False),
            current_match_time_str=match_time_str,
        )
        day_high_entered.append(
            ActivePosition(
                symbol=symbol,
                name=name,
                group_name=entry.group_name,
                group_tag=entry.group_name,
                entry_price=entry.entry_price,
                current_price=price_raw / 10000,
                pnl_pct=pnl_pct,
                stop_loss=day_high_policy.stop_price,
                take_profit=0.0,
                day_high=entry.day_high_at_entry,
                entry_time=str(entry.entry_time_raw),
                side=entry.side,
                qty=pos.stocks.get(symbol, 0),
            )
        )

    day_high_exited: list[CompletedTrade] = []
    for trade in completed_trades[-200:]:
        if trade.signal_type != "SignalDayHigh":
            continue
        ref = f1_map.get(trade.symbol)
        name = getattr(ref, "name", trade.symbol)
        day_high_exited.append(
            CompletedTrade(
                symbol=trade.symbol,
                name=name,
                group_name=trade.group_name,
                group_tag=trade.group_name,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                pnl_pct=trade.return_pct / 100.0,
                entry_time=str(trade.entry_time_raw),
                exit_time=str(trade.exit_time_raw),
                exit_cause=trade.final_leave_cause,
                side=trade.side,
            )
        )

    day_high_counters = SignalCounters(
        qualified=len(day_high_preparing),
        not_qualified=0,
        holding=len(day_high_entered),
        take_profit=sum(1 for trade in day_high_exited if trade.exit_cause == "takeProfit"),
        stop_loss=sum(1 for trade in day_high_exited if trade.exit_cause == "stopLoss"),
        forbidden=0,
    )

    for symbol, entry in pos.open_trades.items():
        if entry.signal_type != "SignalDayHigh":
            continue
        day_high_open_state: SignalDayHighState | None = signal_day_high_map.get(symbol)
        if not day_high_open_state:
            if symbol in day_high_symbols:
                continue
            established_high = entry.day_high_at_entry
            pullback_low = 0.0
            pullback_time = ""
            trigger_time = _fmt_time(entry.entry_time_raw)
            last_trigger_high = entry.day_high_at_entry
            last_trigger_high_time = _fmt_time(entry.entry_time_raw)
            last_pullback_low = 0.0
            last_pullback_time = ""
        else:
            established_high = _fmt_price(
                day_high_open_state.last_trigger_high
                if day_high_open_state.last_trigger_high > 0
                else int(entry.day_high_at_entry * 10000)
            )
            pullback_low = _fmt_price(day_high_open_state.last_trigger_pullback_low)
            pullback_time = _fmt_time(day_high_open_state.last_trigger_pullback_time)
            trigger_time = _fmt_time(day_high_open_state.last_trigger_time)
            last_trigger_high = _fmt_price(day_high_open_state.last_trigger_high)
            last_trigger_high_time = _fmt_time(day_high_open_state.last_trigger_high_time)
            last_pullback_low = _fmt_price(day_high_open_state.last_trigger_pullback_low)
            last_pullback_time = _fmt_time(day_high_open_state.last_trigger_pullback_time)

        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        day_high_rows.append(
            SignalDayHighMonitorEntry(
                symbol=symbol,
                name=name,
                group_name=entry.group_name,
                triggered=True,
                established_high=established_high,
                established_high_time=last_trigger_high_time,
                pullback_confirmed=True,
                pullback_low=pullback_low,
                pullback_time=pullback_time,
                last_trigger_high=last_trigger_high,
                last_trigger_high_time=last_trigger_high_time,
                last_trigger_pullback_low=last_pullback_low,
                last_trigger_pullback_time=last_pullback_time,
                trigger_time=trigger_time,
                phase="holding",
                entries=(day_high_open_state.entries if day_high_open_state else 1),
                status="holding",
            )
        )
        day_high_symbols.add(symbol)

    phase_counts = {
        "tracking": sum(1 for row in day_high_rows if row.phase == "tracking"),
        "pullback": sum(1 for row in day_high_rows if row.phase == "pullback"),
        "triggered": sum(1 for row in day_high_rows if row.phase == "triggered"),
        "holding": sum(1 for row in day_high_rows if row.phase == "holding"),
        "exited": sum(1 for row in day_high_rows if row.phase == "exited"),
    }

    day_high_relevant_symbols: set[str] = {
        symbol for symbol in signal_day_high_map if _is_current_day_high_selection(symbol)
    }
    day_high_relevant_symbols |= {
        symbol
        for symbol, entry in pos.open_trades.items()
        if entry.signal_type == "SignalDayHigh"
    }
    day_high_relevant_symbols |= {
        trade.symbol
        for trade in completed_trades[-200:]
        if trade.signal_type == "SignalDayHigh"
    }
    day_high_relevant_symbols |= set(day_high_entry_logic.keys())
    day_high_group_valid_top_n = config.strong_group.group_valid_top_n or 10
    day_high_relevant_symbols |= {
        symbol
        for symbol, info in strong_group.last_match_info.items()
        if (
            info.group_name
            and 1 <= info.group_rank <= day_high_group_valid_top_n
            and info.member_rank == 1
            and info.raw_member_rank == 1
        )
    }

    selection_rows: list[SignalDayHighSelectionRow] = []
    for symbol in sorted(day_high_relevant_symbols):
        idx_for_symbol = latest_idx_map.get(symbol)
        price_raw = last_price.get(symbol, 0)
        if (
            idx_for_symbol is None
            and price_raw <= 0
            and symbol not in strong_group.last_match_info
            and symbol not in pos.open_trades
        ):
            continue
        explain_fn = getattr(strong_group, "explain_day_high_selection", None)
        if callable(explain_fn):
            selection_rows.append(
                explain_fn(
                    symbol=symbol,
                    idx=idx_for_symbol,
                    price_raw=price_raw,
                )
            )
        else:
            info = strong_group.last_match_info.get(symbol)
            name = getattr(f1_map.get(symbol), "name", symbol)
            selection_rows.append(
                SignalDayHighSelectionRow(
                    symbol=symbol,
                    name=name,
                    group_name=info.group_name if info is not None else symbol_to_group.get(symbol, ""),
                    selected=(info.member_rank == 1 if info is not None else False),
                    group_rank=info.group_rank if info is not None else 0,
                    member_rank=info.member_rank if info is not None else 0,
                    raw_member_rank=info.raw_member_rank if info is not None else 0,
                    m1_symbol=info.m1_symbol if info is not None else "",
                    current_price=price_raw / 10000 if price_raw > 0 else 0.0,
                    vwap=(
                        idx_for_symbol.vwap / 10000
                        if idx_for_symbol is not None and idx_for_symbol.vwap > 0
                        else 0.0
                    ),
                )
            )

    entry_rows_by_symbol: dict[str, SignalDayHighEntryRow] = dict(day_high_entry_logic)
    for row in day_high_rows:
        if row.phase not in {"pullback", "triggered", "holding"}:
            continue
        if row.symbol in entry_rows_by_symbol:
            continue
        group_name = row.group_name
        match_info = strong_group.last_match_info.get(row.symbol)
        if match_info is not None and match_info.group_name:
            group_name = match_info.group_name
        group_limit_up_count = strong_group.get_group_limit_up_count(group_name) if group_name else 0
        group_limit_up_passed = (
            group_limit_up_count < config.signal_day_high.max_group_limit_up_count
            if group_name
            else True
        )
        waiting_reason = ""
        if row.phase == "pullback":
            waiting_reason = "waiting_breakout"
        elif row.phase == "triggered" and not group_limit_up_passed:
            waiting_reason = "day_high_group_limit_up_count"
        elif row.phase == "triggered":
            waiting_reason = "pending_entry_filters"
        entry_rows_by_symbol[row.symbol] = SignalDayHighEntryRow(
            symbol=row.symbol,
            name=row.name,
            group_name=group_name,
            phase=row.phase,
            trigger_time=row.trigger_time,
            current_price=last_price.get(row.symbol, 0) / 10000,
            established_high=row.established_high,
            pullback_low=row.pullback_low,
            day_high_group_limit_up_count=group_limit_up_count,
            day_high_group_limit_up_limit=config.signal_day_high.max_group_limit_up_count,
            day_high_group_limit_up_passed=group_limit_up_passed,
            allowed=row.phase == "holding",
            entered=row.phase == "holding",
            block_reason=waiting_reason,
        )

    entry_rows: list[SignalDayHighEntryRow] = sorted(
        entry_rows_by_symbol.values(),
        key=lambda row: (row.symbol, row.trigger_time, row.phase),
    )

    exit_rows: list[SignalDayHighExitRow] = []
    for symbol, entry in pos.open_trades.items():
        if entry.signal_type != "SignalDayHigh":
            continue
        ref = f1_map.get(symbol)
        name = getattr(ref, "name", symbol)
        price_raw = last_price.get(symbol, 0)
        current_price = price_raw / 10000 if price_raw > 0 else 0.0
        if entry.entry_price > 0 and current_price > 0:
            pnl_pct = (current_price - entry.entry_price) / entry.entry_price
        else:
            pnl_pct = 0.0
        policy = describe_day_high_exit_policy(
            config.execution,
            entry_vwap=entry.entry_vwap,
            currently_limit_up_locked=day_high_limit_up_locked.get(symbol, False),
            current_match_time_str=match_time_str,
        )
        exit_rows.append(
            SignalDayHighExitRow(
                symbol=symbol,
                name=name,
                group_name=entry.group_name,
                status="open",
                entry_price=entry.entry_price,
                current_price=current_price,
                pnl_pct=pnl_pct,
                entry_time=str(entry.entry_time_raw),
                stop_basis=policy.stop_basis,
                stop_anchor=policy.stop_anchor,
                stop_price=policy.stop_price,
                time_exit_deadline=policy.time_exit_deadline,
                take_profit_enabled=policy.take_profit_enabled,
                bailout_enabled=policy.bailout_enabled,
                hold_overnight_on_limit_up=policy.hold_overnight_on_limit_up,
                currently_limit_up_locked=policy.currently_limit_up_locked,
                overnight_eligible_now=policy.overnight_eligible_now,
            )
        )
    for trade in completed_trades[-200:]:
        if trade.signal_type != "SignalDayHigh":
            continue
        ref = f1_map.get(trade.symbol)
        name = getattr(ref, "name", trade.symbol)
        policy = describe_day_high_exit_policy(
            config.execution,
            entry_vwap=trade.entry_vwap,
            currently_limit_up_locked=False,
        )
        exit_rows.append(
            SignalDayHighExitRow(
                symbol=trade.symbol,
                name=name,
                group_name=trade.group_name,
                status="closed",
                entry_price=trade.entry_price,
                current_price=trade.exit_price,
                pnl_pct=trade.return_pct / 100.0,
                entry_time=str(trade.entry_time_raw),
                exit_time=str(trade.exit_time_raw),
                stop_basis=policy.stop_basis,
                stop_anchor=policy.stop_anchor,
                stop_price=policy.stop_price,
                time_exit_deadline=policy.time_exit_deadline,
                take_profit_enabled=policy.take_profit_enabled,
                bailout_enabled=policy.bailout_enabled,
                hold_overnight_on_limit_up=policy.hold_overnight_on_limit_up,
                currently_limit_up_locked=False,
                overnight_eligible_now=False,
                final_leave_cause=trade.final_leave_cause,
            )
        )

    block_reasons: dict[str, int] = {}
    for entry_row in entry_rows:
        if entry_row.entered or entry_row.allowed:
            continue
        reason = entry_row.block_reason
        if reason in {"", "waiting_breakout", "pending_entry_filters"}:
            continue
        block_reasons[reason] = block_reasons.get(reason, 0) + 1

    day_high_logic = SignalDayHighLogicSnapshot(
        selection_rows=selection_rows,
        entry_rows=entry_rows,
        exit_rows=exit_rows,
        funnel=SignalDayHighLogicFunnel(
            selected=sum(1 for selection_row in selection_rows if selection_row.selected),
            armed=phase_counts["pullback"] + phase_counts["triggered"],
            blocked=sum(
                1
                for entry_row in entry_rows
                if (
                    not entry_row.allowed
                    and not entry_row.entered
                    and entry_row.block_reason not in {"", "waiting_breakout", "pending_entry_filters"}
                )
            ),
            entered=sum(1 for entry_row in entry_rows if entry_row.entered),
            holding=len(day_high_entered),
            exited=len(day_high_exited),
            block_reasons=block_reasons,
        ),
    )

    day_high_snapshot = SignalDayHighMonitorSnapshot(
        rows=day_high_rows,
        preparing=day_high_preparing,
        entered=day_high_entered,
        exited=day_high_exited,
        phase_counts=SignalDayHighPhaseCounts(**phase_counts),
        counters=day_high_counters,
        tracking=phase_counts["tracking"],
        pullback=phase_counts["pullback"],
        triggered=phase_counts["triggered"] + phase_counts["holding"],
        entries=sum(row.entries for row in day_high_rows),
        logic=day_high_logic,
    )

    modules = [
        DashboardModuleStatus(
            "strong-groups",
            "Strong Groups",
            "available",
            "",
            "StockScreening strong groups",
        ),
        DashboardModuleStatus(
            "burst-groups",
            "Burst Groups",
            "unavailable",
            "This engine has no burst-group evaluator.",
            "StockScreening burst groups",
        ),
        DashboardModuleStatus(
            "intraday-burst",
            "Intraday Burst Stocks",
            "unavailable",
            "This engine has no intraday burst-stock evaluator.",
            "StockScreening intraday burst stocks",
        ),
        DashboardModuleStatus(
            "strong-stocks",
            "Strong Stocks",
            "available",
            "",
            "StockScreening strong stocks",
        ),
        DashboardModuleStatus(
            "vwap-watchlist",
            "VWAP Watchlist",
            "available",
            "",
            "StockScreening VWAP watchlist",
        ),
        DashboardModuleStatus(
            "signal-a-family",
            "Signal A / SignalAShort",
            "available",
            "",
            "signal SignalA and SignalAShort",
        ),
        DashboardModuleStatus(
            "signal-b",
            "Signal B",
            "available",
            "",
            "signal SignalB",
        ),
        DashboardModuleStatus(
            "signal-c-summary",
            "Signal C Summary",
            "unavailable",
            "Signal C is not implemented in this engine.",
            "StockScreening Signal C",
        ),
        DashboardModuleStatus(
            "day-high-summary",
            "SignalDayHigh",
            "available",
            "",
            "signal SignalDayHigh",
        ),
    ]

    return DashboardSnapshot(
        timestamp=_format_match_time(match_time_str),
        time_raw=match_time_str,
        tick_count=tick_count,
        groups=strong_group.to_snapshot(latest_idx_map),
        singles=strong_single.to_snapshot(latest_idx_map, last_price, symbol_to_group=symbol_to_group),
        vwap_monitor=vwap_rows,
        signal_a=signal_a_snapshot,
        signal_b=signal_b_snapshot,
        signal_day_high=day_high_snapshot,
        modules=modules,
    )


def run_daily_replay(
    trade_date: str,
    config_path: str = "./cfg/parameter.cfg",
    data_dir: str = "./data/",
    files_dir: str = "./files/",
    group_file: str = "./files/group.csv",
    log_folder: str = "",
    history: HistoryWindow | None = None,
    use_cache: bool = True,
    no_charts: bool = False,
    write_snapshots: bool = False,
    snapshot_dir: str = "./cache/replay/",
    cost_model_override: str = "",
    provider: MarketDataProvider | None = None,
    hooks: SessionHooks | None = None,
    on_dashboard_snapshot: Callable[[DashboardSnapshot], None] | None = None,
    data_source: str = "text",
    write_outputs: bool = True,
    overnight_holdings: dict[str, OvernightHolding] | None = None,
) -> list[TradeRecord]:
    """Run a single-day replay and return completed trades.

    ``data_source`` selects the market-data ingestion path:
      * ``"text"``  — legacy ``TSEQuote/OTCQuote`` text files under ``data_dir``
      * ``"parquet"`` — new parquet root with ``TWSE/<date>.parquet`` and
        ``TPEX/<date>.parquet`` directories under ``data_dir``.

    If ``provider`` is supplied it always wins (the live path passes its own
    Redis provider). If ``history`` is supplied, history loading is skipped
    (used by batch mode).

    When ``write_outputs`` is False, the replay still computes screening/signal/
    execution behavior and returns completed trades, but it does not write order
    logs or end-of-day reports under ``log/``.
    """
    if data_source not in ("text", "parquet"):
        raise ValueError(f"data_source must be 'text' or 'parquet', got {data_source!r}")
    report_data_source = "provider" if provider is not None else data_source

    if data_source == "parquet" and _symbols_file_missing(files_dir, trade_date):
        print(
            f"[GUARD] Skipping {trade_date}: Symbols_{trade_date}.csv not found in {files_dir}"
        )
        return []

    t_start = time.time()

    # 1. Load config
    raw_cfg = load_legacy_ini(config_path)
    config = normalize_strategy_config(raw_cfg)

    # Apply cost model override if provided
    cost_params = _parse_cost_model(cost_model_override)
    if "commission" in cost_params:
        config.execution.commission_rate = cost_params["commission"]
    if "tax" in cost_params:
        prior_tax_rate = config.execution.tax_rate
        config.execution.tax_rate = cost_params["tax"]
        config.execution.day_trade_tax_rate = cost_params["tax"]
        if (
            config.execution.overnight_tax_rate <= 0
            or abs(config.execution.overnight_tax_rate - prior_tax_rate) < 1e-12
        ):
            config.execution.overnight_tax_rate = cost_params["tax"]
    if "slippage" in cost_params:
        config.execution.slippage_bps = cost_params["slippage"]
    compatibility_short_mode = config.strategy.trade_mode == "short"
    legacy_short_signal_a_enabled = compatibility_short_mode and config.signal_a.enabled
    signal_a_short_enabled = config.signal_a_short.enabled and not compatibility_short_mode
    legacy_short_signal_a_config = _legacy_signal_a_short_config(config)

    print(f"signalA_enabled: [{config.signal_a.enabled}]")
    print(f"signalAShort_enabled: [{config.signal_a_short.enabled}]")
    print(f"signalB_enabled: [{config.signal_b.enabled}]")
    print(f"signalDayHigh_enabled: [{config.signal_day_high.enabled}]")
    print(f"strongGroup_enabled: [{config.strong_group.enabled}]")
    print(f"strongSingle_enabled: [{config.strong_single.enabled}]")
    print(f"trade_mode: [{config.strategy.trade_mode}]")
    if (
        config.signal_day_high.enabled
        and config.execution.hold_overnight_on_limit_up
        and overnight_holdings is None
    ):
        print(DAYHIGH_OVERNIGHT_MAP_WARNING)

    # 2. Load reference data
    f1_map = load_symbol_reference(trade_date, files_dir)
    prev_day_lu = derive_prev_day_limit_up(trade_date, files_dir)
    _, symbol_to_groups, group_members = load_group_membership(group_file)

    # 3. Load history (or use pre-built)
    if history is None:
        if data_source == "parquet":
            t0 = time.time()
            hw_otc = load_parquet_history_window(
                "OTC",
                trade_date,
                data_dir,
                use_cache=use_cache,
                write_cache=use_cache,
            )
            print(f"[TIMING] getTickData OTC: {(time.time() - t0) * 1000:.0f} ms")

            t0 = time.time()
            hw_tse = load_parquet_history_window(
                "TSE",
                trade_date,
                data_dir,
                use_cache=use_cache,
                write_cache=use_cache,
            )
            print(f"[TIMING] getTickData TSE: {(time.time() - t0) * 1000:.0f} ms")
        else:
            t0 = time.time()
            hw_otc = load_history_window("OTC", trade_date, data_dir, use_cache=use_cache)
            print(f"[TIMING] getTickData OTC: {(time.time() - t0) * 1000:.0f} ms")

            t0 = time.time()
            hw_tse = load_history_window("TSE", trade_date, data_dir, use_cache=use_cache)
            print(f"[TIMING] getTickData TSE: {(time.time() - t0) * 1000:.0f} ms")

        history = _merge_history_windows(hw_otc, hw_tse)
    else:
        print("[TIMING] getTickData: using pre-built history")

    vol_cum = history.vol_cum
    trading_val = history.trading_val

    # 4. Initialize screening
    strong_group = StrongGroupEvaluator(
        config=config.strong_group,
        symbol_to_groups=symbol_to_groups,
        group_members=group_members,
        vol_cum=vol_cum,
        trading_val=trading_val,
        f1_map=f1_map,
        prev_day_limit_up=prev_day_lu,
        trade_mode=config.strategy.trade_mode,
    )
    t0 = time.time()
    strong_group.initialize_validity()
    print(f"[TIMING] getGroup: {(time.time() - t0) * 1000:.0f} ms")

    strong_group_short: StrongGroupEvaluator | None = None
    if signal_a_short_enabled and config.strong_group.enabled:
        strong_group_short = StrongGroupEvaluator(
            config=config.strong_group,
            symbol_to_groups=symbol_to_groups,
            group_members=group_members,
            vol_cum=vol_cum,
            trading_val=trading_val,
            f1_map=f1_map,
            prev_day_limit_up=prev_day_lu,
            trade_mode="short",
        )
        t0 = time.time()
        strong_group_short.initialize_validity()
        print(f"[TIMING] getGroupShort: {(time.time() - t0) * 1000:.0f} ms")

    strong_single = StrongSingleEvaluator(
        config=config.strong_single,
        vol_cum=vol_cum,
        trading_val=trading_val,
        f1_map=f1_map,
    )
    strong_single_enabled_for_entry = config.strong_single.enabled and not compatibility_short_mode
    strong_single_valid_symbols = strong_single.initialize_validity() if strong_single_enabled_for_entry else set()

    # 5. Build replay universe
    valid_group_symbols = extract_valid_group_symbols(strong_group.symbol_is_valid)
    if strong_group_short is not None:
        valid_group_symbols |= extract_valid_group_symbols(strong_group_short.symbol_is_valid)
    tick_filter = build_replay_universe(
        valid_group_symbols,
        single_valid_symbols=strong_single_valid_symbols,
    )
    if overnight_holdings:
        tick_filter |= set(overnight_holdings.keys())
    print(f"tickFilter: {len(tick_filter)} symbols")

    # 6. Setup position state
    log_dir = _compute_log_dir(trade_date, log_folder)
    pos = PositionState()
    entry_idx_map: dict[str, IndexData] = {}
    entry_signal_type: dict[str, str] = {}
    completed_trades: list[TradeRecord] = []
    index_calc_map: dict[str, IndexCalc] = {}
    latest_idx_map: dict[str, IndexData] = {}
    signal_a_map: dict[str, SignalAState] = {}
    signal_a_short_map: dict[str, SignalAState] = {}
    signal_b_map: dict[str, SignalBState] = {}
    signal_day_high_map: dict[str, SignalDayHighState] = {}
    day_high_entry_logic: dict[str, SignalDayHighEntryRow] = {}
    day_high_limit_up_locked: dict[str, bool] = {}
    signal_b_short_warning_emitted = False
    last_price: dict[str, int] = {}
    funnel = FunnelTracker()
    funnel.universe_count = len(tick_filter)
    funnel.valid_group_symbols = len(valid_group_symbols)

    # Determine if Friday
    is_friday = False
    if len(trade_date) == 8:
        try:
            dt = datetime.strptime(trade_date, "%Y%m%d")
            is_friday = dt.weekday() == 4
        except ValueError:
            pass

    # 0050 prev close
    p0050_ref = f1_map.get("0050")
    p0050_prev = int(p0050_ref.previous_close * 10000) if p0050_ref else 0

    market_gate = MarketGate(config.strategy, p0050_prev)

    proxy_0050_iter: Iterator[MarketTick] | None = None
    proxy_0050_next: MarketTick | None = None

    # The parquet tick feed omits all 00* symbols (including 0050). Prefer a
    # lightweight 0050-only proxy stream from legacy text data when available so
    # gate and entry-change semantics match the text path; otherwise fall back to
    # day-bar open synthesis to keep circuit-breaker logic active.
    if data_source == "parquet" and p0050_prev > 0:
        sidecar_root = default_sidecar_root(data_dir)
        sidecar_file = sidecar_path(sidecar_root, trade_date)
        if sidecar_file.exists():
            proxy_0050_iter = load_0050_sidecar(trade_date, sidecar_root)
            proxy_0050_next = next(proxy_0050_iter, None)
            if proxy_0050_next is not None:
                print(f"[GATE] 0050 sidecar: {sidecar_file}")
            else:
                proxy_0050_iter = None

        if proxy_0050_next is None:
            text_proxy_dir = _find_0050_proxy_text_dir(trade_date, data_dir)
            if text_proxy_dir is not None:
                proxy_0050_iter = iterate_market_file("TSE", trade_date, text_proxy_dir, {"0050"})
                proxy_0050_next = next(proxy_0050_iter, None)
                if proxy_0050_next is not None:
                    print(f"[GATE] 0050 proxy stream: {text_proxy_dir}/TSEQuote.{trade_date}")
                else:
                    proxy_0050_iter = None

        if proxy_0050_next is None:
            day_bar_root = Path(data_dir).parent / "day-ohlcv-and-chip"
            open_price = load_0050_open(trade_date, day_bar_root)
            if open_price is None:
                print(
                    f"[GATE] WARNING: no 0050 proxy stream and no day-bar open for "
                    f"{trade_date} under {day_bar_root}; market gate will be inert "
                    f"under parquet path"
                )
            else:
                open_int = to_int_price(open_price)
                for raw_time in (90_000_000_000, 91_500_000_000):
                    synth = MarketTick(
                        symbol="0050",
                        market="TSE",
                        match_time_str=raw_time,
                        match_time_us=(9 * 3600 + (15 if raw_time == 91_500_000_000 else 0) * 60)
                        * 1_000_000,
                        status_code=0,
                        trade_code=1,
                        match=QuotePair(price=open_int, qty=0),
                    )
                    market_gate.on_tick(synth)
                print(
                    f"[GATE] 0050 backfill: prev_close={p0050_prev / 10000:.2f} "
                    f"open={open_price:.2f} open_chg%={market_gate.market_open_chg_pct:.3f} "
                    f"market_disabled={market_gate.market_disabled}"
                )

    # Setup log writer
    log_writer: _OrderLogWriterLike
    if write_outputs:
        log_writer = OrderLogWriter(log_dir, trade_date)
    else:
        log_writer = _NullOrderLogWriter()
    snapshot_writer = SnapshotWriter(trade_date, snapshot_dir) if write_snapshots else None
    signal_snapshot_writer = SignalSnapshotWriter(trade_date, snapshot_dir) if write_snapshots else None
    snapshots_finalized = False

    entry_idx = 0

    # 7. Run replay
    t0 = time.time()
    num_tracker = NumTracker()
    tick_count = 0
    last_match_time_str = config.execution.exit_time_limit
    last_minute: int | None = None
    market_gate_exit_pending = False

    data_provider = provider
    if data_provider is None:
        if data_source == "parquet":
            data_provider = ParquetReplayProvider(
                otc_date=trade_date,
                tse_date=trade_date,
                root=data_dir,
                tick_filter=tick_filter,
                prev_day_limit_up=prev_day_lu,
                num_tracker=num_tracker,
            )
        else:
            data_provider = FileReplayProvider(
                otc_date=trade_date,
                tse_date=trade_date,
                data_dir=data_dir,
                tick_filter=tick_filter,
                prev_day_limit_up=prev_day_lu,
                num_tracker=num_tracker,
            )

    def _emit_replay_snapshot(match_time_str: int) -> None:
        if on_dashboard_snapshot is None and snapshot_writer is None:
            return

        snapshot = _build_dashboard_snapshot(
            config=config,
            match_time_str=match_time_str,
            tick_count=tick_count,
            strong_group=strong_group,
            strong_single=strong_single,
            symbol_to_groups=symbol_to_groups,
            f1_map=f1_map,
            latest_idx_map=latest_idx_map,
            last_price=last_price,
            signal_a_map=signal_a_map,
            signal_a_short_map=signal_a_short_map,
            signal_b_map=signal_b_map,
            signal_day_high_map=signal_day_high_map,
            day_high_entry_logic=day_high_entry_logic,
            day_high_limit_up_locked=day_high_limit_up_locked,
            pos=pos,
            completed_trades=completed_trades,
            trade_mode=config.strategy.trade_mode,
        )
        if on_dashboard_snapshot is not None:
            on_dashboard_snapshot(snapshot)
        if snapshot_writer is not None:
            snapshot_writer.capture(
                match_time_str=match_time_str,
                strong_group=strong_group,
                signal_a_map=signal_a_map,
                signal_b_map=signal_b_map,
                pos=pos,
                market_gate=market_gate,
                completed_trades=completed_trades,
                dashboard_snapshot=snapshot.to_dict(),
            )

    def _finalize_snapshot_artifacts() -> None:
        nonlocal snapshots_finalized
        if snapshots_finalized:
            return
        if snapshot_writer is not None:
            snapshot_writer.finalize()
        if signal_snapshot_writer is not None:
            signal_snapshot_writer.finalize()
        snapshots_finalized = True

    def _emit_minute_callbacks(match_time_str: int, *, force: bool = False) -> None:
        nonlocal last_minute
        minute = _minute_bucket(match_time_str)
        if not force and minute == last_minute:
            return
        last_minute = minute

        if hooks is not None and hooks.on_minute is not None:
            hooks.on_minute(match_time_str)
        _emit_replay_snapshot(match_time_str)

    def _has_pending_overnight_exit() -> bool:
        if not overnight_holdings:
            return False
        return any(holding.carry_from_date != trade_date for holding in overnight_holdings.values())

    def _finalize_for_market_disable() -> bool:
        nonlocal market_gate_exit_pending
        _finalize_open_positions(
            config,
            pos,
            last_price,
            entry_signal_type,
            entry_idx_map,
            completed_trades,
            log_writer,
            max(last_match_time_str, config.execution.exit_time_limit),
            trade_date=trade_date,
            hooks=hooks,
            signal_snapshot_writer=signal_snapshot_writer,
        )
        _emit_minute_callbacks(max(last_match_time_str, config.execution.exit_time_limit), force=True)
        if write_outputs:
            if not _has_pending_overnight_exit():
                _generate_reports(
                    completed_trades,
                    log_dir,
                    market_gate.market_open_chg_pct,
                    funnel,
                    trade_date,
                    no_charts,
                    data_dir,
                    prev_day_lu,
                    report_data_source,
                )
                log_writer.close()
                market_gate_exit_pending = False
                return True
            market_gate_exit_pending = True
            return False

        market_gate_exit_pending = True
        return False

    def _drain_0050_proxy(until_match_time_str: int) -> bool:
        nonlocal proxy_0050_next
        while proxy_0050_next is not None and proxy_0050_next.match_time_str <= until_match_time_str:
            market_gate.on_tick(proxy_0050_next)
            if market_gate.market_disabled:
                return True
            assert proxy_0050_iter is not None
            proxy_0050_next = next(proxy_0050_iter, None)
        return False

    if market_gate.market_disabled:
        if _finalize_for_market_disable():
            _finalize_snapshot_artifacts()
            return completed_trades


    for tick in data_provider.iterate_ticks():
        if proxy_0050_next is not None and _drain_0050_proxy(tick.match_time_str):
            if _finalize_for_market_disable():
                _finalize_snapshot_artifacts()
                return completed_trades

        tick_count += 1
        last_price[tick.symbol] = tick.match.price
        last_match_time_str = tick.match_time_str

        # Market gate (0050 tracking)
        if tick.symbol == "0050" and tick.trade_code == 1 and tick.match.price > 0:
            market_gate.on_tick(tick)
            if market_gate.market_disabled:
                if _finalize_for_market_disable():
                    _finalize_snapshot_artifacts()
                    return completed_trades

        # Skip non-trade ticks and "00XX" symbols
        if tick.trade_code != 1 or (tick.symbol[0:2] == "00"):
            continue

        symbol = tick.symbol
        f1 = f1_map.get(symbol)
        _apply_limit_up_lock_flag(tick, f1)
        day_high_limit_up_locked[symbol] = tick.is_limit_up_locked

        # Compute index
        if symbol not in index_calc_map:
            index_calc_map[symbol] = IndexCalc()
        idx = index_calc_map[symbol].calc(tick.match.price, tick.match.qty)
        latest_idx_map[symbol] = idx

        if hooks is not None and hooks.on_tick is not None:
            hooks.on_tick(tick, idx)

        # Close carried overnight holdings on the first next-day trade.
        if overnight_holdings is not None and symbol in overnight_holdings:
            holding = overnight_holdings[symbol]
            if holding.carry_from_date != trade_date:
                entry_price_int = int(holding.entry_trade.entry_price * 10000 + 0.5)
                entry_cashflow = -holding.entry_trade.entry_qty * holding.entry_trade.entry_price
                overnight_pos = PositionState(
                    stocks={symbol: holding.qty},
                    symbol_cash={symbol: holding.entry_trade.baseline + entry_cashflow},
                    orders={symbol: []},
                    reserve_stocks={symbol: 0.0},
                    profit_taken={symbol: False},
                    open_trades={symbol: holding.entry_trade},
                    trade_low={symbol: holding.trade_low if holding.trade_low is not None else entry_price_int},
                    trade_high={symbol: holding.trade_high if holding.trade_high is not None else entry_price_int},
                )
                overnight_cause = on_tick_exit(
                    config.execution,
                    symbol,
                    tick.match.price,
                    tick.bid[0].price,
                    tick.ask[0].price,
                    tick.match_time_str,
                    holding.entry_signal_type,
                    holding.entry_idx,
                    overnight_pos,
                    completed_trades,
                    trade_date=holding.carry_from_date,
                    exit_trade_date=trade_date,
                    is_overnight_exit=True,
                    force_exit_cause="overnightExit",
                )
                if overnight_cause:
                    side = completed_trades[-1].side if completed_trades else "long"
                    log_writer.write_leave(
                        symbol,
                        tick.match_time_str,
                        tick.match.price,
                        overnight_pos.cash,
                        overnight_pos.symbol_cash.get(symbol, 0),
                        overnight_cause,
                        side,
                        0.0,
                    )
                    if hooks is not None and hooks.on_exit is not None and completed_trades:
                        hooks.on_exit(symbol, overnight_cause, completed_trades[-1])
                    if signal_snapshot_writer is not None and completed_trades:
                        signal_snapshot_writer.on_exit(symbol, overnight_cause, completed_trades[-1])
                overnight_holdings.pop(symbol, None)
                if market_gate_exit_pending and not _has_pending_overnight_exit():
                    _emit_minute_callbacks(tick.match_time_str, force=True)
                    _generate_reports(
                        completed_trades, log_dir, market_gate.market_open_chg_pct,
                        funnel, trade_date, no_charts, data_dir, prev_day_lu,
                    )
                    log_writer.close()
                    _finalize_snapshot_artifacts()
                    return completed_trades

        # Exit logic
        if abs(pos.stocks.get(symbol, 0)) > 0.001:
            sig_type = entry_signal_type.get(symbol, "")
            eidx = entry_idx_map.get(symbol, IndexData())
            signal_policy = policy_for_signal(sig_type, config.execution)
            overnight_map = overnight_holdings
            should_carry_overnight = (
                sig_type == "SignalDayHigh"
                and signal_policy.hold_overnight_on_limit_up
                and tick.match_time_str >= config.execution.exit_time_limit
                and tick.is_limit_up_locked
                and overnight_map is not None
            )
            if should_carry_overnight:
                ot = pos.open_trades.get(symbol)
                if ot is not None and overnight_map is not None:
                    entry_price_int = int(ot.entry_price * 10000 + 0.5)
                    overnight_map[symbol] = OvernightHolding(
                        entry_trade=ot,
                        qty=pos.stocks.get(symbol, 0.0),
                        entry_idx=eidx,
                        entry_signal_type=sig_type,
                        carry_from_date=trade_date,
                        limit_up_price=pos.limit_up_prices.get(symbol, 0),
                        trade_low=pos.trade_low.get(symbol, entry_price_int),
                        trade_high=pos.trade_high.get(symbol, entry_price_int),
                    )
                pos.stocks[symbol] = 0
                pos.orders[symbol] = []
                pos.reserve_stocks[symbol] = 0
                pos.profit_taken[symbol] = False
                pos.open_trades.pop(symbol, None)
                pos.trade_low.pop(symbol, None)
                pos.trade_high.pop(symbol, None)
                entry_signal_type.pop(symbol, None)
                entry_idx_map.pop(symbol, None)
                log_writer.write_leave(
                    symbol,
                    tick.match_time_str,
                    tick.match.price,
                    pos.cash,
                    pos.symbol_cash.get(symbol, 0),
                    "holdOvernight",
                    "long",
                    0.0,
                )
                _emit_minute_callbacks(tick.match_time_str)
                continue
            cause = on_tick_exit(
                config.execution,
                symbol,
                tick.match.price,
                tick.bid[0].price,
                tick.ask[0].price,
                tick.match_time_str,
                sig_type,
                eidx,
                pos,
                completed_trades,
                trade_date=trade_date,
            )
            if cause:
                side = "long"
                if completed_trades:
                    side = completed_trades[-1].side
                log_writer.write_leave(symbol, tick.match_time_str, tick.match.price,
                                       pos.cash, pos.symbol_cash.get(symbol, 0), cause, side,
                                       pos.stocks.get(symbol, 0))
                if hooks is not None and hooks.on_exit is not None and completed_trades:
                    hooks.on_exit(symbol, cause, completed_trades[-1])
                if signal_snapshot_writer is not None and completed_trades:
                    signal_snapshot_writer.on_exit(symbol, cause, completed_trades[-1])

        if not (abs(pos.stocks.get(symbol, 0)) > 0.001 or market_gate.market_disabled):
            # Screening (skip disabled features entirely)
            single = False
            if strong_single_enabled_for_entry:
                single = strong_single.on_tick(idx, symbol, tick.match.price, tick.match.qty,
                                               tick.match_time_us, tick.match_time_str)
                if single and config.strong_group.enabled and config.strategy.single_group_rank_filter:
                    if not strong_group.is_single_allowed(symbol, config.strategy.single_max_member_rank):
                        single = False

            group = False
            if config.strong_group.enabled:
                group = strong_group.on_tick(idx, symbol, tick.match.price, tick.match.qty,
                                             tick.match_time_us, tick.match_time_str, tick.is_limit_up_locked)
            short_group = False
            if strong_group_short is not None:
                short_group = strong_group_short.on_tick(
                    idx, symbol, tick.match.price, tick.match.qty,
                    tick.match_time_us, tick.match_time_str, tick.is_limit_up_locked
                )

            long_match_type = "None"
            short_match_type = "None"
            if compatibility_short_mode:
                if group:
                    short_match_type = "StrongGroup"
            else:
                if single and group:
                    long_match_type = "Both"
                elif single:
                    long_match_type = "StrongSingle"
                elif group:
                    long_match_type = "StrongGroup"
                if short_group:
                    short_match_type = "StrongGroup"

            match_type_for_screening = short_match_type if compatibility_short_mode else long_match_type

            if hooks is not None and hooks.on_screening is not None:
                hooks.on_screening(symbol, match_type_for_screening, match_type_for_screening != "None")
            if hooks is not None and hooks.on_screening_detail is not None:
                detail_evaluator = strong_group
                detail_match_type = match_type_for_screening
                if compatibility_short_mode:
                    if strong_group_short is not None:
                        detail_evaluator = strong_group_short
                elif signal_a_short_enabled and strong_group_short is not None and short_match_type != "None":
                    detail_evaluator = strong_group_short
                    detail_match_type = short_match_type

                mi = detail_evaluator.last_match_info.get(symbol)
                ahead_symbol = ""
                behind_symbol = ""
                if mi is not None and mi.group_name:
                    member_ranker = detail_evaluator.group_member_vwap_rank.get(mi.group_name)
                    if member_ranker is not None:
                        ranked_symbols = [member_symbol for _, member_symbol in member_ranker.iter_ranked()]
                        if symbol in ranked_symbols:
                            rank_idx = ranked_symbols.index(symbol)
                            if rank_idx > 0:
                                ahead_symbol = ranked_symbols[rank_idx - 1]
                            if rank_idx + 1 < len(ranked_symbols):
                                behind_symbol = ranked_symbols[rank_idx + 1]

                hooks.on_screening_detail(
                    ScreeningDetail(
                        symbol=symbol,
                        match_time_str=tick.match_time_str,
                        match_time_us=tick.match_time_us,
                        vwap=idx.vwap,
                        day_high=idx.day_high,
                        day_low=idx.day_low,
                        match_type=detail_match_type,
                        qualified=detail_match_type != "None",
                        strong_group=group,
                        strong_single=single,
                        group_name=mi.group_name if mi is not None else "",
                        group_rank=mi.group_rank if mi is not None else 0,
                        member_rank=mi.member_rank if mi is not None else 0,
                        raw_member_rank=mi.raw_member_rank if mi is not None else 0,
                        m1_symbol=mi.m1_symbol if mi is not None else "",
                        vol_ratio=mi.vol_ratio if mi is not None else 0.0,
                        month_trading_val=mi.month_trading_val if mi is not None else 0,
                        ahead_symbol=ahead_symbol,
                        behind_symbol=behind_symbol,
                    )
                )

            if long_match_type != "None" or short_match_type != "None":
                funnel.group_qualified_ticks += 1

            is_signal_day_high = False
            trigger_mt_day_high = "None"
            if config.signal_day_high.enabled and not compatibility_short_mode:
                day_high_product_match = group and _is_day_high_product_spec_match(
                    strong_group,
                    symbol,
                    config,
                )
                if day_high_product_match and symbol not in signal_day_high_map:
                    signal_day_high_map[symbol] = SignalDayHighState(symbol=symbol)
                if day_high_product_match:
                    is_signal_day_high, trigger_mt_day_high = evaluate_signal_day_high(
                        signal_day_high_map[symbol],
                        config.signal_day_high,
                        tick.match.price,
                        tick.match_time_str,
                        tick.match_time_us,
                        long_match_type,
                        f1,
                    )
                else:
                    signal_day_high_map.pop(symbol, None)
                if hooks is not None and hooks.on_signal is not None:
                    hooks.on_signal(symbol, "SignalDayHigh", is_signal_day_high)

            # Signal A (skip if disabled)
            is_signal_a = False
            trigger_mt_a = "None"
            if not compatibility_short_mode and config.signal_a.enabled:
                if symbol not in signal_a_map:
                    signal_a_map[symbol] = SignalAState(symbol=symbol)
                is_signal_a, trigger_mt_a = evaluate_signal_a(
                    signal_a_map[symbol], config.signal_a, idx,
                    tick.match.price, tick.match_time_str, tick.match_time_us,
                    long_match_type, f1,
                )
                if hooks is not None and hooks.on_signal is not None:
                    hooks.on_signal(symbol, "SignalA", is_signal_a)
            elif legacy_short_signal_a_enabled:
                if symbol not in signal_a_map:
                    signal_a_map[symbol] = SignalAState(symbol=symbol)
                is_signal_a, trigger_mt_a = evaluate_signal_a_short(
                    signal_a_map[symbol], legacy_short_signal_a_config, idx,
                    tick.match.price, tick.match_time_str, tick.match_time_us,
                    short_match_type, f1,
                )
                if hooks is not None and hooks.on_signal is not None:
                    hooks.on_signal(symbol, "SignalA", is_signal_a)

            is_signal_a_short = False
            trigger_mt_a_short = "None"
            if signal_a_short_enabled:
                if symbol not in signal_a_short_map:
                    signal_a_short_map[symbol] = SignalAState(symbol=symbol)
                is_signal_a_short, trigger_mt_a_short = evaluate_signal_a_short(
                    signal_a_short_map[symbol], config.signal_a_short, idx,
                    tick.match.price, tick.match_time_str, tick.match_time_us,
                    short_match_type, f1,
                )
                if hooks is not None and hooks.on_signal is not None:
                    hooks.on_signal(symbol, "SignalAShort", is_signal_a_short)

            # Signal B (skip if disabled - no state allocation)
            is_signal_b = False
            trigger_mt_b = "None"
            if config.signal_b.enabled:
                if compatibility_short_mode:
                    if config.signal_b.supports_short:
                        raise RuntimeError(
                            "SignalB short compatibility is not implemented. "
                            "Keep SignalB disabled for trade_mode=short."
                        )
                    if not signal_b_short_warning_emitted:
                        print(SIGNAL_B_SHORT_MODE_WARNING)
                        signal_b_short_warning_emitted = True
                else:
                    if symbol not in signal_b_map:
                        sb = SignalBState(symbol=symbol)
                        sb.rolling_low.set_duration(config.signal_b.rolling_low_duration_us)
                        sb.rolling_sum_short.set_duration(config.signal_b.rolling_sum_short_duration_us)
                        sb.rolling_sum_long.set_duration(config.signal_b.rolling_sum_long_duration_us)
                        signal_b_map[symbol] = sb
                    is_signal_b, trigger_mt_b = evaluate_signal_b(
                        signal_b_map[symbol], config.signal_b, idx,
                        symbol, tick.match.price, tick.match.qty,
                        tick.match_time_str, tick.match_time_us, tick.trade_at,
                        long_match_type, f1,
                        symbol in pos.stopped_loss_symbols,
                    )
                if hooks is not None and hooks.on_signal is not None:
                    hooks.on_signal(symbol, "SignalB", is_signal_b)

            # Trigger entry
            selected_signal_type: str | None = None
            selected_match_type = "None"
            selected_trade_mode: TradeMode = "long"
            selected_group_eval = strong_group

            # Deterministic priority: SignalDayHigh > SignalA > SignalAShort > SignalB.
            if is_signal_day_high:
                selected_signal_type = "SignalDayHigh"
                selected_match_type = trigger_mt_day_high
                selected_trade_mode = "long"
            elif is_signal_a:
                selected_signal_type = "SignalA"
                selected_match_type = trigger_mt_a
                selected_trade_mode = "short" if compatibility_short_mode else "long"
            elif is_signal_a_short:
                selected_signal_type = "SignalAShort"
                selected_match_type = trigger_mt_a_short
                selected_trade_mode = "short"
                if strong_group_short is not None:
                    selected_group_eval = strong_group_short
            elif is_signal_b:
                selected_signal_type = "SignalB"
                selected_match_type = trigger_mt_b
                selected_trade_mode = "short" if compatibility_short_mode else "long"
                if selected_trade_mode == "short" and strong_group_short is not None:
                    selected_group_eval = strong_group_short

            if selected_signal_type is not None:
                funnel.signal_triggered += 1

                allowed = True
                block_reason: str | None = None
                day_high_entry_eval = _default_entry_filter_evaluation()
                day_high_group_limit_up_count = 0
                day_high_group_limit_up_passed = True
                day_high_group_name = ""
                if selected_signal_type == "SignalDayHigh":
                    mi = strong_group.last_match_info.get(symbol)
                    day_high_group_name = mi.group_name if mi is not None else ""
                    day_high_entry_eval = evaluate_entry_filters(
                        config.execution,
                        selected_trade_mode,
                        tick,
                        selected_match_type,
                        selected_signal_type,
                        pos,
                        is_friday,
                        p0050_prev,
                        market_gate.p0050_latest,
                        market_gate.market_open_chg_pct,
                        strong_single.forbidden if strong_single_enabled_for_entry else None,
                    )
                    if day_high_group_name:
                        day_high_group_limit_up_count = strong_group.get_group_limit_up_count(day_high_group_name)
                        day_high_group_limit_up_passed = (
                            day_high_group_limit_up_count < config.signal_day_high.max_group_limit_up_count
                        )
                    if (
                        day_high_group_name
                        and not day_high_group_limit_up_passed
                    ):
                        allowed = False
                        block_reason = "day_high_group_limit_up_count"
                if allowed:
                    allowed, block_reason = should_enter(
                        config.execution,
                        selected_trade_mode,
                        tick,
                        selected_match_type,
                        selected_signal_type,
                        pos,
                        is_friday,
                        p0050_prev, market_gate.p0050_latest, market_gate.market_open_chg_pct,
                        strong_single.forbidden if strong_single_enabled_for_entry else None,
                    )
                if selected_signal_type == "SignalDayHigh":
                    day_high_state = signal_day_high_map.get(symbol)
                    day_high_phase = _phase_for_day_high_state(day_high_state) if day_high_state else "triggered"
                    established_high = 0.0
                    pullback_low = 0.0
                    trigger_time = tick.match_time_str
                    if day_high_state is not None:
                        established_high_raw = (
                            day_high_state.last_trigger_high
                            if day_high_state.last_trigger_high > 0
                            else day_high_state.established_high
                        )
                        established_high = established_high_raw / 10000 if established_high_raw > 0 else 0.0
                        pullback_raw = (
                            day_high_state.last_trigger_pullback_low
                            if day_high_state.last_trigger_pullback_low > 0
                            else day_high_state.pullback_low
                        )
                        pullback_low = pullback_raw / 10000 if pullback_raw > 0 else 0.0
                        trigger_time = (
                            day_high_state.last_trigger_time
                            if day_high_state.last_trigger_time > 0
                            else tick.match_time_str
                        )
                    day_high_entry_logic[symbol] = SignalDayHighEntryRow(
                        symbol=symbol,
                        name=f1.name if f1 is not None else symbol,
                        group_name=day_high_group_name,
                        phase=day_high_phase,
                        trigger_time=str(trigger_time),
                        current_price=tick.match.price / 10000,
                        established_high=established_high,
                        pullback_low=pullback_low,
                        day_high_group_limit_up_count=day_high_group_limit_up_count,
                        day_high_group_limit_up_limit=config.signal_day_high.max_group_limit_up_count,
                        day_high_group_limit_up_passed=day_high_group_limit_up_passed,
                        filter_entry_time_limit=day_high_entry_eval.entry_time_limit,
                        filter_prev_day_limit_up=day_high_entry_eval.prev_day_limit_up,
                        filter_no_entry_friday=day_high_entry_eval.no_entry_friday,
                        filter_max_0050_entry_chg=day_high_entry_eval.max_0050_entry_chg,
                        filter_max_0050_intra_chg=day_high_entry_eval.max_0050_intra_chg,
                        filter_volatility_pause=day_high_entry_eval.volatility_pause,
                        filter_already_holding=day_high_entry_eval.already_holding,
                        filter_single_forbidden=day_high_entry_eval.single_forbidden,
                        filter_max_entry_price=day_high_entry_eval.max_entry_price,
                        allowed=allowed,
                        block_reason=block_reason or "",
                    )
                if allowed:
                    execute_entry(
                        config.execution,
                        selected_trade_mode,
                        tick,
                        idx,
                        selected_match_type,
                        selected_signal_type,
                        pos,
                        f1_map,
                        selected_group_eval,
                        p0050_prev,
                        market_gate.p0050_latest,
                        market_gate.market_open_chg_pct,
                    )
                    if selected_signal_type == "SignalDayHigh" and symbol in day_high_entry_logic:
                        day_high_entry_logic[symbol].entered = True
                        day_high_entry_logic[symbol].allowed = True
                        day_high_entry_logic[symbol].block_reason = ""
                    # Initialize MAE/MFE tracking at entry price
                    entry_trade = pos.open_trades.get(symbol)
                    if entry_trade is not None:
                        entry_price_int = int(entry_trade.entry_price * 10000 + 0.5)
                        pos.trade_low[symbol] = entry_price_int
                        pos.trade_high[symbol] = entry_price_int

                    entry_idx_map[symbol] = idx
                    entry_signal_type[symbol] = selected_signal_type
                    entry_idx += 1
                    funnel.executed_trades += 1

                    if hooks is not None and hooks.on_entry is not None:
                        entry_trade = pos.open_trades.get(symbol)
                        if entry_trade is not None:
                            hooks.on_entry(symbol, entry_trade)
                    if signal_snapshot_writer is not None:
                        entry_trade = pos.open_trades.get(symbol)
                        if entry_trade is not None:
                            signal_snapshot_writer.on_entry(symbol, entry_trade)

                    # Write log
                    mi = selected_group_eval.last_match_info.get(symbol)
                    group_info = "-"
                    if mi and mi.group_name:
                        group_info = f"{mi.group_name}(G{mi.group_rank}/M{mi.member_rank}/R{mi.raw_member_rank})"
                        if mi.member_rank > 1:
                            group_info += f" M1={mi.m1_symbol}"
                    log_writer.write_entry(
                        symbol, tick.match_time_str, tick.match.price,
                        pos.cash, pos.symbol_cash.get(symbol, 0), selected_signal_type, selected_match_type,
                        (
                            pos.open_trades[symbol].side
                            if symbol in pos.open_trades
                            else ("short" if selected_trade_mode == "short" else "long")
                        ),
                        pos.stocks.get(symbol, 0), group_info,
                    )
                else:
                    if block_reason:
                        funnel.record_block(block_reason)

        _emit_minute_callbacks(tick.match_time_str)

    print(f"[TIMING] readFileMerged: {(time.time() - t0) * 1000:.0f} ms")

    # 8. Force close remaining positions
    had_open_positions = any(abs(qty) > 0.001 for qty in pos.stocks.values())
    _finalize_open_positions(
        config,
        pos,
        last_price,
        entry_signal_type,
        entry_idx_map,
        completed_trades,
        log_writer,
        max(last_match_time_str, config.execution.exit_time_limit),
        trade_date=trade_date,
        hooks=hooks,
        signal_snapshot_writer=signal_snapshot_writer,
    )
    if had_open_positions:
        _emit_minute_callbacks(
            max(last_match_time_str, config.execution.exit_time_limit),
            force=True,
        )

    # 9. Generate reports
    if write_outputs:
        _generate_reports(
            completed_trades,
            log_dir,
            market_gate.market_open_chg_pct,
            funnel,
            trade_date,
            no_charts,
            data_dir,
            prev_day_lu,
            report_data_source,
        )
        log_writer.close()

    print(f"[TIMING] TOTAL: {(time.time() - t_start) * 1000:.0f} ms")
    print(f"Total ticks processed: {tick_count}")
    _finalize_snapshot_artifacts()

    return completed_trades


def _generate_reports(
    completed_trades: list[TradeRecord],
    log_dir: str,
    market_open_chg_pct: float,
    funnel: FunnelTracker | None = None,
    trade_date: str = "",
    no_charts: bool = False,
    data_dir: str = "./data/",
    prev_day_limit_up: dict[str, bool] | None = None,
    data_source: str = "",
) -> None:
    write_trade_report(completed_trades, log_dir, market_open_chg_pct, data_source)
    write_summary_report(completed_trades, log_dir)
    write_category_report(completed_trades, log_dir)

    # New Phase 2 reports (imported lazily to keep existing imports clean)
    from tw_signal_engine.reporting.build_concentration_report import write_concentration_report
    from tw_signal_engine.reporting.build_funnel_report import write_funnel_report
    from tw_signal_engine.reporting.build_statistics_report import write_statistics_report
    from tw_signal_engine.reporting.build_trade_path_report import write_trade_path_report

    if funnel is not None:
        write_funnel_report(funnel, log_dir)
    write_statistics_report(completed_trades, log_dir)
    write_concentration_report(completed_trades, log_dir)
    write_trade_path_report(completed_trades, log_dir)

    # Charts
    if not no_charts:
        try:
            from tw_signal_engine.reporting.generate_charts import generate_daily_charts
            generate_daily_charts(
                completed_trades,
                funnel,
                log_dir,
                trade_date=trade_date,
                data_dir=data_dir,
                prev_day_limit_up=prev_day_limit_up,
            )
        except ImportError:
            pass
