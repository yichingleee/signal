"""CLI: run the signal engine web server."""

from __future__ import annotations

import argparse
import signal
import threading
import time
import traceback
from typing import TYPE_CHECKING

from tw_signal_engine.cli.default_paths import (
    data_dir_help,
    default_data_dir,
    default_files_dir,
    default_group_file,
    files_dir_help,
    group_file_help,
)

if TYPE_CHECKING:
    from tw_signal_engine.market_data.providers import MarketDataProvider
    from tw_signal_engine.server.live_state import LiveState


def main() -> None:
    parser = argparse.ArgumentParser(description="Run signal engine web server")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--mode", choices=["live", "replay"], default="replay", help="Server mode")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    parser.add_argument("--files-dir", default=default_files_dir(), help=files_dir_help())
    parser.add_argument("--group-file", default=default_group_file(), help=group_file_help())
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--snapshot-dir", default="./cache/replay/", help="Snapshot directory")
    parser.add_argument("--redis-host", default=None, help="Override Redis host")
    parser.add_argument("--redis-port", type=int, default=None, help="Override Redis port")
    parser.add_argument("--no-cache", action="store_true", help="Disable volume cache")
    args = parser.parse_args()

    import uvicorn

    from tw_signal_engine.server.app import socket_app

    if args.mode == "replay":
        _start_replay_mode(args)
    else:
        _start_live_mode(args)

    print(f"Starting server on {args.host}:{args.port} in {args.mode} mode")
    uvicorn.run(socket_app, host=args.host, port=args.port, log_level="info")


def _start_replay_mode(args: argparse.Namespace) -> None:
    """Load Parquet snapshots and configure for replay mode."""
    from tw_signal_engine.server.app import configure
    from tw_signal_engine.server.replay_manager import ReplayManager

    manager = ReplayManager(args.date, args.snapshot_dir)
    if manager.load():
        print(f"Loaded replay data for {args.date}")
        time_range = manager.get_time_range()
        print(f"  Time range: {time_range['min_time']} - {time_range['max_time']} ({time_range['count']} snapshots)")
    else:
        print(f"Warning: No replay data found for {args.date} in {args.snapshot_dir}")
        print("  Run with --snapshots first to generate Parquet snapshots")

    configure(mode="replay", replay_manager=manager)


def _start_live_mode(args: argparse.Namespace) -> None:
    """Start the engine in a background thread with live state hooks."""
    from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
    from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config
    from tw_signal_engine.market_data.load_history_window import load_history_window
    from tw_signal_engine.market_data.redis_live_provider import RedisLiveProvider
    from tw_signal_engine.reference_data.derive_prev_day_limit_up import derive_prev_day_limit_up
    from tw_signal_engine.reference_data.load_group_membership import load_group_membership
    from tw_signal_engine.reference_data.load_symbol_reference import load_symbol_reference
    from tw_signal_engine.replay.build_replay_universe import (
        build_replay_universe,
        extract_valid_group_symbols,
    )
    from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay
    from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
    from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator
    from tw_signal_engine.server.app import configure
    from tw_signal_engine.server.live_state import LiveState

    # Load config
    raw_cfg = load_legacy_ini(args.config)
    config = normalize_strategy_config(raw_cfg)
    if args.redis_host:
        config.live.redis_host = args.redis_host
    if args.redis_port:
        config.live.redis_port = args.redis_port

    # Load reference data
    f1_map = load_symbol_reference(args.date, args.files_dir)
    prev_day_lu = derive_prev_day_limit_up(args.date, args.files_dir)
    _, symbol_to_groups, group_members = load_group_membership(args.group_file)

    # Load history
    use_cache = not args.no_cache
    hw_otc = load_history_window(
        "OTC",
        args.date,
        args.data_dir,
        use_cache=use_cache,
        require_target_file=False,
    )
    hw_tse = load_history_window(
        "TSE",
        args.date,
        args.data_dir,
        use_cache=use_cache,
        require_target_file=False,
    )
    history = _merge_history_windows(hw_otc, hw_tse)

    # Build tick filter
    strong_group = StrongGroupEvaluator(
        config=config.strong_group,
        symbol_to_groups=symbol_to_groups,
        group_members=group_members,
        vol_cum=history.vol_cum,
        trading_val=history.trading_val,
        f1_map=f1_map,
        prev_day_limit_up=prev_day_lu,
    )
    strong_group.initialize_validity()

    strong_single = StrongSingleEvaluator(
        config=config.strong_single,
        vol_cum=history.vol_cum,
        trading_val=history.trading_val,
        f1_map=f1_map,
    )
    single_valid = strong_single.initialize_validity() if config.strong_single.enabled else set()

    tick_filter = build_replay_universe(
        extract_valid_group_symbols(strong_group.symbol_is_valid),
        single_valid_symbols=single_valid,
    )

    # Create live state and provider
    live_state = LiveState()
    hooks = live_state.build_hooks()

    provider: MarketDataProvider = RedisLiveProvider(
        config=config.live,
        tick_filter=tick_filter,
        prev_day_limit_up=prev_day_lu,
    )

    configure(mode="live", live_state=live_state)
    feed_status_stop = _start_feed_status_bridge(provider, live_state)
    live_state.mark_engine_running()

    startup_error: list[BaseException] = []

    # Run engine in background thread
    def engine_thread() -> None:
        try:
            run_daily_replay(
                trade_date=args.date,
                config_path=args.config,
                data_dir=args.data_dir,
                files_dir=args.files_dir,
                group_file=args.group_file,
                history=history,
                use_cache=use_cache,
                provider=provider,
                hooks=hooks,
                on_dashboard_snapshot=live_state.update_snapshot,
            )
            live_state.mark_engine_stopped()
            print("Engine thread finished")
        except BaseException as exc:
            startup_error.append(exc)
            tb = traceback.format_exc()
            live_state.set_fatal_error(str(exc), tb)
            print("Engine thread crashed:")
            print(tb)

    t = threading.Thread(target=engine_thread, daemon=True, name="engine")
    t.start()
    print(f"Engine thread started, subscribing to {len(tick_filter)} symbols")

    # Fail fast when startup crashes before first tick.
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if not t.is_alive():
            if startup_error:
                feed_status_stop.set()
                raise RuntimeError("Live engine failed during startup") from startup_error[0]
            break
        if live_state.get_status().get("tick_count", 0) > 0:
            break
        time.sleep(0.05)

    # Graceful shutdown
    def on_signal(signum: int, frame: object) -> None:
        print("\nShutting down...")
        feed_status_stop.set()
        if hasattr(provider, "stop"):
            provider.stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)


def _start_feed_status_bridge(
    provider: MarketDataProvider,
    live_state: LiveState,
    interval: float = 1.0,
) -> threading.Event:
    """Periodically copy live provider health into LiveState."""
    stop_event = threading.Event()

    def poll() -> None:
        while not stop_event.is_set():
            _copy_feed_status(provider, live_state)
            stop_event.wait(interval)

    _copy_feed_status(provider, live_state)
    thread = threading.Thread(target=poll, daemon=True, name="feed-status")
    thread.start()
    return stop_event


def _copy_feed_status(provider: MarketDataProvider, live_state: LiveState) -> None:
    status = provider.get_status()
    if status is not None:
        live_state.update_feed_status(status)


if __name__ == "__main__":
    main()
