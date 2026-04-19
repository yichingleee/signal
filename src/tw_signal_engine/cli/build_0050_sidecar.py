"""CLI for building precomputed 0050 sidecar parquet files."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tw_signal_engine.market_data.proxy_0050_sidecar import (
    Build0050SidecarResult,
    build_0050_sidecar,
    default_sidecar_root,
    discover_text_dates,
)

_TEXT_DATA_ENV = "TW_SIGNAL_DATA_DIR"
_DEFAULT_TEXT_DATA_DIR = "./data/"


def _build_one(date: str, text_data_dir: str, sidecar_dir: str, force: bool) -> Build0050SidecarResult:
    return build_0050_sidecar(
        date=date,
        text_data_dir=text_data_dir,
        sidecar_root=sidecar_dir,
        force=force,
    )


def _summarize(results: list[Build0050SidecarResult], sidecar_dir: str) -> int:
    built = sum(1 for result in results if result.status == "built")
    skipped_fresh = sum(1 for result in results if result.status == "skipped_fresh")
    failed = sum(1 for result in results if result.status == "failed")

    print(f"Summary: built={built} skipped_fresh={skipped_fresh} failed={failed}")
    print(f"Output root: {sidecar_dir}")
    return 0 if failed == 0 else 1


def _print_result(result: Build0050SidecarResult) -> None:
    line = (
        f"{result.date} status={result.status} rows={result.row_count} "
        f"elapsed={result.elapsed_sec:.3f}s path={result.path}"
    )
    if result.message:
        line += f" message={result.message}"
    print(line)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build precomputed 0050 sidecar parquet files")
    parser.add_argument("--start", required=True, help="Inclusive start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="Inclusive end date YYYYMMDD")
    parser.add_argument(
        "--text-data-dir",
        default=os.environ.get(_TEXT_DATA_ENV, _DEFAULT_TEXT_DATA_DIR),
        help="Legacy text replay root containing TSEQuote.YYYYMMDD files",
    )
    parser.add_argument(
        "--sidecar-dir",
        default=None,
        help=(
            "Output sidecar root. Default: "
            "$TW_SIGNAL_0050_SIDECAR_DIR or sibling 0050-sidecar beside --text-data-dir"
        ),
    )
    parser.add_argument("--force", action="store_true", help="Rebuild even when sidecar metadata is fresh")
    parser.add_argument("--dry-run", action="store_true", help="Discover dates and print actions only")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Worker count for optional parallel build (default: 1)",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if args.start > args.end:
        parser.error("--start must be <= --end")
    return args


def main() -> None:
    args = _parse_args()
    text_data_dir = str(args.text_data_dir)
    sidecar_dir = str(args.sidecar_dir) if args.sidecar_dir else str(default_sidecar_root(text_data_dir))
    dates = discover_text_dates(text_data_dir, args.start, args.end)

    print(f"Building {len(dates)} 0050 sidecars from {text_data_dir}")
    print(f"Date range: {args.start}..{args.end}")
    print(f"Output root: {sidecar_dir}")

    if args.dry_run:
        if dates:
            print("Dry run dates:")
            for date in dates:
                print(date)
        else:
            print("Dry run: no matching TSEQuote dates found")
        raise SystemExit(0)

    if not dates:
        print("No matching TSEQuote dates found; nothing to build")
        raise SystemExit(0)

    results: list[Build0050SidecarResult] = []

    if args.jobs == 1:
        for date in dates:
            result = _build_one(date, text_data_dir, sidecar_dir, args.force)
            results.append(result)
            _print_result(result)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            future_map = {
                pool.submit(_build_one, date, text_data_dir, sidecar_dir, args.force): date for date in dates
            }
            for future in as_completed(future_map):
                date = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = Build0050SidecarResult(
                        date=date,
                        path=Path(sidecar_dir) / "0050" / f"{date}.parquet",
                        row_count=0,
                        elapsed_sec=0.0,
                        status="failed",
                        message=str(exc),
                    )
                results.append(result)
        results.sort(key=lambda result: result.date)
        for result in results:
            _print_result(result)

    exit_code = _summarize(results, sidecar_dir)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
