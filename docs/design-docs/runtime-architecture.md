# Runtime Architecture

## Purpose

`tw_signal_engine` replays archived Taiwan equity tick files for one trading day, applies deterministic screening and signal logic, manages simulated positions, and emits CSV outputs. Daily and batch replay support two explicit market-data sources: parquet, which is the default, and legacy text, which remains a compatibility path.

## Inputs

- `cfg/parameter.cfg`: legacy INI strategy config
- `Symbols_YYYYMMDD.csv` under `--files-dir` (or `TW_SIGNAL_FILES_DIR` / `./files/` fallback)
- `group.csv` from `--group-file` (or `TW_SIGNAL_GROUP_FILE` / `./files/group.csv` fallback)
- parquet replay root under `--data-dir`: `TWSE/YYYYMMDD.parquet` and `TPEX/YYYYMMDD.parquet`
- `TSEQuote.YYYYMMDD` and `OTCQuote.YYYYMMDD` under `--data-dir` for `--data-source text` 
  (or `TW_SIGNAL_DATA_DIR` / `./data/` fallback)

Detailed file conventions live in [docs/references/runtime-conventions.md](../references/runtime-conventions.md).

## Session Lifecycle

### 1. Config and references

`run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py`:

1. Loads the legacy INI file through `config/load_legacy_ini.py`.
2. Normalizes it into typed Pydantic models through `config/normalize_strategy_config.py`.
3. Loads the symbol reference map, derives previous-day limit-up flags, and loads group membership.
4. Reads `Strategy.trade_mode` (`long|short`) plus signal switches:
   - preferred/default path: `trade_mode=long` with `SignalA` and `SignalAShort` concurrently
   - legacy compatibility path: `trade_mode=short` (historical short-only behavior)

### 2. History window build

The history loader is selected by `--data-source`.

- `market_data/parquet_history_loader.py` reads prior-session parquet files for the default parquet path.
- `market_data/load_history_window.py` reads prior-session text files for the compatibility text path.
- parquet history optionally uses binary day caches (`market_data/parquet_history_cache.py`) keyed by market/date and source-file freshness.
- Index `0` is the most recent prior session.
- Up to 20 prior sessions are used by screening averages.
- Both OTC and TSE histories are loaded separately, then merged in `replay_session.py`.
- batch replay uses rolling providers for both sources:
  - text: `market_data/rolling_history.py`
  - parquet: `market_data/parquet_rolling_history.py`
- `--no-cache` disables both cache reads and cache writes.

The history loader builds:

- cumulative intraday volume trackers
- cumulative intraday trading-value trackers
- per-session total trading value by symbol

### 3. Screening initialization

`StrongGroupEvaluator.initialize_validity()` precomputes:

- whether each symbol clears the monthly trading-value floor
- per-group monthly trading-value sums
- per-group valid member counts

`StrongSingleEvaluator` is instantiated as well. When enabled, it now precomputes its monthly trading-value validity so replay-universe construction can include its candidates.

### 4. Replay universe build

`replay/build_replay_universe.py` now unions:

- strong-group symbols
- prevalidated strong-single symbols when that screen is enabled
- `0050`

`0050` is always included for market gating.
In `trade_mode=short` legacy compatibility mode, strong-single does not drive entries.

Parquet replay may feed `0050` market-gate state from the text proxy stream or day-bar open fallback because the parquet tick feed omits `00*` symbols.

### 5. Replay provider

The replay provider is selected by `--data-source` unless a caller injects a custom `MarketDataProvider`:

- parquet: `ParquetReplayProvider` reads `TWSE` and `TPEX` parquet files, validates the required schema, applies parquet source filters, tags engine markets as `TSE` / `OTC`, and yields ticks in chronological order.
- text: `FileReplayProvider` reads `TSEQuote` and `OTCQuote` files and uses `replay/merge_market_streams.py` to merge them in `match_time_str` order.

Per yielded tick the provider path also:

