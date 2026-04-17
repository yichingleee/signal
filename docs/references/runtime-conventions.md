# Runtime Conventions

## Directory Layout

The Python CLIs support environment-based default paths and still preserve the original
relative fallbacks.

Path resolution order for `--data-dir`, `--files-dir`, and `--group-file`:

1. explicit CLI flag value
2. environment variable (`TW_SIGNAL_DATA_DIR`, `TW_SIGNAL_FILES_DIR`, `TW_SIGNAL_GROUP_FILE`)
3. legacy relative fallback (`./data/`, `./files/`, `./files/group.csv`)

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

### Single-day replay

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date YYYYMMDD \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

### Batch replay

```bash
uv run python -m tw_signal_engine.cli.run_batch_replay \
  --start YYYYMMDD \
  --end YYYYMMDD \
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

### Replay files

- `TSEQuote.YYYYMMDD`
- `OTCQuote.YYYYMMDD`

The parser expects `Trade,...` rows and optional paired depth rows. Missing files are silently skipped by the low-level iterators, so missing-market situations can degrade coverage without raising a hard startup error.

## Price And Time Conventions

- internal price unit: integer `price * 10000`
- `match_time_str`: wall-clock integer timestamp such as `91500000000`
- `match_time_us`: microseconds since midnight
- VWAP is stored internally in scaled-price units, not as a decimal currency string

## History Window Convention

`load_history_window()` scans up to 21 sessions ending at the replay date:

- slot `0`: target replay date
- slots `1..20`: prior sessions used for history averages

Group and single screening averages use the prior 20 sessions, not the target day.

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
uv run pytest tests/golden -m golden -q
uv run ruff check src tests
uv run mypy src
```
