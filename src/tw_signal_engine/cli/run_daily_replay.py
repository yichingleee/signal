"""CLI: run a single-day replay."""

from __future__ import annotations

import argparse
import os

from tw_signal_engine.cli.default_paths import (
    default_files_dir,
    default_group_file,
    files_dir_help,
    group_file_help,
)

_DEFAULT_DATA_DIR = "./data/"
_PARQUET_DATA_DIR_ENV = "TW_SIGNAL_PARQUET_DATA_DIR"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run single-day replay backtest")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Data directory. Default: text=./data/; "
            "parquet=$TW_SIGNAL_PARQUET_DATA_DIR (fallback ./data/)"
        ),
    )
    parser.add_argument("--files-dir", default=default_files_dir(), help=files_dir_help())
    parser.add_argument("--group-file", default=default_group_file(), help=group_file_help())
    parser.add_argument("--log-folder", default="", help="Log folder name")
    parser.add_argument("--no-cache", action="store_true", help="Disable history caches (keep data dir read-only)")
    parser.add_argument("--no-charts", action="store_true", help="Skip chart generation (CSV only)")
    parser.add_argument("--snapshots", action="store_true", help="Write replay dashboard snapshots for time-travel mode")
    parser.add_argument("--snapshot-dir", default="./cache/replay/", help="Replay snapshot output directory")
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

    from tw_signal_engine.replay.replay_session import run_daily_replay

    run_daily_replay(
        trade_date=args.date,
        config_path=args.config,
        data_dir=data_dir,
        files_dir=args.files_dir,
        group_file=args.group_file,
        log_folder=args.log_folder,
        use_cache=not args.no_cache,
        no_charts=args.no_charts,
        write_snapshots=args.snapshots,
        snapshot_dir=args.snapshot_dir,
        cost_model_override=args.cost_model,
        data_source=args.data_source,
    )


if __name__ == "__main__":
    main()
