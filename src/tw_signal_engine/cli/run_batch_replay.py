"""CLI: run batch replay across multiple dates."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path


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
    parser.add_argument("--data-dir", default="./data/", help="Data directory")
    parser.add_argument("--files-dir", default="./files/", help="Symbol files directory")
    parser.add_argument("--group-file", default="./files/group.csv", help="Group membership file")
    parser.add_argument("--no-cache", action="store_true", help="Disable history cache")
    args = parser.parse_args()

    from tw_signal_engine.market_data.rolling_history import RollingHistoryProvider
    from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay

    dates = _get_trading_dates(args.start, args.end, args.data_dir)
    print(f"Batch replay: {len(dates)} dates from {args.start} to {args.end}")

    batch_folder = datetime.now().strftime("%m%d_%H%M")
    use_cache = not args.no_cache

    # Create rolling history providers for both markets
    otc_provider = RollingHistoryProvider("OTC", args.data_dir, use_cache=use_cache)
    tse_provider = RollingHistoryProvider("TSE", args.data_dir, use_cache=use_cache)

    for date in dates:
        print(f"\n{'=' * 40}")
        print(f"  Replaying {date}")
        print(f"{'=' * 40}")
        try:
            # Get history from rolling providers (reuses loaded sessions)
            hw_otc = otc_provider.get_history(date)
            hw_tse = tse_provider.get_history(date)
            merged_history = _merge_history_windows(hw_otc, hw_tse)

            run_daily_replay(
                trade_date=date,
                config_path=args.config,
                data_dir=args.data_dir,
                files_dir=args.files_dir,
                group_file=args.group_file,
                log_folder=batch_folder,
                history=merged_history,
            )
        except Exception as e:
            print(f"  ERROR on {date}: {e}")


if __name__ == "__main__":
    main()
