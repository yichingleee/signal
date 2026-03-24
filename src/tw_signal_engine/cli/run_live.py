"""CLI: run live trading session with Redis market data."""

from __future__ import annotations

import argparse
import signal


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live trading session with Redis market data")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument("--data-dir", default="./data/", help="Data directory")
    parser.add_argument("--files-dir", default="./files/", help="Symbol files directory")
    parser.add_argument("--group-file", default="./files/group.csv", help="Group membership file")
    parser.add_argument("--log-folder", default="", help="Log folder name")
    parser.add_argument("--no-cache", action="store_true", help="Disable volume cache")
    parser.add_argument("--redis-host", default=None, help="Override Redis host")
    parser.add_argument("--redis-port", type=int, default=None, help="Override Redis port")
    parser.add_argument("--backfill", action="store_true", help="Replay today's file before switching to live")
    args = parser.parse_args()

    from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
    from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config
    from tw_signal_engine.market_data.load_history_window import load_history_window
    from tw_signal_engine.market_data.market_data_records import NumTracker
    from tw_signal_engine.market_data.providers import MarketDataProvider
    from tw_signal_engine.market_data.redis_live_provider import RedisLiveProvider
    from tw_signal_engine.reference_data.derive_prev_day_limit_up import derive_prev_day_limit_up
    from tw_signal_engine.reference_data.load_group_membership import load_group_membership
    from tw_signal_engine.reference_data.load_symbol_reference import load_symbol_reference
    from tw_signal_engine.replay.build_replay_universe import build_replay_universe
    from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay
    from tw_signal_engine.screening.evaluate_strong_group import StrongGroupEvaluator
    from tw_signal_engine.screening.evaluate_strong_single import StrongSingleEvaluator

    # 1. Load config
    raw_cfg = load_legacy_ini(args.config)
    config = normalize_strategy_config(raw_cfg)

    # Apply CLI overrides
    if args.redis_host:
        config.live.redis_host = args.redis_host
    if args.redis_port:
        config.live.redis_port = args.redis_port

    # 2. Load reference data
    f1_map = load_symbol_reference(args.date, args.files_dir)
    prev_day_lu = derive_prev_day_limit_up(args.date, args.files_dir)
    _, symbol_to_groups, group_members = load_group_membership(args.group_file)

    # 3. Load history
    use_cache = not args.no_cache
    hw_otc = load_history_window("OTC", args.date, args.data_dir, use_cache=use_cache)
    hw_tse = load_history_window("TSE", args.date, args.data_dir, use_cache=use_cache)
    history = _merge_history_windows(hw_otc, hw_tse)

    # 4. Build replay universe (tick filter)
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
    strong_single_valid = strong_single.initialize_validity() if config.strong_single.enabled else set()

    tick_filter = build_replay_universe(
        set(strong_group.symbol_is_valid.keys()),
        single_valid_symbols=strong_single_valid,
    )
    print(f"Live mode: subscribing to {len(tick_filter)} symbol channels")

    # 5. Create provider
    provider: MarketDataProvider
    if args.backfill:
        from tw_signal_engine.market_data.backfill_provider import BackfillThenLiveProvider
        from tw_signal_engine.market_data.file_replay_provider import FileReplayProvider

        file_provider = FileReplayProvider(
            otc_date=args.date,
            tse_date=args.date,
            data_dir=args.data_dir,
            tick_filter=tick_filter,
            prev_day_limit_up=prev_day_lu,
            num_tracker=NumTracker(),
        )
        redis_provider = RedisLiveProvider(
            config=config.live,
            tick_filter=tick_filter,
            prev_day_limit_up=prev_day_lu,
        )
        provider = BackfillThenLiveProvider(
            file_provider=file_provider,
            redis_provider=redis_provider,
        )
    else:
        provider = RedisLiveProvider(
            config=config.live,
            tick_filter=tick_filter,
            prev_day_limit_up=prev_day_lu,
        )

    # 6. Setup graceful shutdown
    def on_signal(signum: int, frame: object) -> None:
        print("\nShutting down gracefully...")
        if hasattr(provider, "stop"):
            provider.stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # 7. Run
    print(f"Starting live session for {args.date}")
    print(f"Redis: {config.live.redis_host}:{config.live.redis_port}")
    trades = run_daily_replay(
        trade_date=args.date,
        config_path=args.config,
        data_dir=args.data_dir,
        files_dir=args.files_dir,
        group_file=args.group_file,
        log_folder=args.log_folder,
        history=history,
        use_cache=use_cache,
        provider=provider,
    )
    print(f"Session complete. {len(trades)} trades recorded.")


if __name__ == "__main__":
    main()
