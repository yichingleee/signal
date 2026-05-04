"""Diagnostic per-symbol cumulative-volume comparison for text and parquet.

This tool is intentionally not a release parity gate. The legacy text files
and parquet tick-data root are separate replay sources with separate source
contracts. Cross-source deltas are useful audit evidence, but equality is not
required for parquet correctness.

Usage:
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market TSE
    uv run python scripts/compare_text_vs_parquet.py --date 20260326 --market OTC

The text side is consumed via the existing ``iterate_market_file`` so the
comparison uses exactly the records the legacy ``FileReplayProvider`` would
hand to the engine (post status-code filtering, post depth-line pairing).
The parquet side uses pyarrow with column projection on
``["symbol", "tradeVolume"]`` and the replay-source push-down filters:
``matchFlag == "Y"``, regular session time, and positive ``tradeVolume``.

The script prints a summary, classifies structural differences that are known
to be source-specific, and lists the largest potential regressions for review.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from tw_signal_engine.market_data.parquet_io import PARQUET_STATUS_EQ_FILTERS
from tw_signal_engine.replay.iterate_market_file import iterate_market_file

_MARKET_TO_PARQUET_DIR = {"TSE": "TWSE", "OTC": "TPEX"}


@dataclass(frozen=True)
class VolumeDiff:
    symbol: str
    text_volume: int
    parquet_volume: int
    delta: int
    classification: str
    reason: str


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
        filters=[*PARQUET_STATUS_EQ_FILTERS, ("tradeVolume", ">", 0)],
    )
    symbols = table.column("symbol").to_pylist()
    volumes = table.column("tradeVolume").to_pylist()
    totals: dict[str, int] = defaultdict(int)
    for sym, vol in zip(symbols, volumes):
        totals[sym] += vol
    return dict(totals)


def _classify_difference(symbol: str, text_volume: int, parquet_volume: int) -> tuple[str, str]:
    if text_volume > 0 and parquet_volume == 0 and symbol.startswith("00"):
        return "expected_source_difference", "parquet_omits_00_prefix_symbols"
    if text_volume > 0 and parquet_volume == 0:
        return "potential_regression", "symbol_present_only_in_text"
    if text_volume == 0 and parquet_volume > 0:
        return "potential_regression", "symbol_present_only_in_parquet"
    return "potential_regression", "same_symbol_volume_delta"


def _compare(text_totals: dict[str, int], parquet_totals: dict[str, int]) -> list[VolumeDiff]:
    """Return classified volume differences sorted by absolute delta descending."""
    diffs: list[VolumeDiff] = []
    all_symbols = set(text_totals) | set(parquet_totals)
    for symbol in all_symbols:
        t = text_totals.get(symbol, 0)
        p = parquet_totals.get(symbol, 0)
        if t == p:
            continue
        delta = p - t
        classification, reason = _classify_difference(symbol, t, p)
        diffs.append(VolumeDiff(symbol, t, p, delta, classification, reason))
    diffs.sort(key=lambda row: abs(row.delta), reverse=True)
    return diffs


def main() -> None:
    parser = argparse.ArgumentParser(description="Text vs parquet cumulative-volume diagnostic")
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
    parser.add_argument(
        "--fail-on-potential-regression",
        action="store_true",
        help="Exit non-zero if any difference is not classified as expected source difference.",
    )
    args = parser.parse_args()

    text_totals = _sum_text_volume(args.market, args.date, args.text_data_dir)
    parquet_totals = _sum_parquet_volume(args.market, args.date, args.parquet_root)

    diffs = _compare(text_totals, parquet_totals)
    expected_diffs = [d for d in diffs if d.classification == "expected_source_difference"]
    potential_regressions = [d for d in diffs if d.classification == "potential_regression"]
    text_only = sum(1 for d in diffs if d.text_volume > 0 and d.parquet_volume == 0)
    parquet_only = sum(1 for d in diffs if d.text_volume == 0 and d.parquet_volume > 0)

    print(f"date={args.date} market={args.market}")
    print(f"  text symbols:    {len(text_totals)}")
    print(f"  parquet symbols: {len(parquet_totals)}")
    print(f"  symbols with cumulative-volume differences: {len(diffs)}")
    print(f"  expected source differences: {len(expected_diffs)}")
    print(f"  potential regressions: {len(potential_regressions)}")
    print(f"  text-only symbols (parquet=0): {text_only}")
    print(f"  parquet-only symbols (text=0): {parquet_only}")
    if diffs:
        print(f"  top {min(args.top, len(diffs))} symbols by abs delta (parquet - text):")
        print(
            f"    {'symbol':<10}{'text':>14}{'parquet':>14}{'delta':>14}  "
            f"{'classification':<28}reason"
        )
        for diff in diffs[: args.top]:
            print(
                f"    {diff.symbol:<10}{diff.text_volume:>14}{diff.parquet_volume:>14}"
                f"{diff.delta:>+14}  {diff.classification:<28}{diff.reason}"
            )

    if args.fail_on_potential_regression and potential_regressions:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
