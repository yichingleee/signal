"""CLI for precomputing parquet history day caches."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tw_signal_engine.market_data.parquet_history_cache import (
    BuildParquetHistoryCacheResult,
    default_parquet_history_cache_root,
)
from tw_signal_engine.market_data.parquet_history_loader import build_parquet_history_day_cache

_PARQUET_DATA_ENV = "TW_SIGNAL_PARQUET_DATA_DIR"
_DEFAULT_PARQUET_DATA_DIR = "./data/"

_MARKET_TO_DIR = {
    "TSE": "TWSE",
    "OTC": "TPEX",
}


def _discover_market_dates(
    parquet_root: str | Path,
    market_type: str,
    start: str,
    end: str,
) -> list[str]:
    root = Path(parquet_root) / _MARKET_TO_DIR[market_type]
    if not root.exists():
        return []
    dates: list[str] = []
    for candidate in root.glob("*.parquet"):
        stem = candidate.stem
        if len(stem) == 8 and stem.isdigit() and start <= stem <= end:
            dates.append(stem)
    dates.sort()
    return dates


def _build_one(
    market_type: str,
    date: str,
    data_dir: str,
    cache_dir: str,
    force: bool,
) -> BuildParquetHistoryCacheResult:
    return build_parquet_history_day_cache(
        market_type,
        date,
        data_dir,
        cache_root=cache_dir,
        force=force,
    )


def _summarize(results: list[BuildParquetHistoryCacheResult], cache_dir: str) -> int:
    built = sum(1 for result in results if result.status == "built")
    skipped_fresh = sum(1 for result in results if result.status == "skipped_fresh")
    failed = sum(1 for result in results if result.status == "failed")

    print(f"Summary: built={built} skipped_fresh={skipped_fresh} failed={failed}")
    print(f"Cache root: {cache_dir}")
    return 0 if failed == 0 else 1


def _print_result(result: BuildParquetHistoryCacheResult) -> None:
    line = (
        f"{result.market} {result.date} status={result.status} rows={result.row_count} "
        f"elapsed={result.elapsed_sec:.3f}s path={result.path}"
    )
    if result.message:
        line += f" message={result.message}"
    print(line)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build parquet history day caches")
    parser.add_argument("--start", required=True, help="Inclusive start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="Inclusive end date YYYYMMDD")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get(_PARQUET_DATA_ENV, _DEFAULT_PARQUET_DATA_DIR),
        help="Parquet tick-data root (contains TWSE/ and TPEX/)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help=(
            "Output cache root. Default: "
            "$TW_SIGNAL_PARQUET_HISTORY_CACHE_DIR or sibling parquet-history-cache beside --data-dir"
        ),
    )
    parser.add_argument(
        "--market",
        nargs="+",
        default=["OTC", "TSE"],
        choices=["OTC", "TSE"],
        help="Markets to build (default: both)",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild even when cache metadata is fresh")
    parser.add_argument("--dry-run", action="store_true", help="Discover dates and print planned jobs only")
    parser.add_argument("--jobs", type=int, default=1, help="Worker count for optional parallel build")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if args.start > args.end:
        parser.error("--start must be <= --end")
    return args


def main() -> None:
    args = _parse_args()
    data_dir = str(args.data_dir)
    cache_dir = str(args.cache_dir) if args.cache_dir else str(default_parquet_history_cache_root(data_dir))

    targets: list[tuple[str, str]] = []
    for market in args.market:
        dates = _discover_market_dates(data_dir, market, args.start, args.end)
        targets.extend((market, date) for date in dates)

    targets.sort()
    print(f"Building {len(targets)} parquet history caches from {data_dir}")
    print(f"Date range: {args.start}..{args.end}")
    print(f"Cache root: {cache_dir}")

    if args.dry_run:
        if targets:
            print("Dry run targets:")
            for market, date in targets:
                print(f"{market} {date}")
        else:
            print("Dry run: no matching parquet dates found")
        raise SystemExit(0)

    if not targets:
        print("No matching parquet dates found; nothing to build")
        raise SystemExit(0)

    results: list[BuildParquetHistoryCacheResult] = []
    if args.jobs == 1:
        for market, date in targets:
            result = _build_one(market, date, data_dir, cache_dir, args.force)
            results.append(result)
            _print_result(result)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            future_map = {
                pool.submit(_build_one, market, date, data_dir, cache_dir, args.force): (market, date)
                for market, date in targets
            }
            for future in as_completed(future_map):
                market, date = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = BuildParquetHistoryCacheResult(
                        market=market,
                        date=date,
                        path=Path(cache_dir) / market / f"{date}.pkl",
                        row_count=0,
                        elapsed_sec=0.0,
                        status="failed",
                        message=str(exc),
                    )
                results.append(result)
        results.sort(key=lambda result: (result.market, result.date))
        for result in results:
            _print_result(result)

    exit_code = _summarize(results, cache_dir)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
