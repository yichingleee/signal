"""Top-level replay session: the main event loop."""

from __future__ import annotations

import time
from datetime import datetime

from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config
from tw_signal_engine.config.strategy_config import ExecutionConfig, NormalizedStrategyConfig
from tw_signal_engine.execution.create_entry_trade import execute_entry, should_enter
from tw_signal_engine.execution.trade_ledger import on_tick_exit
from tw_signal_engine.market_data.file_replay_provider import FileReplayProvider
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.load_history_window import load_history_window
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker, NumTracker
from tw_signal_engine.market_data.paced_replay_provider import PacedReplayProvider
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.records.market_event_records import MarketTick, TradeRecord
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.reference_data.derive_prev_day_limit_up import derive_prev_day_limit_up
from tw_signal_engine.reference_data.load_group_membership import load_group_membership
from tw_signal_engine.reference_data.load_symbol_reference import load_symbol_reference
from tw_signal_engine.replay.apply_market_gate import MarketGate
from tw_signal_engine.replay.build_replay_universe import build_replay_universe
from tw_signal_engine.replay.session_hooks import SessionHooks
from tw_signal_engine.reporting.build_category_summary import write_category_report
from tw_signal_engine.reporting.build_daily_summary import write_summary_report
from tw_signal_engine.reporting.build_trade_report_rows import write_trade_report
from tw_signal_engine.reporting.write_order_log_csv import OrderLogWriter
from tw_signal_engine.screening.evaluate_strong_group import MatchInfo, StrongGroupEvaluator
from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator
from tw_signal_engine.server.dashboard_snapshot import (
    ActivePosition,
    CompletedTrade,
    DashboardSnapshot,
    PreparingEntry,
    SignalAMonitorSnapshot,
    SignalCounters,
    SingleSnapshot,
    VWAPMonitorEntry,
)
from tw_signal_engine.signals.evaluate_signal_a import evaluate_signal_a
from tw_signal_engine.signals.evaluate_signal_b import evaluate_signal_b
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalAState, SignalBState
from tw_signal_engine.state.symbol_state import IndexCalc, IndexData

PRICE_SCALE = 10000.0


def _time_str_to_hhmmss(match_time_str: int) -> str:
    """Convert match_time_str to HH:MM:SS string."""
    raw = match_time_str // 1_000_000
    seconds = raw % 100
    raw //= 100
    minutes = raw % 100
    hours = raw // 100
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _signal_a_state_label(state: SignalAState) -> str:
    if state.triggered:
        return "triggered"
    if state.forbidden:
        return "forbidden"
    if state.near_vwap:
        return "near_vwap"
    return "idle"


def _status_label(
    symbol: str,
    sig_label: str,
    pos: PositionState,
    completed: list[TradeRecord],
) -> str:
    """Build a display status label for a symbol."""
    if pos.stocks.get(symbol, 0) > 0:
        return "持倉中"
    for tr in reversed(completed):
        if tr.symbol == symbol:
            norm_cause = _normalize_exit_cause(tr.final_leave_cause)
            if norm_cause == "take_profit":
                return "停利出場"
            if norm_cause == "stop_loss":
                return "停損出場"
            return "已出場"
    if sig_label == "near_vwap":
        return "接近VWAP"
    if sig_label == "forbidden":
        return "禁止"
    return ""


def _normalize_exit_cause(cause: str) -> str:
    normalized = cause.strip()
    if normalized in ("takeProfit", "take_profit", "take_profit_sell"):
        return "take_profit"
    if normalized in ("stopLoss", "stop_loss", "stop_loss_sell"):
        return "stop_loss"
    if normalized in ("timeExit", "time_exit", "lockedLimitUp", "locked_limit_up"):
        return "time_exit"
    if normalized in ("bailout", "bail_out"):
        return "bailout"
    return normalized or "unknown"


