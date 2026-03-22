"""CLI: run a single-day replay."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run single-day replay backtest")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    parser.add_argument("--data-dir", default="./data/", help="Data directory")
    parser.add_argument("--files-dir", default="./files/", help="Symbol files directory")
    parser.add_argument("--group-file", default="./files/group.csv", help="Group membership file")
    parser.add_argument("--log-folder", default="", help="Log folder name")
    parser.add_argument("--no-cache", action="store_true", help="Disable volume cache (keep data dir read-only)")
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
    )


if __name__ == "__main__":
    main()
