"""CLI: run a single-day replay."""

from __future__ import annotations

import argparse

from tw_signal_engine.cli.default_paths import (
    data_dir_help,
    default_data_dir,
    default_files_dir,
    default_group_file,
    files_dir_help,
    group_file_help,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run single-day replay backtest")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    parser.add_argument("--files-dir", default=default_files_dir(), help=files_dir_help())
    parser.add_argument("--group-file", default=default_group_file(), help=group_file_help())
    parser.add_argument("--log-folder", default="", help="Log folder name")
    parser.add_argument("--no-cache", action="store_true", help="Disable volume cache (keep data dir read-only)")
    parser.add_argument("--no-charts", action="store_true", help="Skip chart generation (CSV only)")
    parser.add_argument("--cost-model", default="", help="Override cost params: 'commission=0.001425,tax=0.0015'")
    args = parser.parse_args()

    from tw_signal_engine.replay.replay_session import run_daily_replay

    run_daily_replay(
        trade_date=args.date,
        config_path=args.config,
        data_dir=args.data_dir,
        files_dir=args.files_dir,
        group_file=args.group_file,
        log_folder=args.log_folder,
        use_cache=not args.no_cache,
        no_charts=args.no_charts,
        cost_model_override=args.cost_model,
    )


if __name__ == "__main__":
    main()