def _estimate_take_profit(entry_price: float, day_high_at_entry: float, exec_config: ExecutionConfig) -> float:
    if exec_config.take_profit_pcts:
        base = entry_price if exec_config.tp_base_entry else day_high_at_entry
        return base * (1 + exec_config.take_profit_pcts[0])
    return day_high_at_entry


def build_dashboard_snapshot(
    match_time_str: int,
    tick_count: int,
    strong_group: StrongGroupEvaluator,
    strong_single: StrongSingleEvaluator | None,
    signal_a_map: dict[str, SignalAState],
    pos: PositionState,
    completed_trades: list[TradeRecord],
    index_calc_map: dict[str, IndexCalc],
    f1_map: dict[str, ReferenceSymbol],
    exec_config: ExecutionConfig,
    last_price: dict[str, int],
    monitored_symbols: set[str] | None = None,
) -> DashboardSnapshot:
    """Build a full dashboard snapshot from current engine state."""
    timestamp = _time_str_to_hhmmss(match_time_str)

    # Collect index data for all symbols
    idx_map: dict[str, IndexData] = {}
    for sym, calc in index_calc_map.items():
        idx_map[sym] = IndexData(
            vwap=calc._price_vol_sum / calc._vol_sum if calc._vol_sum > 0 else 0.0,
            day_high=calc._day_high,
            day_low=calc._day_low,
        )

    # 1. Strong groups
    groups = strong_group.to_snapshot(idx_map)

    # 2. Build symbol → group name mapping from match_info
    sym_group: dict[str, str] = {}
    sym_match: dict[str, MatchInfo] = {}
    for sym, mi in strong_group.last_match_info.items():
        if mi.group_name:
            sym_group[sym] = mi.group_name
            sym_match[sym] = mi

    # 3. Strong singles (if enabled)
    singles: list[SingleSnapshot] = []
    if strong_single is not None and strong_single.config.enabled:
        singles = strong_single.to_snapshot(idx_map, last_price, sym_group)

    # 4. VWAP monitor
    vwap_entries: list[VWAPMonitorEntry] = []
    symbols = set(monitored_symbols) if monitored_symbols is not None else set(idx_map.keys())
    symbols.update(signal_a_map.keys())
    symbols.update(pos.open_trades.keys())
    for tr in completed_trades:
        symbols.add(tr.symbol)

    for sym in sorted(symbols):
        idx = idx_map.get(sym)
        if idx is None:
            continue
        ref = f1_map.get(sym)
        name = ref.name if ref is not None else sym
        prev_close = ref.previous_close if ref is not None else 0.0
        price_raw = last_price.get(sym, 0)
        vwap_raw = idx.vwap

        sig_state = signal_a_map.get(sym)
        sig_label = _signal_a_state_label(sig_state) if sig_state else "idle"
        price = price_raw / PRICE_SCALE
        vwap = vwap_raw / PRICE_SCALE
        vwap_pct = (vwap - prev_close) / prev_close if prev_close > 0 else 0.0
        pv_ratio = price / vwap if vwap > 0 else 0.0

        vwap_entries.append(
            VWAPMonitorEntry(
                symbol=sym,
                name=name,
                group_name=sym_group.get(sym, ""),
                price=price,
                vwap=vwap,
                vwap_pct=vwap_pct,
                pv_ratio=pv_ratio,
                signal_a_state=sig_label,
                status=_status_label(sym, sig_label, pos, completed_trades),
            )
        )

    # 5. Signal A monitor
    preparing: list[PreparingEntry] = []
    entered: list[ActivePosition] = []
    exited: list[CompletedTrade] = []
    counters = SignalCounters()

    for sym, sa_state in signal_a_map.items():
        if sa_state.forbidden:
            counters.forbidden += 1
        elif sa_state.triggered and sym not in pos.open_trades:
            # Triggered but not entered (possibly exited or filtered)
            pass
        elif sa_state.near_vwap and sym not in pos.open_trades:
            # Near VWAP + check if screening qualified
            match_info = sym_match.get(sym)
            if match_info and match_info.group_rank > 0:
                counters.qualified += 1
                ref = f1_map.get(sym)
                name = ref.name if ref is not None else sym
                idx = idx_map.get(sym)
                price_raw = last_price.get(sym, 0)
                vwap_raw = idx.vwap if idx else 0.0
                day_low = idx.day_low if idx else 0
                stop_loss = (vwap_raw / PRICE_SCALE) * exec_config.stop_loss_ratio_a
                low_near = sa_state.low_since_near if sa_state.low_since_near > 0 else price_raw
                distance = (price_raw - low_near) / low_near if low_near > 0 else 0.0

                preparing.append(
                    PreparingEntry(
                        symbol=sym,
                        name=name,
                        group_name=match_info.group_name,
                        group_tag=f"G{match_info.group_rank} {match_info.group_name}",
                        order_price=price_raw / PRICE_SCALE,
                        current_price=price_raw / PRICE_SCALE,
                        distance_pct=distance,
                        vwap=vwap_raw / PRICE_SCALE,
                        day_low=day_low / PRICE_SCALE if day_low < 2**60 else 0.0,
                        stop_loss=stop_loss,
                        near_vwap_pv_ratio=sa_state.near_vwap_pv_ratio,
                    )
                )
            else:
                counters.not_qualified += 1
        elif not sa_state.triggered and not sa_state.near_vwap and not sa_state.forbidden:
            counters.not_qualified += 1

    # Active positions
    for sym, trade in pos.open_trades.items():
        if trade.signal_type != "SignalA":
            continue
        counters.holding += 1
        ref = f1_map.get(sym)
        name = ref.name if ref is not None else sym
        current_price = last_price.get(sym, 0) / PRICE_SCALE
        entry_p = trade.entry_price
        pnl = (current_price - entry_p) / entry_p if entry_p > 0 else 0.0
        stop_loss = trade.entry_vwap * exec_config.stop_loss_ratio_a
        take_profit = _estimate_take_profit(entry_p, trade.day_high_at_entry, exec_config)

        entered.append(
            ActivePosition(
                symbol=sym,
                name=name,
                group_name=trade.group_name,
                group_tag=f"G{trade.group_rank} {trade.group_name}",
                entry_price=entry_p,
                current_price=current_price,
                pnl_pct=pnl,
                stop_loss=stop_loss,
                take_profit=take_profit,
                day_high=trade.day_high_at_entry,
                entry_time=_time_str_to_hhmmss(trade.entry_time_raw),
            )
        )

    # Completed trades
    for tr in completed_trades:
        if tr.signal_type != "SignalA":
            continue
        ref = f1_map.get(tr.symbol)
        name = ref.name if ref is not None else tr.symbol
        cause = _normalize_exit_cause(tr.final_leave_cause)
        if cause == "take_profit":
            counters.take_profit += 1
        elif cause == "stop_loss":
            counters.stop_loss += 1
        pnl_ratio = tr.return_pct / 100.0

        exited.append(
            CompletedTrade(
                symbol=tr.symbol,
                name=name,
                group_name=tr.group_name,
                group_tag=f"G{tr.group_rank} {tr.group_name}" if tr.group_rank > 0 else tr.group_name,
                entry_price=tr.entry_price,
                exit_price=tr.entry_price * (1 + pnl_ratio) if tr.entry_price > 0 else 0.0,
                pnl_pct=pnl_ratio,
                entry_time=_time_str_to_hhmmss(tr.entry_time_raw),
                exit_time=_time_str_to_hhmmss(tr.exit_time_raw),
                exit_cause=cause,
            )
        )

    signal_a = SignalAMonitorSnapshot(
        preparing=preparing,
        entered=entered,
        exited=exited,
        counters=counters,
    )

    return DashboardSnapshot(
        timestamp=timestamp,
        time_raw=match_time_str,
        tick_count=tick_count,
        groups=groups,
        singles=singles,
        vwap_monitor=vwap_entries,
        signal_a=signal_a,
    )


