"""Per-symbol cumulative-volume parity check between the legacy text replay
files and the new parquet tick-data root.

Used by milestone M1 of the market-data-parquet-migration ExecPlan.

Usage:
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market OTC

The text side is consumed via the existing ``iterate_market_file`` so the
comparison uses exactly the records the legacy ``FileReplayProvider`` would
hand to the engine (post status-code filtering, post depth-line pairing).
The parquet side uses pyarrow with column projection on
``["symbol", "tradeVolume"]`` and the ``[("tradeVolume", ">", 0)]`` push-down
filter recommended in the design report.

The script prints a one-line summary plus the top-ten symbols by absolute
delta. ``symbols with mismatched cumulative volume: 0`` is the M1 acceptance
gate.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from tw_signal_engine.replay.iterate_market_file import iterate_market_file


_MARKET_TO_PARQUET_DIR = {"TSE": "TWSE", "OTC": "TPEX"}


def _sum_text_volume(market: str, date: str, data_dir: str) -> dict[str, int]:
    """Return per-symbol cumulative volume parsed from the legacy text file."""
    totals: dict[str, int] = defaultdict(int)
    for tick in iterate_market_file(market, date, data_dir):
        # iterate_market_file already filters status_code != 0 and pairs the
        # depth line. Sum the per-tick match qty exactly as the engine sees it.
        totals[tick.symbol] += tick.match.qty
    return dict(totals)


def _sum_parquet_volume(market: str, date: str, parquet_root: str) -> dict[str, int]:
    """Return per-symbol cumulative volume from the parquet tick-data file."""
    parquet_subdir = _MARKET_TO_PARQUET_DIR[market]
    path = Path(parquet_root) / parquet_subdir / f"{date}.parquet"
    table = pq.read_table(
        str(path),
        columns=["symbol", "tradeVolume"],
        filters=[("tradeVolume", ">", 0)],
    )
    symbols = table.column("symbol").to_pylist()
    volumes = table.column("tradeVolume").to_pylist()
    totals: dict[str, int] = defaultdict(int)
    for sym, vol in zip(symbols, volumes):
        totals[sym] += vol
    return dict(totals)


def _compare(
    text_totals: dict[str, int], parquet_totals: dict[str, int]
) -> tuple[list[tuple[str, int, int, int]], int, int]:
    """Return (mismatches, text_only_count, parquet_only_count).

    ``mismatches`` is a list of (symbol, text_volume, parquet_volume, delta)
    sorted by absolute delta descending.
    """
    mismatches: list[tuple[str, int, int, int]] = []
    all_symbols = set(text_totals) | set(parquet_totals)
    text_only = 0
    parquet_only = 0
    for symbol in all_symbols:
        t = text_totals.get(symbol, 0)
        p = parquet_totals.get(symbol, 0)
        if t == p:
            continue
        if t == 0:
            parquet_only += 1
        elif p == 0:
            text_only += 1
        delta = p - t
        mismatches.append((symbol, t, p, delta))
    mismatches.sort(key=lambda row: abs(row[3]), reverse=True)
    return mismatches, text_only, parquet_only


def main() -> None:
    parser = argparse.ArgumentParser(description="Text vs parquet cumulative-volume parity check")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument(
        "--market",
        required=True,
        choices=("TSE", "OTC"),
        help="Engine market code; mapped TSE->TWSE, OTC->TPEX for parquet.",
    )
    parser.add_argument(
        "--text-data-dir",
        default="exec/data",
        help="Directory holding TSEQuote.YYYYMMDD / OTCQuote.YYYYMMDD text files.",
    )
    parser.add_argument(
        "--parquet-root",
        default="/Users/liyijing/Projects/Trading/market-data/tick-data/",
        help="Root containing TWSE/ and TPEX/ parquet directories.",
    )
    parser.add_argument("--top", type=int, default=10, help="Top-N symbols by absolute delta.")
    args = parser.parse_args()

    text_totals = _sum_text_volume(args.market, args.date, args.text_data_dir)
    parquet_totals = _sum_parquet_volume(args.market, args.date, args.parquet_root)

    mismatches, text_only, parquet_only = _compare(text_totals, parquet_totals)

    print(f"date={args.date} market={args.market}")
    print(f"  text symbols:    {len(text_totals)}")
    print(f"  parquet symbols: {len(parquet_totals)}")
    print(f"  symbols with mismatched cumulative volume: {len(mismatches)}")
    print(f"  text-only symbols (parquet=0): {text_only}")
    print(f"  parquet-only symbols (text=0): {parquet_only}")
    if mismatches:
        print(f"  top {min(args.top, len(mismatches))} symbols by abs delta (parquet - text):")
        print(f"    {'symbol':<10}{'text':>14}{'parquet':>14}{'delta':>14}")
        for sym, t, p, delta in mismatches[: args.top]:
            print(f"    {sym:<10}{t:>14}{p:>14}{delta:>+14}")


if __name__ == "__main__":
    main()
