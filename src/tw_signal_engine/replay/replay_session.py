"""Top-level replay session: the main event loop."""

from __future__ import annotations

import time
from datetime import datetime

from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config
from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.execution.create_entry_trade import execute_entry, should_enter
from tw_signal_engine.execution.trade_ledger import on_tick_exit
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.load_history_window import load_history_window
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker, NumTracker
from tw_signal_engine.records.market_event_records import MarketTick, TradeRecord
from tw_signal_engine.reference_data.derive_prev_day_limit_up import derive_prev_day_limit_up
from tw_signal_engine.reference_data.load_group_membership import load_group_membership
from tw_signal_engine.reference_data.load_symbol_reference import load_symbol_reference
from tw_signal_engine.replay.apply_market_gate import MarketGate
from tw_signal_engine.replay.build_replay_universe import build_replay_universe
from tw_signal_engine.replay.merge_market_streams import merge_market_streams
from tw_signal_engine.reporting.build_category_summary import write_category_report
from tw_signal_engine.reporting.build_daily_summary import write_summary_report
from tw_signal_engine.reporting.build_trade_report_rows import write_trade_report
from tw_signal_engine.reporting.write_order_log_csv import OrderLogWriter
from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator
from tw_signal_engine.signals.evaluate_signal_a import evaluate_signal_a
from tw_signal_engine.signals.evaluate_signal_b import evaluate_signal_b
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.signal_state import SignalAState, SignalBState
from tw_signal_engine.state.symbol_state import IndexCalc, IndexData


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

    # 7. Run replay
    t0 = time.time()
    num_tracker = NumTracker()
    tick_count = 0
    last_match_time_str = config.execution.exit_time_limit

    for tick in merge_market_streams(
        "OTC", trade_date, "TSE", trade_date,
        data_dir=data_dir,
        tick_filter=tick_filter,
        prev_day_limit_up=prev_day_lu,
        num_tracker=num_tracker,
    ):
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
                )
                _generate_reports(completed_trades, log_dir, market_gate.market_open_chg_pct)
                log_writer.close()
                return completed_trades

        # Skip non-trade ticks and "00XX" symbols
        if tick.trade_code != 1 or (tick.symbol[0:2] == "00"):
            continue

        symbol = tick.symbol

        # Compute index
        if symbol not in index_calc_map:
            index_calc_map[symbol] = IndexCalc()
        idx = index_calc_map[symbol].calc(tick.match.price, tick.match.qty)

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
    )

    # 9. Generate reports
    _generate_reports(completed_trades, log_dir, market_gate.market_open_chg_pct)
    log_writer.close()

    print(f"[TIMING] TOTAL: {(time.time() - t_start) * 1000:.0f} ms")
    print(f"Total ticks processed: {tick_count}")

    return completed_trades


def _generate_reports(completed_trades: list[TradeRecord], log_dir: str, market_open_chg_pct: float) -> None:
    write_trade_report(completed_trades, log_dir, market_open_chg_pct)
    write_summary_report(completed_trades, log_dir)
    write_category_report(completed_trades, log_dir)
