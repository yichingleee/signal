# Parquet Tick Data Integration Report

**File analysed:** `data/test/1101.parquet` (1101 台泥, 2025-01-02)

---

## 1. New Format Summary

| Attribute | Value |
|---|---|
| Rows | 10,267 |
| Columns | 30 |
| Row types | `Trade` (1,720 rows) + `Depth` (8,547 rows) |
| Time range | 08:30:21 – 13:30:00 (includes pre-open book) |
| File size | 248 KB (parquet, single symbol, one day) |
| Price convention | **Float (元)** — e.g. `31.55` |
| Timestamp | `Datetime` (datetime64[ns]) + `Timestamp` (epoch ms) |
| Depth levels | 5 bid + 5 ask (price + volume per level) |

### Trade row fields
`Type, StockCode, Datetime, Timestamp, Flag, Price, Volume, TotalVolume`
- `Flag` = 0 for all rows (analogous to `status_code == 0` in current format)
- `TotalVolume` = running cumulative volume for the day
- Depth columns are all NaN on Trade rows

### Depth row fields
`Type, StockCode, Datetime, Timestamp, BidCount, AskCount, Bid1_Price..Bid5_Volume, Ask1_Price..Ask5_Volume`
- Trade columns (`Flag, Price, Volume, TotalVolume`) are all NaN on Depth rows
- Every Trade row has a matching Depth row with the exact same `Timestamp` (1720/1720)
- Pre-open session has 130 depth snapshots (~5 sec interval) before any trades

### Key structural difference from current format

| Aspect | Current (TSEQuote/OTCQuote text) | New (parquet) |
|---|---|---|
| File scope | All symbols in one market file per day | **One file per symbol** |
| Encoding | Custom CSV: `Trade,SYMBOL,MATCHTIME,STATUS,PRICE,QTY,...` | Apache Parquet (columnar, typed) |
| Price unit | `int * 10000` (e.g. `315500`) | **Float (元)** (e.g. `31.55`) |
| Time format | `HMMSS000000` integer (e.g. `90001994194`) | `datetime64[ns]` + epoch ms |
| Depth | Inline string: `BID:5,P1*Q1,...ASK:5,...` | 20 typed columns (5 levels x 2 sides x 2 fields) |
| Trade/Depth pairing | Consecutive line pairs, fragile | Same timestamp, explicit `Type` column |
| Market indicator | Inferred from filename (`TSE` / `OTC`) | Not present — must come from filename or metadata |

---

## 2. Benefits

### 2.1 Performance — I/O and parsing
- **Columnar compression**: parquet files are typically 2–5x smaller than equivalent text for dense numeric data. For full-market daily files, this could reduce disk I/O significantly.
- **Zero parsing overhead**: no more `line.split(",")`, `line.find("BID:")`, integer scanning. Parquet decodes directly to typed arrays.
- **Column projection**: the replay engine only needs `Price, Volume, Bid1_Price, Ask1_Price` per trade tick. Parquet can read only those columns, skipping the 20+ unused depth columns entirely.
- **Predicate pushdown**: with row-group statistics, pre-open data or specific time ranges can be skipped without reading.

### 2.2 Data quality
- **Typed schema eliminates malformed-line errors**: current text parser has many early-return `None` paths for bad data.
- **Explicit Trade/Depth separation**: no more fragile "is the next line a Depth?" heuristic. The `Type` column is definitive.
- **Full 5-level book**: current pipeline extracts only best bid/ask. The parquet format provides all 5 levels, enabling future order-flow and microstructure signals.
- **Pre-open book snapshots**: 130 depth rows before 09:00 give visibility into opening auction dynamics — not available in the current text format.
- **Cumulative TotalVolume**: readily available without the engine needing to track it.

### 2.3 Ecosystem
- Parquet is natively supported by pandas, pyarrow, polars, DuckDB, Spark. Analysis and ad-hoc queries become trivial.
- The per-symbol-per-day file layout maps naturally to partitioned storage (`data/{date}/{symbol}.parquet`), enabling efficient symbol-level caching and parallel loads.

---

## 3. Problems to Solve

### 3.1 Price convention mismatch (critical)
The entire pipeline uses `price * 10000` integers:
- `MarketTick.match.price`, `bid[].price`, `ask[].price` are all `int`
- `IndexCalc.calc()` computes VWAP with `price * qty` integer arithmetic
- Config thresholds, tick-size tables, and reference data all use `int * 10000`

**Solution**: The parquet adapter must convert `float → int * 10000` at ingestion time:
```python
price_int = round(row["Price"] * 10000)
```
Floating-point precision must be handled carefully (e.g., `31.55 * 10000 = 315499.99...`). Use `round()`, not `int()`.