def _compute_log_dir(date: str, log_folder: str = "") -> str:
    if log_folder:
        return f"./log/{log_folder}/{date}/"
    now = datetime.now()
    return f"./log/{date}_{now.strftime('%H%M')}/"


def _finalize_open_positions(
    config: NormalizedStrategyConfig,
    pos: PositionState,
    last_price: dict[str, int],
    entry_signal_type: dict[str, str],
    entry_idx_map: dict[str, IndexData],
    completed_trades: list[TradeRecord],
    log_writer: OrderLogWriter,
    last_match_time_str: int,
    hooks: SessionHooks | None = None,
) -> None:
    dummy_tick = MarketTick()
    dummy_tick.match_time_str = last_match_time_str
    for symbol, qty in list(pos.stocks.items()):
        if qty <= 0:
            continue
        lp = last_price.get(symbol, 0)
        dummy_tick.symbol = symbol
        dummy_tick.match.price = lp
        dummy_tick.bid[0].price = lp
        sig_type = entry_signal_type.get(symbol, "")
        eidx = entry_idx_map.get(symbol, IndexData())
        cause = on_tick_exit(
            config.execution, symbol, lp, lp,
            dummy_tick.match_time_str, sig_type, eidx, pos, completed_trades,
        )
        if cause:
            log_writer.write_leave(
                symbol, dummy_tick.match_time_str, lp,
                pos.cash, pos.symbol_cash.get(symbol, 0), cause,
                pos.stocks.get(symbol, 0),
            )
            if hooks and hooks.on_exit and completed_trades:
                hooks.on_exit(symbol, cause, completed_trades[-1])


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


