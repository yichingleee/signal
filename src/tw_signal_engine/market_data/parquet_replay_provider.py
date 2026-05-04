"""Parquet-backed replay provider implementing ``MarketDataProvider``.

Reads the OTC and TSE parquet files for one trade date from the tick-data
root, validates the parquet source contract, merges them in ``time`` order,
and yields ``MarketTick`` records with the same engine-facing shape as other
providers.

The provider absorbs the per-tick post-processing that
``merge_market_streams`` does today (``prev_limit_up`` lookup,
``volatility_pause`` flag from ``NumTracker``) because there is no
per-market iterator to merge under parquet — pyarrow lets us concat the
tables and sort once, much cheaper than streaming two text files.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from tw_signal_engine.market_data.market_data_records import NumTracker
from tw_signal_engine.market_data.parquet_io import (
    PARQUET_REPLAY_COLUMNS,
    PARQUET_STATUS_EQ_FILTERS,
    assert_replay_schema,
    parquet_path,
    to_int_price,
)
from tw_signal_engine.market_data.providers import MarketDataProvider
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair

_DEFAULT_PARQUET_ROOT = "/Users/liyijing/Projects/Trading/market-data/tick-data/"
_DEFAULT_BATCH_SIZE = 10_000


def _convert_raw_time_to_us(raw_time: int) -> int:
    """Convert ``HHMMSSffffff`` (e.g. 91500000000) to microseconds since midnight."""
    micros = raw_time % 1_000_000
    remaining = raw_time // 1_000_000
    seconds = remaining % 100
    remaining //= 100
    minutes = remaining % 100
    hours = remaining // 100
    return (hours * 3600 + minutes * 60 + seconds) * 1_000_000 + micros


def _read_market_table(
    market: str,
    date: str,
    root: str | Path,
    tick_filter: set[str] | None,
) -> pa.Table:
    """Read one market's parquet file with column projection and pushdown filters."""
    path = parquet_path(root, market, date)
    assert_replay_schema(pq.read_schema(str(path)))
    filters: list[tuple[str, str, object]] = list(PARQUET_STATUS_EQ_FILTERS)
    filters.append(("tradeVolume", ">", 0))
    if tick_filter:
        filters.append(("symbol", "in", list(tick_filter)))
    table = pq.read_table(
        str(path),
        columns=PARQUET_REPLAY_COLUMNS,
        filters=filters,
    )
    market_col = pa.array([market] * table.num_rows, type=pa.string())
    return table.append_column("market", market_col)


class ParquetReplayProvider(MarketDataProvider):
    """Yield ``MarketTick`` events from the parquet TWSE+TPEX feeds for one date."""

    def __init__(
        self,
        otc_date: str,
        tse_date: str,
        root: str | Path = _DEFAULT_PARQUET_ROOT,
        tick_filter: set[str] | None = None,
        prev_day_limit_up: dict[str, bool] | None = None,
        num_tracker: NumTracker | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self.otc_date = otc_date
        self.tse_date = tse_date
        self.root = root
        self.tick_filter = tick_filter
        self.prev_day_limit_up = prev_day_limit_up
        self.num_tracker = num_tracker
        self.batch_size = batch_size

    def iterate_ticks(self) -> Iterator[MarketTick]:
        tse_table = _read_market_table("TSE", self.tse_date, self.root, self.tick_filter)
        otc_table = _read_market_table("OTC", self.otc_date, self.root, self.tick_filter)
        merged = pa.concat_tables([tse_table, otc_table]).combine_chunks()
        merged = merged.sort_by([("time", "ascending")])

        pdlu = self.prev_day_limit_up or {}
        nt = self.num_tracker or NumTracker()

        for batch in merged.to_batches(max_chunksize=self.batch_size):
            symbols = batch.column("symbol").to_pylist()
            times = batch.column("time").to_pylist()
            prices = batch.column("tradePrice").to_pylist()
            volumes = batch.column("tradeVolume").to_pylist()
            bids = batch.column("buyPrice1").to_pylist()
            asks = batch.column("sellPrice1").to_pylist()
            bid_qtys_l1 = batch.column("buyVolume1").to_pylist()
            bid_qtys_l2 = batch.column("buyVolume2").to_pylist()
            bid_qtys_l3 = batch.column("buyVolume3").to_pylist()
            bid_qtys_l4 = batch.column("buyVolume4").to_pylist()
            bid_qtys_l5 = batch.column("buyVolume5").to_pylist()
            ask_qtys_l1 = batch.column("sellVolume1").to_pylist()
            ask_qtys_l2 = batch.column("sellVolume2").to_pylist()
            ask_qtys_l3 = batch.column("sellVolume3").to_pylist()
            ask_qtys_l4 = batch.column("sellVolume4").to_pylist()
            ask_qtys_l5 = batch.column("sellVolume5").to_pylist()
            markets = batch.column("market").to_pylist()

            for (
                sym, raw_time, price, qty, bid_price, ask_price,
                bq1, bq2, bq3, bq4, bq5,
                aq1, aq2, aq3, aq4, aq5,
                market,
            ) in zip(
                symbols, times, prices, volumes, bids, asks,
                bid_qtys_l1, bid_qtys_l2, bid_qtys_l3, bid_qtys_l4, bid_qtys_l5,
                ask_qtys_l1, ask_qtys_l2, ask_qtys_l3, ask_qtys_l4, ask_qtys_l5,
                markets,
            ):
                price_int = to_int_price(price)
                bid_int = to_int_price(bid_price) if bid_price is not None else 0
                ask_int = to_int_price(ask_price) if ask_price is not None else 0
                ts_us = _convert_raw_time_to_us(raw_time)
                total_bid_qty = (
                    (bq1 or 0) + (bq2 or 0) + (bq3 or 0) + (bq4 or 0) + (bq5 or 0)
                )
                total_ask_qty = (
                    (aq1 or 0) + (aq2 or 0) + (aq3 or 0) + (aq4 or 0) + (aq5 or 0)
                )

                tick = MarketTick(
                    symbol=sym,
                    market=market,
                    match_time_str=raw_time,
                    match_time_us=ts_us,
                    status_code=0,
                    trade_code=1,
                    match=QuotePair(price=price_int, qty=qty),
                )
                tick.bid[0].price = bid_int
                tick.ask[0].price = ask_int
                tick.total_bid_qty = total_bid_qty
                tick.total_ask_qty = total_ask_qty
                if bid_int and price_int == bid_int:
                    tick.trade_at = 1
                elif ask_int:
                    tick.trade_at = 2

                tick.prev_limit_up = pdlu.get(sym, False)
                trade_count = nt.on_tick(sym, ts_us)
                tick.volatility_pause = trade_count <= 3

                yield tick
