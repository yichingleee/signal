"""CLI: pre-build volume caches for history window acceleration."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from tw_signal_engine.cli.default_paths import data_dir_help, default_data_dir


def _get_trading_dates(start: str, end: str, data_dir: str) -> list[str]:
    """Find all trading dates between start and end that have data files."""
    data_path = Path(data_dir)
    available_dates: set[str] = set()
    for f in data_path.iterdir():
        name = f.name
        if "Quote." in name:
            date_part = name.split(".")[-1]
            if len(date_part) == 8:
                available_dates.add(date_part)
    return sorted(d for d in available_dates if start <= d <= end)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-build volume caches for replay history windows",
    )
    parser.add_argument("--start", required=True, help="Start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="End date YYYYMMDD")
    parser.add_argument("--data-dir", default=default_data_dir(), help=data_dir_help())
    parser.add_argument(
        "--market",
        nargs="+",
        default=["OTC", "TSE"],
        choices=["OTC", "TSE"],
        help="Market types to cache (default: both)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from tw_signal_engine.market_data.build_volume_caches import ensure_caches

    dates = _get_trading_dates(args.start, args.end, args.data_dir)
    print(f"Found {len(dates)} trading dates in [{args.start}, {args.end}]")

    for market in args.market:
        ensure_caches(market, dates, args.data_dir)
        print(f"  {market}: done")


if __name__ == "__main__":
    main()
