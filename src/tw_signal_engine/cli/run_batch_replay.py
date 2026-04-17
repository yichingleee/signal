"""CLI: run batch replay across multiple dates."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from tw_signal_engine.cli.default_paths import (
    data_dir_help,
    default_data_dir,
    default_files_dir,
    default_group_file,
    files_dir_help,
    group_file_help,
)


def _get_trading_dates(start: str, end: str, data_dir: str = "./data/") -> list[str]:
    """Find all trading dates between start and end that have data files."""
    data_path = Path(data_dir)
    available_dates: set[str] = set()
    for f in data_path.iterdir():
        name = f.name
        if "Quote." in name:
            date_part = name.split(".")[-1]
            if len(date_part) == 8:
                available_dates.add(date_part)

    result = sorted(d for d in available_dates if start <= d <= end)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch replay backtest")
    parser.add_argument("--start", required=True, help="Start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="End date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    parser.add_argument("--files-dir", default=default_files_dir(), help=files_dir_help())
    parser.add_argument("--group-file", default=default_group_file(), help=group_file_help())
    parser.add_argument("--no-cache", action="store_true", help="Disable history cache")
    parser.add_argument("--no-charts", action="store_true", help="Skip chart generation")
    parser.add_argument("--cost-model", default="", help="Override cost params: 'commission=0.001425,tax=0.0015'")
    args = parser.parse_args()

    from tw_signal_engine.market_data.rolling_history import RollingHistoryProvider
    from tw_signal_engine.records.market_event_records import TradeRecord
    from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay
    from tw_signal_engine.reporting.generate_batch_reports import generate_batch_reports

    dates = _get_trading_dates(args.start, args.end, args.data_dir)
    print(f"Batch replay: {len(dates)} dates from {args.start} to {args.end}")

    batch_folder = datetime.now().strftime("%m%d_%H%M")
    use_cache = not args.no_cache

    # Create rolling history providers for both markets
    otc_provider = RollingHistoryProvider("OTC", args.data_dir, use_cache=use_cache)
    tse_provider = RollingHistoryProvider("TSE", args.data_dir, use_cache=use_cache)

    all_trades: list[TradeRecord] = []

    for date in dates:
        print(f"\n{'=' * 40}")
        print(f"  Replaying {date}")
        print(f"{'=' * 40}")
        try:
            # Get history from rolling providers (reuses loaded sessions)
            hw_otc = otc_provider.get_history(date)
            hw_tse = tse_provider.get_history(date)
            merged_history = _merge_history_windows(hw_otc, hw_tse)

            day_trades = run_daily_replay(
                trade_date=date,
                config_path=args.config,
                data_dir=args.data_dir,
                files_dir=args.files_dir,
                group_file=args.group_file,
                log_folder=batch_folder,
                history=merged_history,
                no_charts=args.no_charts,
                cost_model_override=args.cost_model,
            )
            all_trades.extend(day_trades)
        except Exception as e:
            print(f"  ERROR on {date}: {e}")

    # Generate batch-level reports
    if all_trades:
        batch_log_dir = f"./log/{batch_folder}/"
        Path(batch_log_dir).mkdir(parents=True, exist_ok=True)
        generate_batch_reports(all_trades, batch_log_dir)

        if not args.no_charts:
            try:
                from tw_signal_engine.reporting.generate_charts import generate_batch_charts
                generate_batch_charts(all_trades, batch_log_dir)
            except ImportError:
                print("[Charts] matplotlib not installed, skipping batch charts")

        print(f"\n{'=' * 40}")
        print(f"  Batch complete: {len(all_trades)} trades across {len(dates)} dates")
        print(f"  Batch reports: {batch_log_dir}")
        print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