### 3.2 Time format mismatch (critical)
The pipeline uses two time representations:
- `match_time_str`: `HMMSS000000` integer (e.g., `90001994194` for 09:00:01.994194)
- `match_time_us`: microseconds since midnight

The parquet provides `Datetime` (datetime64[ns]) and `Timestamp` (epoch ms).

**Solution**: Convert at ingestion:
```python
dt = row["Datetime"]
h, m, s, us = dt.hour, dt.minute, dt.second, dt.microsecond
match_time_str = h * 10000000000 + m * 100000000 + s * 1000000 + us
match_time_us  = (h * 3600 + m * 60 + s) * 1_000_000 + us
```

### 3.3 Missing `status_code` / `trade_code` fields
Current pipeline filters on `status_code == 0` to skip non-regular trades (e.g., auction, error corrections). The parquet has only `Flag` (always `0.0` in the sample).

**Risk**: If `Flag == 0` reliably maps to `status_code == 0`, this is fine. But we need to confirm:
- What values can `Flag` take?
- Does the data source pre-filter to regular trades, or could auction/odd-lot trades appear?

### 3.4 Missing market identifier
The current pipeline distinguishes `TSE` vs `OTC` via filename (`TSEQuote.*` / `OTCQuote.*`). The parquet has `StockCode` but no market field.

**Solution options**:
1. Encode market in file path: `data/{date}/TSE/{symbol}.parquet`
2. Derive from symbol code (TSE symbols are typically 4 digits, OTC includes letters — but unreliable)
3. Add a `Market` column to the parquet schema upstream

### 3.5 File layout — per-symbol vs per-market
Current pipeline iterates a single market file and yields ticks for all symbols interleaved by time. The parquet format is one file per symbol.

This changes the merge strategy fundamentally:
- Current: `iterate_market_file("TSE", date)` → streams all TSE ticks in time order
- New: must open N parquet files (one per symbol in universe), then merge into a single time-ordered stream

**Solution**: Build a `ParquetReplayProvider` that:
1. Takes the replay universe (symbol list) + date + data directory
2. Loads each symbol's parquet, filters to Trade rows only
3. Merges all symbols into a single time-ordered iterator (heap merge on `Timestamp`)
4. For each trade, looks up the matching or most-recent Depth row for bid/ask

### 3.6 `trade_at` inference (bid-side vs ask-side)
Current pipeline determines `trade_at` by comparing `price == bid_price` (inner/bid) vs else (outer/ask). This is used by `evaluate_signal_b` for inner-volume tracking.

The parquet has Bid1/Ask1 on Depth rows but **not on Trade rows**. Need to join Trade with its matching Depth row (same timestamp) to infer `trade_at`.

### 3.7 Dependency management
`pandas` and `pyarrow` are currently in the `[live]` optional dependency group, not in core `dependencies`. For replay (the primary use case), the parquet adapter would require promoting these to core dependencies, or creating a new `[parquet]` extra.

### 3.8 Memory footprint for full-market loads
Loading all ~1,000 symbols × 10K rows as DataFrames is ~10M rows. At 30 columns of float64, that's ~2.4 GB in memory if loaded naively.

**Mitigation**: 
- Read only needed columns (`Price, Volume, Bid1_Price, Ask1_Price, Timestamp, Type`)
- Stream row-by-row rather than loading full DataFrames
- Use `pyarrow.parquet.read_table()` with column projection + row-group filtering

---

## 4. Integration Architecture

### Recommended approach: new `ParquetReplayProvider`

```
MarketDataProvider (ABC)
├── FileReplayProvider          ← existing, text-based
├── RedisLiveProvider           ← existing, live feed
└── ParquetReplayProvider       ← new
```

The new provider would:
1. Accept `date`, `data_dir`, `tick_filter` (symbol set), `market_map` (symbol → TSE/OTC)
2. For each symbol in `tick_filter`, read `{data_dir}/{date}/{symbol}.parquet`
3. Filter to `Type == "Trade"` rows
4. Convert prices to `int * 10000`, times to `match_time_str` / `match_time_us`
5. Join each trade with its closest Depth row for bid/ask/trade_at
6. Yield `MarketTick` objects in global time order via heap merge

The rest of the pipeline (`replay_session`, signals, execution, reporting) would work unchanged — it only sees `MarketTick` objects.

---

## 5. Summary

| Area | Verdict |
|---|---|
| Can it work? | **Yes** — all fields needed by the pipeline are present or derivable |
| Biggest win | Typed columnar format eliminates brittle text parsing; 5-level book enables future signals |
| Biggest risk | Price float→int conversion precision; missing market/status_code metadata needs confirmation |
| Implementation effort | Medium — new `ParquetReplayProvider` + conversion layer; no changes to core engine |
| Breaking changes to existing flow | None — additive new provider behind the existing `MarketDataProvider` interface |