- attaches the previous-day limit-up flag
- marks `volatility_pause=True` for the first three trades per symbol

### 6. Per-tick processing

For each merged trade tick:

1. Update `0050` market-gate state. A disable event finalizes any open positions, generates reports, and terminates the session early.
2. Skip non-trade ticks and `00xx` symbols after the market-gate update.
3. Update per-symbol intraday state through `state/IndexCalc`:
   - VWAP
   - day high
   - day low
4. If a position is open, process exits first through `execution/trade_ledger.py`.
5. If still flat, evaluate screening:
   - long-side strong-single/strong-group path
   - short-side strong-group weakest-path when `SignalAShort` is enabled
   - in legacy `trade_mode=short`, strong-single entry contribution is disabled
6. Evaluate Signal A, Signal A Short, and Signal B.
   - Signal A: long state machine
   - Signal A Short: mirrored short state machine
   - legacy `trade_mode=short` maps Signal A behavior through the short-compat evaluator
7. If any signal triggers, apply entry filters through `execution/should_enter()`.
8. Execute the selected entry with side-aware trade mode, stage take-profit orders, and write order-log rows immediately.
   - positions use signed quantity (`+` long / `-` short)

### 7. End-of-day closeout

After the stream ends, or immediately before an early market-gate return, `replay_session.py` force-closes any remaining positions by invoking the normal exit path with a sentinel end-of-day timestamp. It then writes:

- `order_log_YYYYMMDD.csv`
- `order_log_YYYYMMDD_<symbol>.csv`
- `report_trades.csv`
- `report_summary.csv`
- `report_by_category.csv`

`report_trades.csv` includes `DataSource` so analysts can distinguish parquet, text, and custom-provider output when reviewing differences.

If charts are enabled (default, unless `--no-charts` is set), the reporting pipeline also:

- keeps existing aggregate/day-level chart behavior (`len(trades) >= 2`)
- performs a second filtered stream pass for traded symbols only
- writes one per-symbol intraday timeline chart:
  - `chart_trade_day_<symbol>.png`
- writes a chart manifest:
  - `report_trade_day_charts.csv`

Per-symbol timeline charts show replay-granularity price, session cumulative VWAP, and labeled signal/entry/exit markers sourced from `TradeRecord` fields (including `exit_price`).

## Signal and Execution Ordering

The runtime has several ordering rules that matter for correctness:

- Exits are always evaluated before new entries on the same tick.
- Signal priority is deterministic: `SignalA` > `SignalAShort` > `SignalB`.
- Exit priority is:
  1. stop-loss
  2. time exit
  3. take-profit
  4. bailout
- Exit fill quotes are side-aware:
  - long closes on bid-side fallback to match
  - short closes on ask-side fallback to match
- Each symbol can have at most one open position at a time.

## Module Responsibilities

- `cli/`: daily and batch replay entrypoints
- `config/`: legacy config parsing and typed normalization
- `reference_data/`: static symbol and group inputs
- `market_data/`: replay-row parsing and history-window construction
- `replay/`: orchestration, market gating, file iteration, and merged stream control
- `screening/`: strong-group and strong-single qualification
- `signals/`: Signal A and Signal B state machines
- `execution/`: entry sizing plus exit mechanics
- `reporting/`: CSV writers and summary rollups
- `state/`: mutable per-session state
- `records/`: immutable data records

## Architecture Invariants

- Prices are stored internally as integer `price * 10000`.
- `match_time_str` is the canonical wall-clock tick timestamp.
- `match_time_us` is the canonical rolling-window timestamp.
- `text` and `parquet` are separate truth sources. Cross-source comparisons are diagnostics, not strict acceptance gates.
- The Python implementation preserves some parity-sensitive C++ behaviors; see [docs/references/parity-status.md](../references/parity-status.md).
- The main orchestration still lives in one file, `replay/replay_session.py`; the follow-up split is tracked in [docs/exec-plans/tech-debt-tracker.md](../exec-plans/tech-debt-tracker.md).