def run_daily_replay(
    trade_date: str,
    config_path: str = "./cfg/parameter.cfg",
    data_dir: str = "./data/",
    files_dir: str = "./files/",
    group_file: str = "./files/group.csv",
    log_folder: str = "",
    history: HistoryWindow | None = None,
    use_cache: bool = True,
    provider: MarketDataProvider | None = None,
    replay_speed: float | None = None,
    hooks: SessionHooks | None = None,
    enable_snapshots: bool = False,
    snapshot_dir: str = "./cache/replay/",
    on_dashboard_snapshot: object | None = None,
) -> list[TradeRecord]:
    """Run a single-day replay and return completed trades.

    If history is provided, skip loading history from disk (used by batch mode).
    """
    t_start = time.time()

    # 1. Load config
    raw_cfg = load_legacy_ini(config_path)
    config = normalize_strategy_config(raw_cfg)
    print(f"signalA_enabled: [{config.signal_a.enabled}]")
    print(f"signalB_enabled: [{config.signal_b.enabled}]")
    print(f"strongGroup_enabled: [{config.strong_group.enabled}]")
    print(f"strongSingle_enabled: [{config.strong_single.enabled}]")

    # 2. Load reference data
    f1_map = load_symbol_reference(trade_date, files_dir)
    prev_day_lu = derive_prev_day_limit_up(trade_date, files_dir)
    _, symbol_to_groups, group_members = load_group_membership(group_file)

    # 3. Load history (or use pre-built)
    if history is None:
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
    )
    t0 = time.time()
    strong_group.initialize_validity()
    print(f"[TIMING] getGroup: {(time.time() - t0) * 1000:.0f} ms")

    strong_single = StrongSingleEvaluator(
        config=config.strong_single,
        vol_cum=vol_cum,
        trading_val=trading_val,
        f1_map=f1_map,
    )
    strong_single_valid_symbols = strong_single.initialize_validity() if config.strong_single.enabled else set()

    # 5. Build replay universe
    tick_filter = build_replay_universe(
        set(strong_group.symbol_is_valid.keys()),
        single_valid_symbols=strong_single_valid_symbols,
    )
    print(f"tickFilter: {len(tick_filter)} symbols")

    # 6. Setup position state
    log_dir = _compute_log_dir(trade_date, log_folder)
    pos = PositionState()
    entry_idx_map: dict[str, IndexData] = {}
    entry_signal_type: dict[str, str] = {}
    completed_trades: list[TradeRecord] = []
    index_calc_map: dict[str, IndexCalc] = {}
    signal_a_map: dict[str, SignalAState] = {}
    signal_b_map: dict[str, SignalBState] = {}
    last_price: dict[str, int] = {}

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

    # Setup log writer
    log_writer = OrderLogWriter(log_dir, trade_date)

    entry_idx = 0

    # Setup snapshot writers if enabled
    snapshot_writer = None
    signal_snapshot_writer = None
    if enable_snapshots:
        from tw_signal_engine.reporting.snapshot_writer import SignalSnapshotWriter, SnapshotWriter

        snapshot_writer = SnapshotWriter(trade_date, snapshot_dir)
        signal_snapshot_writer = SignalSnapshotWriter(trade_date, snapshot_dir)

        # Wire snapshot hooks (merge with any user-provided hooks)
        if hooks is None:
            hooks = SessionHooks()

        _user_on_minute = hooks.on_minute
        _user_on_entry = hooks.on_entry
        _user_on_exit = hooks.on_exit

        def _snapshot_on_minute(match_time_str: int) -> None:
            assert snapshot_writer is not None
            dashboard_snapshot = build_dashboard_snapshot(
                match_time_str,
                tick_count,
                strong_group,
                strong_single if config.strong_single.enabled else None,
                signal_a_map,
                pos,
                completed_trades,
                index_calc_map,
                f1_map,
                config.execution,
                last_price,
                monitored_symbols=tick_filter,
            )
            snapshot_writer.capture(
                match_time_str, strong_group, signal_a_map, signal_b_map,
                pos, market_gate, completed_trades,
                dashboard_snapshot=dashboard_snapshot.to_dict(),
            )
            if _user_on_minute:
                _user_on_minute(match_time_str)

        def _snapshot_on_entry(symbol: str, trade: EntryTrade) -> None:
            assert signal_snapshot_writer is not None
            signal_snapshot_writer.on_entry(symbol, trade)
            if _user_on_entry:
                _user_on_entry(symbol, trade)

        def _snapshot_on_exit(symbol: str, cause: str, record: TradeRecord) -> None:
            assert signal_snapshot_writer is not None
            signal_snapshot_writer.on_exit(symbol, cause, record)
            if _user_on_exit:
                _user_on_exit(symbol, cause, record)

        hooks.on_minute = _snapshot_on_minute
        hooks.on_entry = _snapshot_on_entry
        hooks.on_exit = _snapshot_on_exit

    # Wire dashboard snapshot hook (for live server)
    if on_dashboard_snapshot is not None:
        if hooks is None:
            hooks = SessionHooks()

        _prev_on_minute = hooks.on_minute

        def _dashboard_on_minute(match_time_str: int) -> None:
            if _prev_on_minute:
                _prev_on_minute(match_time_str)
            snap = build_dashboard_snapshot(
                match_time_str,
                tick_count,
                strong_group,
                strong_single if config.strong_single.enabled else None,
                signal_a_map,
                pos,
                completed_trades,
                index_calc_map,
                f1_map,
                config.execution,
                last_price,
                monitored_symbols=tick_filter,
            )
            on_dashboard_snapshot(snap)  # type: ignore[operator]

        hooks.on_minute = _dashboard_on_minute

    # 7. Run replay
    t0 = time.time()
    num_tracker = NumTracker()
    tick_count = 0
    last_match_time_str = config.execution.exit_time_limit

    if provider is None:
        file_provider = FileReplayProvider(
            otc_date=trade_date,
            tse_date=trade_date,
            data_dir=data_dir,
            tick_filter=tick_filter,
            prev_day_limit_up=prev_day_lu,
            num_tracker=num_tracker,
        )
        if replay_speed is not None:
            provider = PacedReplayProvider(file_provider, speed=replay_speed)
        else:
            provider = file_provider

    _prev_minute_tracker: dict[str, int] = {}

    for tick in provider.iterate_ticks():
        tick_count += 1
        last_price[tick.symbol] = tick.match.price
        last_match_time_str = tick.match_time_str

        # Market gate (0050 tracking)
        if tick.symbol == "0050" and tick.trade_code == 1 and tick.match.price > 0:
            market_gate.on_tick(tick)
            if market_gate.market_disabled:
                _finalize_open_positions(
                    config,
                    pos,
                    last_price,
                    entry_signal_type,
                    entry_idx_map,
                    completed_trades,
                    log_writer,
                    max(last_match_time_str, config.execution.exit_time_limit),
                    hooks,
                )
                _generate_reports(completed_trades, log_dir, market_gate.market_open_chg_pct)
                log_writer.close()
                # Finalize snapshots before early return
                if snapshot_writer is not None:
                    snapshot_writer.finalize()
                if signal_snapshot_writer is not None:
                    signal_snapshot_writer.finalize()
                return completed_trades

        # Skip non-trade ticks and "00XX" symbols
        if tick.trade_code != 1 or (tick.symbol[0:2] == "00"):
            continue

        symbol = tick.symbol

        # Compute index
        if symbol not in index_calc_map:
            index_calc_map[symbol] = IndexCalc()
        idx = index_calc_map[symbol].calc(tick.match.price, tick.match.qty)

        # Hook: on_tick
        if hooks and hooks.on_tick:
            hooks.on_tick(tick, idx)

        # Hook: on_minute (detect minute boundary crossing)
        if hooks and hooks.on_minute:
            cur_minute = tick.match_time_str // 100_000_000
            prev_minute = _prev_minute_tracker.get("v", -1)
            if cur_minute != prev_minute:
                _prev_minute_tracker["v"] = cur_minute
                hooks.on_minute(tick.match_time_str)

        # Exit logic
        if pos.stocks.get(symbol, 0) > 0:
            sig_type = entry_signal_type.get(symbol, "")
            eidx = entry_idx_map.get(symbol, IndexData())
            cause = on_tick_exit(config.execution, symbol, tick.match.price, tick.bid[0].price,
                                tick.match_time_str, sig_type, eidx, pos, completed_trades)
            if cause:
                log_writer.write_leave(symbol, tick.match_time_str, tick.match.price,
                                       pos.cash, pos.symbol_cash.get(symbol, 0), cause,
                                       pos.stocks.get(symbol, 0))
                # Hook: on_exit
                if hooks and hooks.on_exit and completed_trades:
                    hooks.on_exit(symbol, cause, completed_trades[-1])

        # Skip entry if already holding or market disabled
        if pos.stocks.get(symbol, 0) > 0 or market_gate.market_disabled:
            continue

        # Screening (skip disabled features entirely)
        single = False
        if config.strong_single.enabled:
            single = strong_single.on_tick(idx, symbol, tick.match.price, tick.match.qty,
                                           tick.match_time_us, tick.match_time_str)
            if single and config.strong_group.enabled and config.strategy.single_group_rank_filter:
                if not strong_group.is_single_allowed(symbol, config.strategy.single_max_member_rank):
                    single = False

        group = False
        if config.strong_group.enabled:
            group = strong_group.on_tick(idx, symbol, tick.match.price, tick.match.qty,
                                         tick.match_time_us, tick.match_time_str, tick.is_limit_up_locked)

        match_type = "None"
        if single and group:
            match_type = "Both"
        elif single:
            match_type = "StrongSingle"
        elif group:
            match_type = "StrongGroup"

        # Hook: on_screening
        if hooks and hooks.on_screening and match_type != "None":
            hooks.on_screening(symbol, match_type, True)

        # Signal A (skip if disabled)
        f1 = f1_map.get(symbol)
        is_signal_a = False
        trigger_mt_a = "None"
        if config.signal_a.enabled:
            if symbol not in signal_a_map:
                signal_a_map[symbol] = SignalAState(symbol=symbol)
            is_signal_a, trigger_mt_a = evaluate_signal_a(
                signal_a_map[symbol], config.signal_a, idx,
                tick.match.price, tick.match_time_str, tick.match_time_us,
                match_type, f1,
            )

        # Signal B (skip if disabled - no state allocation)
        is_signal_b = False
        trigger_mt_b = "None"
        if config.signal_b.enabled:
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
                match_type, f1,
                symbol in pos.stopped_loss_symbols,
            )

        # Hook: on_signal
        if hooks and hooks.on_signal:
            if is_signal_a:
                hooks.on_signal(symbol, "SignalA", True)
            if is_signal_b:
                hooks.on_signal(symbol, "SignalB", True)

        # Trigger entry
        if is_signal_a or is_signal_b:
            if is_signal_a and is_signal_b:
                sig_type = "SignalA"
                tmt = trigger_mt_a
            elif is_signal_a:
                sig_type = "SignalA"
                tmt = trigger_mt_a
            else:
                sig_type = "SignalB"
                tmt = trigger_mt_b

            if should_enter(config.execution, tick, tmt, sig_type, pos, is_friday,
                            p0050_prev, market_gate.p0050_latest, market_gate.market_open_chg_pct,
                            strong_single.forbidden if config.strong_single.enabled else None):
                execute_entry(config.execution, tick, idx, tmt, sig_type, pos, f1_map,
                              strong_group, p0050_prev, market_gate.p0050_latest,
                              market_gate.market_open_chg_pct)
                entry_idx_map[symbol] = idx
                entry_signal_type[symbol] = sig_type
                entry_idx += 1

                # Hook: on_entry
                if hooks and hooks.on_entry and symbol in pos.open_trades:
                    hooks.on_entry(symbol, pos.open_trades[symbol])

                # Write log
                mi = strong_group.last_match_info.get(symbol)
                group_info = "-"
                if mi and mi.group_name:
                    group_info = f"{mi.group_name}(G{mi.group_rank}/M{mi.member_rank}/R{mi.raw_member_rank})"
                    if mi.member_rank > 1:
                        group_info += f" M1={mi.m1_symbol}"
                log_writer.write_entry(
                    symbol, tick.match_time_str, tick.match.price,
                    pos.cash, pos.symbol_cash.get(symbol, 0), sig_type, tmt,
                    pos.stocks.get(symbol, 0), group_info,
                )

    print(f"[TIMING] readFileMerged: {(time.time() - t0) * 1000:.0f} ms")

    # 8. Force close remaining positions
    _finalize_open_positions(
        config,
        pos,
        last_price,
        entry_signal_type,
        entry_idx_map,
        completed_trades,
        log_writer,
        max(last_match_time_str, config.execution.exit_time_limit),
        hooks,
    )

    # 9. Generate reports
    _generate_reports(completed_trades, log_dir, market_gate.market_open_chg_pct)
    log_writer.close()

    # 10. Finalize snapshots
    if snapshot_writer is not None:
        path = snapshot_writer.finalize()
        if path:
            print(f"[SNAPSHOT] Written {len(snapshot_writer._rows)} snapshots to {path}")
    if signal_snapshot_writer is not None:
        path = signal_snapshot_writer.finalize()
        if path:
            print(f"[SNAPSHOT] Signal records written to {path}")

    print(f"[TIMING] TOTAL: {(time.time() - t_start) * 1000:.0f} ms")
    print(f"Total ticks processed: {tick_count}")

    return completed_trades


def _generate_reports(completed_trades: list[TradeRecord], log_dir: str, market_open_chg_pct: float) -> None:
    write_trade_report(completed_trades, log_dir, market_open_chg_pct)
    write_summary_report(completed_trades, log_dir)
    write_category_report(completed_trades, log_dir)
