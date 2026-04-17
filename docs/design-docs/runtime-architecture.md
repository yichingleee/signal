# Runtime Architecture

## Purpose

`tw_signal_engine` replays archived Taiwan equity tick files for one trading day, applies deterministic screening and signal logic, manages simulated positions, and emits CSV outputs. The current runtime is batch/replay only; live UDP, Redis, and web-serving designs from older notes are not part of the Python implementation in this repository.

## Inputs

- `exec/cfg/parameter.cfg`: legacy INI strategy config
- `exec/files/Symbols_YYYYMMDD.csv`: symbol reference data for the replay date
- `exec/files/group.csv`: group membership
- `exec/data/TSEQuote.YYYYMMDD` and `exec/data/OTCQuote.YYYYMMDD`: replay streams
- `artifacts/baseline/`: archived golden parity outputs, used by tests rather than by the runtime

Detailed file conventions live in [docs/references/runtime-conventions.md](../references/runtime-conventions.md).

## Session Lifecycle

### 1. Config and references

`run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py`:

1. Loads the legacy INI file through `config/load_legacy_ini.py`.
2. Normalizes it into typed Pydantic models through `config/normalize_strategy_config.py`.
3. Loads the symbol reference map, derives previous-day limit-up flags, and loads group membership.
4. Reads `Strategy.trade_mode` (`long|short`) to control screening direction, Signal A mirror behavior, and execution quote side.

### 2. History window build

`market_data/load_history_window.py` scans the replay directory for up to 21 sessions at or before the target date.

- Index `0` is the target date.
- Indices `1..20` are the 20-session history used by screening averages.
- Both OTC and TSE histories are loaded separately, then merged in `replay_session.py`.

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
In short mode, strong-single does not drive entries.

### 5. Stream merge

`replay/merge_market_streams.py` merges OTC and TSE streams in `match_time_str` order.

Per yielded tick it also:

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
5. If still flat, evaluate strong-single and strong-group screening.
   - in short mode, strong-group weakest-path is used and strong-single entry contribution is disabled
6. Evaluate Signal A and Signal B.
   - Signal A uses mirrored near/rejection logic in short mode
7. If either signal triggers, apply entry filters through `execution/should_enter()`.
8. Execute the entry, stage take-profit orders, and write order-log rows immediately.
   - positions use signed quantity (`+` long / `-` short)

### 7. End-of-day closeout

After the stream ends, or immediately before an early market-gate return, `replay_session.py` force-closes any remaining positions by invoking the normal exit path with a sentinel end-of-day timestamp. It then writes:

- `order_log_YYYYMMDD.csv`
- `order_log_YYYYMMDD_<symbol>.csv`
- `report_trades.csv`
- `report_summary.csv`
- `report_by_category.csv`

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
- If both Signal A and Signal B trigger on the same tick, the runtime enters as `SignalA`.
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
- The Python implementation preserves some parity-sensitive C++ behaviors; see [docs/references/parity-status.md](../references/parity-status.md).
- The main orchestration still lives in one file, `replay/replay_session.py`; the follow-up split is tracked in [docs/exec-plans/tech-debt-tracker.md](../exec-plans/tech-debt-tracker.md).
