# Runtime Conventions

## Directory Layout

Daily and batch replay default to `--data-source parquet`. If `--data-dir` is omitted under parquet mode, the CLIs use `$TW_SIGNAL_PARQUET_DATA_DIR` when set and fall back to `./data/`.

Preferred parquet layout:

```text
market-data/
├── tick-data/
│   ├── TWSE/
│   │   └── YYYYMMDD.parquet
│   └── TPEX/
│       └── YYYYMMDD.parquet
├── symbols/
│   └── Symbols_YYYYMMDD.csv
└── group/
    └── group-ver20260329.csv
```

The Python CLIs support path defaults from both explicit CLI flags and environment:

- `--data-dir`: explicit value, otherwise `TW_SIGNAL_PARQUET_DATA_DIR` (parquet source), otherwise `TW_SIGNAL_DATA_DIR`, otherwise `./data/`
- `--files-dir`: explicit value, otherwise `TW_SIGNAL_FILES_DIR`, otherwise `./files/`
- `--group-file`: explicit value, otherwise `TW_SIGNAL_GROUP_FILE`, otherwise `./files/group.csv`

The legacy text source remains available with `--data-source text`.

Classic `exec/` working-directory layout:

```text
exec/
├── cfg/
│   └── parameter.cfg
├── data/
│   ├── TSEQuote.YYYYMMDD
│   └── OTCQuote.YYYYMMDD
├── files/
│   ├── Symbols_YYYYMMDD.csv
│   └── group.csv
└── log/
    └── YYYYMMDD_HHMM/
```

## CLI Entry Points

### Single-day replay, parquet source

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date YYYYMMDD \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
  --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
  --config exec/cfg/parameter.cfg
```

### Batch replay, parquet source

```bash
uv run python -m tw_signal_engine.cli.run_batch_replay \
  --start YYYYMMDD \
  --end YYYYMMDD \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
  --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
  --config exec/cfg/parameter.cfg
```

### Legacy text source

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date YYYYMMDD \
  --data-source text \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

## Input Files

### `parameter.cfg`

- legacy INI format
- parsed case-sensitively
- normalized into typed config models before runtime use
- preferred/default short-side usage:
  - keep `Strategy.trade_mode=long`
  - set `SignalAShort.enabled=true` to run short Signal A concurrently
- `Strategy.trade_mode=short` is a legacy compatibility mode and remains supported for historical short-only behavior
- `SignalB` is currently long-only; in `Strategy.trade_mode=short` compatibility mode it is intentionally disabled
- split invariants are validated at config normalization:
  - `take_profit_splits > 0`
  - `reserve_limit_up_splits >= 0`
  - `take_profit_splits + reserve_limit_up_splits > 0`

### `Symbols_YYYYMMDD.csv`

- one file per replay date
- used for previous close, limit-up/down prices, market, and security metadata
- loader accepts:
  - `utf-8-sig`
  - `cp950`
  - `big5hkscs`

### `group.csv`

- format: `GroupName,Symbol,StockName`
- parsed as UTF-8 with BOM support
- CLI default can point to any compatible CSV path via `TW_SIGNAL_GROUP_FILE`
  (for example, versioned files such as `group-verYYYYMMDD.csv`)

### Replay files, parquet

- `TWSE/YYYYMMDD.parquet`
- `TPEX/YYYYMMDD.parquet`

Parquet source contract:

- required replay columns: `symbol`, `time`, `matchFlag`, `tradePrice`, `tradeVolume`, `buyPrice1`, `sellPrice1`
- required history/filter columns: `symbol`, `time`, `matchFlag`, `tradePrice`, `tradeVolume`
- market mapping is `TSE -> TWSE` and `OTC -> TPEX`
- accepted replay rows satisfy `matchFlag == "Y"`, `time >= 09:00:00.000000`, and `tradeVolume > 0`
- history rows use the same `matchFlag` and time filter and reject negative `tradeVolume`
- `Symbols_YYYYMMDD.csv` is required for parquet replay; missing symbol files are guarded with a `[GUARD]` skip message

### Replay files, legacy text

- `TSEQuote.YYYYMMDD`
- `OTCQuote.YYYYMMDD`

The parser expects `Trade,...` rows and optional paired depth rows. Missing files are silently skipped by the low-level iterators, so missing-market situations can degrade coverage without raising a hard startup error.

Parquet and text are separate replay sources. Cross-source comparisons are diagnostics; strict equality between `report_trades.csv` outputs is not a parquet acceptance gate.

## Price And Time Conventions

- internal price unit: integer `price * 10000`
- `match_time_str`: wall-clock integer timestamp such as `91500000000`
- `match_time_us`: microseconds since midnight
- VWAP is stored internally in scaled-price units, not as a decimal currency string

## History Window Convention

History loaders scan up to 20 prior sessions before the replay date:

- slot `0`: most recent prior session
- slot `19`: oldest prior session

Group and single screening averages use the prior sessions, not the target day.

## Output Files

### Order logs

- `order_log_YYYYMMDD.csv`
- `order_log_YYYYMMDD_<symbol>.csv`

Columns:

- `Action`
- `Symbol`
- `Time`
- `Price`
- `Cash`
- `SymbolCash`
- `SignalType`
- `EnterCause`
- `LeaveCause`
- `RemainingQty`
- `GroupInfo`

### Trade report

`report_trades.csv` contains:

- symbol and signal metadata
- entry and exit times
- leave cause
- PnL and return percentage
- holding duration
- strong-group metadata such as group rank and member rank
- entry snapshots such as entry price, entry VWAP, and day high
- market context fields such as `0050` open change and entry-time change
- `DataSource`, indicating `parquet`, `text`, or `provider`

### Summary reports

- `report_summary.csv`: total trades, PnL, win rate, drawdown, and average holding metrics
- `report_by_category.csv`: rollups by signal type, enter cause, and leave cause

### Chart artifacts

When charts are enabled (default), daily replay output includes:

- aggregate charts (existing files such as `chart_equity_curve.png`, `chart_pnl_distribution.png`, etc.) when there are at least 2 trades
- per-traded-symbol timeline charts for any day with at least 1 completed trade:
  - `chart_trade_day_<symbol>.png`
- per-symbol chart manifest:
  - `report_trade_day_charts.csv`

Per-symbol timeline charts annotate:

- replay-granularity traded-price line
- session cumulative VWAP line
- signal markers with signal type and enter-cause reason
- entry markers with enter-cause reason
- exit markers with leave-cause reason

`--no-charts` remains the global kill-switch and disables both aggregate and per-symbol charts.

## Validation Commands

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```
