"""CLI: regenerate charts from existing report artifacts without replay."""

from __future__ import annotations

import argparse
from pathlib import Path

from tw_signal_engine.cli.default_paths import data_dir_help, default_data_dir
from tw_signal_engine.reporting.generate_charts import generate_batch_charts, generate_daily_charts
from tw_signal_engine.reporting.load_report_artifacts import (
    load_batch_trade_records,
    load_funnel_tracker,
    load_trade_records,
    select_replay_dates,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate charts from report CSV artifacts")
    parser.add_argument("--log-dir", required=True, help="Batch log directory (e.g., ./log/0418_1541)")
    parser.add_argument("--date", default="", help="Single replay date YYYYMMDD")
    parser.add_argument("--start", default="", help="Start date YYYYMMDD (requires --end)")
    parser.add_argument("--end", default="", help="End date YYYYMMDD (requires --start)")
    parser.add_argument("--daily-only", action="store_true", help="Regenerate daily charts only")
    parser.add_argument("--batch-only", action="store_true", help="Regenerate batch charts only")
    parser.add_argument(
        "--with-trade-day",
        action="store_true",
        help="Also regenerate per-symbol intraday timeline charts (reads replay tick files)",
    )
    parser.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.daily_only and args.batch_only:
        parser.error("Choose at most one of --daily-only or --batch-only")

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        parser.error(f"--log-dir does not exist: {log_dir}")
    if not log_dir.is_dir():
        parser.error(f"--log-dir is not a directory: {log_dir}")

    dates = select_replay_dates(
        log_dir=log_dir,
        trade_date=args.date or None,
        start=args.start or None,
        end=args.end or None,
    )
    if not dates:
        print("No matching replay dates found under log directory.")
        return

    run_daily = not args.batch_only
    run_batch = not args.daily_only

    if run_daily:
        for date in dates:
            day_dir = log_dir / date
            trades = load_trade_records(day_dir, date)
            funnel = load_funnel_tracker(day_dir)
            # Empty trade_date skips timeline rebuild and regenerates report-only charts quickly.
            chart_trade_date = date if args.with_trade_day else ""
            generate_daily_charts(
                trades=trades,
                funnel=funnel,
                log_dir=str(day_dir),
                trade_date=chart_trade_date,
                data_dir=args.data_dir,
            )
            print(f"[ChartsOnly] daily {date}: trades={len(trades)}")

    if run_batch:
        all_trades = load_batch_trade_records(log_dir, dates)
        generate_batch_charts(all_trades, str(log_dir))
        print(f"[ChartsOnly] batch: dates={len(dates)} trades={len(all_trades)}")


if __name__ == "__main__":
    main()
