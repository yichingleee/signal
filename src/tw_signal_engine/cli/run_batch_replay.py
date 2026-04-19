"""CLI: run batch replay across multiple dates."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

_DEFAULT_DATA_DIR = "./data/"
_PARQUET_DATA_DIR_ENV = "TW_SIGNAL_PARQUET_DATA_DIR"


def _get_trading_dates(start: str, end: str, data_dir: str = _DEFAULT_DATA_DIR) -> list[str]:
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


def _get_trading_dates_parquet(start: str, end: str, data_dir: str = _DEFAULT_DATA_DIR) -> list[str]:
    """Find all trading dates available under the parquet tick-data root.

    A date counts when at least one of ``TWSE/<date>.parquet`` or
    ``TPEX/<date>.parquet`` exists.
    """
    data_path = Path(data_dir)
    available_dates: set[str] = set()
    for subdir in ("TWSE", "TPEX"):
        market_dir = data_path / subdir
        if not market_dir.exists():
            continue
        for f in market_dir.iterdir():
            name = f.name
            if name.endswith(".parquet"):
                stem = name[: -len(".parquet")]
                if len(stem) == 8 and stem.isdigit():
                    available_dates.add(stem)
    return sorted(d for d in available_dates if start <= d <= end)


def _split_dates_by_symbols_file(dates: list[str], files_dir: str) -> tuple[list[str], list[str]]:
    """Split dates into (replayable, missing-symbols) for parquet guard."""
    root = Path(files_dir)
    ok: list[str] = []
    missing: list[str] = []
    for date in dates:
        if (root / f"Symbols_{date}.csv").exists():
            ok.append(date)
        else:
            missing.append(date)
    return ok, missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch replay backtest")
    parser.add_argument("--start", required=True, help="Start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="End date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Data directory. Default: text=./data/; "
            "parquet=$TW_SIGNAL_PARQUET_DATA_DIR (fallback ./data/)"
        ),
    )
    parser.add_argument("--files-dir", default="./files/", help="Symbol files directory")
    parser.add_argument("--group-file", default="./files/group.csv", help="Group membership file")
    parser.add_argument("--no-cache", action="store_true", help="Disable history cache")
    parser.add_argument("--no-charts", action="store_true", help="Skip chart generation")
    parser.add_argument("--cost-model", default="", help="Override cost params: 'commission=0.001425,tax=0.0015'")
    parser.add_argument(
        "--data-source",
        choices=("text", "parquet"),
        default="parquet",
        help="Market-data ingestion path: new parquet root (default) or legacy text files",
    )
    args = parser.parse_args()
    data_dir = args.data_dir
    if data_dir is None:
        if args.data_source == "parquet":
            data_dir = os.environ.get(_PARQUET_DATA_DIR_ENV, _DEFAULT_DATA_DIR)
        else:
            data_dir = _DEFAULT_DATA_DIR

    from tw_signal_engine.market_data.parquet_rolling_history import ParquetRollingHistoryProvider
    from tw_signal_engine.market_data.rolling_history import RollingHistoryProvider
    from tw_signal_engine.records.market_event_records import TradeRecord
    from tw_signal_engine.replay.replay_session import _merge_history_windows, run_daily_replay
    from tw_signal_engine.reporting.generate_batch_reports import generate_batch_reports

    if args.data_source == "parquet":
        dates = _get_trading_dates_parquet(args.start, args.end, data_dir)
        dates, missing_symbols_dates = _split_dates_by_symbols_file(dates, args.files_dir)
        if missing_symbols_dates:
            print(
                "[GUARD] Skipping dates with missing Symbols files: "
                + ", ".join(missing_symbols_dates)
            )
    else:
        dates = _get_trading_dates(args.start, args.end, data_dir)
    print(f"Batch replay: {len(dates)} dates from {args.start} to {args.end}")

    if not dates:
        print("[GUARD] No replayable dates after Symbols-file guard; exiting.")
        return

    batch_folder = datetime.now().strftime("%m%d_%H%M")
    use_cache = not args.no_cache

    # Create rolling history providers for both markets and data sources.
    # Parquet mode can reuse prior-session windows across adjacent dates and
    # optionally persist day caches for cold-start reduction.
    parquet_otc_provider: ParquetRollingHistoryProvider | None = None
    parquet_tse_provider: ParquetRollingHistoryProvider | None = None
    otc_provider: RollingHistoryProvider | None = None
    tse_provider: RollingHistoryProvider | None = None
    if args.data_source == "parquet":
        parquet_otc_provider = ParquetRollingHistoryProvider(
            "OTC",
            data_dir,
            use_cache=use_cache,
            write_cache=use_cache,
        )
        parquet_tse_provider = ParquetRollingHistoryProvider(
            "TSE",
            data_dir,
            use_cache=use_cache,
            write_cache=use_cache,
        )
    else:
        otc_provider = RollingHistoryProvider("OTC", data_dir, use_cache=use_cache)
        tse_provider = RollingHistoryProvider("TSE", data_dir, use_cache=use_cache)

    all_trades: list[TradeRecord] = []

    for date in dates:
        print(f"\n{'=' * 40}")
        print(f"  Replaying {date}")
        print(f"{'=' * 40}")
        try:
            if args.data_source == "parquet":
                assert parquet_otc_provider is not None and parquet_tse_provider is not None
                hw_otc = parquet_otc_provider.get_history(date)
                hw_tse = parquet_tse_provider.get_history(date)
            else:
                assert otc_provider is not None and tse_provider is not None
                hw_otc = otc_provider.get_history(date)
                hw_tse = tse_provider.get_history(date)
            merged_history = _merge_history_windows(hw_otc, hw_tse)

            day_trades = run_daily_replay(
                trade_date=date,
                config_path=args.config,
                data_dir=data_dir,
                files_dir=args.files_dir,
                group_file=args.group_file,
                log_folder=batch_folder,
                history=merged_history,
                no_charts=args.no_charts,
                cost_model_override=args.cost_model,
                data_source=args.data_source,
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
