"""CLI: benchmark harness for replay profiling.

Provides repeatable measurement entrypoints for:
- load_history_window (isolated history loading)
- iterate_market_file (isolated file parsing)
- run_daily_replay (end-to-end session)

Usage:
    uv run python -m tw_signal_engine.cli.run_benchmark history \
        --market OTC --date 20260211 --data-dir exec/data
    uv run python -m tw_signal_engine.cli.run_benchmark parse \
        --market OTC --date 20260211 --data-dir exec/data
    uv run python -m tw_signal_engine.cli.run_benchmark replay \
        --date 20260211 --data-dir exec/data --files-dir exec/files \
        --group-file exec/files/group.csv --config exec/cfg/parameter.cfg
"""

from __future__ import annotations

import argparse
import time

from tw_signal_engine.cli.default_paths import (
    data_dir_help,
    default_data_dir,
    default_files_dir,
    default_group_file,
    files_dir_help,
    group_file_help,
)


def _bench_history(args: argparse.Namespace) -> None:
    from tw_signal_engine.market_data.load_history_window import load_history_window

    print(f"Benchmarking load_history_window: market={args.market}, date={args.date}")
    t0 = time.perf_counter()
    result = load_history_window(args.market, args.date, args.data_dir)
    elapsed = time.perf_counter() - t0
    vol_cum = result.vol_cum
    print(f"  Loaded history window: {len(vol_cum)} slots")
    symbols: set[str] = set()
    for tracker in vol_cum:
        symbols.update(tracker.data_store.keys())
    print(f"  Unique symbols: {len(symbols)}")
    print(f"  Elapsed: {elapsed:.3f}s ({elapsed * 1000:.0f} ms)")


def _bench_parse(args: argparse.Namespace) -> None:
    from tw_signal_engine.replay.iterate_market_file import iterate_market_file

    print(f"Benchmarking iterate_market_file: market={args.market}, date={args.date}")
    t0 = time.perf_counter()
    count = 0
    for _tick in iterate_market_file(args.market, args.date, args.data_dir):
        count += 1
    elapsed = time.perf_counter() - t0
    print(f"  Ticks parsed: {count}")
    print(f"  Elapsed: {elapsed:.3f}s ({elapsed * 1000:.0f} ms)")


def _bench_replay(args: argparse.Namespace) -> None:
    from tw_signal_engine.replay.replay_session import run_daily_replay

    print(f"Benchmarking run_daily_replay: date={args.date}")
    t0 = time.perf_counter()
    trades = run_daily_replay(
        trade_date=args.date,
        config_path=args.config,
        data_dir=args.data_dir,
        files_dir=args.files_dir,
        group_file=args.group_file,
    )
    elapsed = time.perf_counter() - t0
    print(f"  Completed trades: {len(trades)}")
    print(f"  TOTAL elapsed: {elapsed:.3f}s ({elapsed * 1000:.0f} ms)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay benchmark harness")
    sub = parser.add_subparsers(dest="command", required=True)

    # history sub-command
    h = sub.add_parser("history", help="Benchmark load_history_window")
    h.add_argument("--market", required=True, help="OTC or TSE")
    h.add_argument("--date", required=True, help="Target date YYYYMMDD")
    h.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())

    # parse sub-command
    p = sub.add_parser("parse", help="Benchmark iterate_market_file")
    p.add_argument("--market", required=True, help="OTC or TSE")
    p.add_argument("--date", required=True, help="Target date YYYYMMDD")
    p.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())

    # replay sub-command
    r = sub.add_parser("replay", help="Benchmark full run_daily_replay")
    r.add_argument("--date", required=True, help="Target date YYYYMMDD")
    r.add_argument("--config", default="./cfg/parameter.cfg", help="Config file path")
    r.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    r.add_argument("--files-dir", default=default_files_dir(), help=files_dir_help())
    r.add_argument("--group-file", default=default_group_file(), help=group_file_help())

    args = parser.parse_args()

    if args.command == "history":
        _bench_history(args)
    elif args.command == "parse":
        _bench_parse(args)
    elif args.command == "replay":
        _bench_replay(args)


if __name__ == "__main__":
    main()
