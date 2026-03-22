# Replay Runtime Optimization Research

## Scope

This report studies the Python replay engine under `src/tw_signal_engine/` with one goal: give future optimization work a concrete map of where runtime goes, which code paths matter under the committed config, and how to benchmark improvements without losing rigor.

The analysis covers:

- startup and reference-data loading
- 21-session history-window construction
- current-day replay parsing and merge
- screening, feature/state updates, signal evaluation, execution, and reporting
- batch-scale implications for multi-day replays

The archived C++ runtime is used only as an optimization reference where it exposes techniques the Python port does not yet use, such as binary history caches.

## Current Runtime Shape

Under the committed `exec/cfg/parameter.cfg`, the active path is narrower than the full codebase:

- `SignalA=true`
- `SignalB=false`
- `StrongGroup=true`
- `StrongSingle=false`

That means current optimization work should prioritize:

1. history-window loading
2. current-day parsing and merge
3. strong-group screening and Signal A hot-path work

`SignalB` and strong-single still matter for future-proofing, but they are not the main runtime drivers under the current config.

## Files And Functions Inspected

The runtime-critical code paths are:

- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/replay/iterate_market_file.py`
- `src/tw_signal_engine/replay/merge_market_streams.py`
- `src/tw_signal_engine/market_data/load_history_window.py`
- `src/tw_signal_engine/market_data/parse_format6_replay_rows.py`
- `src/tw_signal_engine/screening/evaluate_strong_group.py`
- `src/tw_signal_engine/screening/evaluate_strong_single.py`
- `src/tw_signal_engine/screening/top_volume_pool.py`
- `src/tw_signal_engine/signals/evaluate_signal_a.py`
- `src/tw_signal_engine/signals/evaluate_signal_b.py`
- `src/tw_signal_engine/execution/*.py`
- `src/tw_signal_engine/reporting/*.py`

Supporting references:

- `exec/cfg/parameter.cfg`
- `docs/design-docs/runtime-architecture.md`
- `docs/product-specs/current-strategy-spec.md`
- `legacy/cpp/QuoteSv/QuoteSv.cpp`
- `src/tw_signal_engine/market_data/build_volume_caches.py`

## Methodology

This report combines static code inspection with targeted measurements taken from this repository workspace on 2026-03-22.

Measured commands used:

```bash
PYTHONPATH=src python -u -m tw_signal_engine.cli.run_daily_replay \
  --date 20251231 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

```bash
PYTHONPATH=src python -u - <<'PY'
import time
from tw_signal_engine.market_data.load_history_window import load_history_window
t0 = time.perf_counter()
load_history_window("OTC", "20260211", "exec/data")
print(round((time.perf_counter() - t0) * 1000, 1))
PY
```

```bash
PYTHONPATH=src python -u - <<'PY'
import time
from tw_signal_engine.replay.iterate_market_file import iterate_market_file
for label, market, date in [
    ("TSE_no_filter", "TSE", "20260225"),
    ("OTC_no_filter", "OTC", "20260225"),
]:
    t0 = time.perf_counter()
    count = 0
    for _ in iterate_market_file(market, date, "exec/data"):
        count += 1
        if count >= 100000:
            break
    dt = time.perf_counter() - t0
    print(label, count, dt, count / dt)
PY
```

The measurements are directionally useful and internally consistent, but they are not lab-grade. CPU model, page-cache state, and thermal throttling were not pinned in a formal benchmark harness. The benchmarking section later in this document explains how to tighten that up.

## Workload Characteristics

### Reference and group data

- `Symbols_20260211.csv`: 45,934 rows, about 2.3 MB
- `group.csv`: 2,085 rows
- Group universe:
  - 1,795 unique group-member symbols
  - 150 groups
  - 2,082 total memberships
  - average memberships per symbol: about 1.16
  - largest group size: 105 symbols

Membership fanout is low:

- 1,530 symbols belong to 1 group
- 241 symbols belong to 2 groups
- 23 symbols belong to 3 groups
- 1 symbol belongs to 4 groups

That matters because strong-group work scales more with group size than with cross-group fanout.

### Replay-day sizes

Representative replay-day sizes in `exec/data/`:

| Date | Total replay bytes | Total trade lines |
| --- | ---: | ---: |
| 2025-12-31 | 1.92 GB | 1,678,259 |
| 2026-02-11 | 2.17 GB | 1,742,718 |
| 2026-02-23 | 2.41 GB | 2,149,307 |
| 2026-02-25 | 2.83 GB | 2,405,601 |

### History-window sizes

For late-period dates, `load_history_window()` scans 21 sessions per market:

| Date | Market | History files | History bytes | History trade lines |
| --- | --- | ---: | ---: | ---: |
| 2026-02-11 | OTC | 21 | 9.40 GB | 9,898,707 |
| 2026-02-11 | TSE | 21 | 41.33 GB | 35,245,288 |
| 2026-02-23 | OTC | 21 | 9.39 GB | 9,826,286 |
| 2026-02-23 | TSE | 21 | 41.45 GB | 35,441,117 |
| 2026-02-25 | OTC | 21 | 9.48 GB | 9,837,107 |
| 2026-02-25 | TSE | 21 | 42.12 GB | 35,805,403 |

The cold-start problem is visible immediately: a single late-period replay day rereads roughly 50 to 52 GB of history text before the current-day replay loop begins.

## Measured Runtime Findings

### Clean end-to-end daily sample: 2025-12-31

Measured directly from `run_daily_replay()`:

| Stage | Time |
| --- | ---: |
| `getTickData OTC` | 3,909 ms |
| `getTickData TSE` | 13,954 ms |
| `getGroup` | 5 ms |
| `readFileMerged` | 39,389 ms |
| `TOTAL` | 57,722 ms |

Other outputs from the same run:

- `tickFilter: 1796 symbols`
- `Total ticks processed: 1,322,689`
- no trades completed on that date under the committed config

Implications:

- When the history window is shallow, the current-day merged replay loop is the dominant cost.
- Even on the smallest available day, the engine already spends about 17.9 seconds building history before the replay loop starts.

### Clean late-period history samples: 2026-02-11

Isolated `load_history_window()` measurements:

| Market | Time | Workload |
| --- | ---: | --- |
| OTC | 107,821.3 ms | 21 files, 9.40 GB, 9,898,707 trade lines |
| TSE | 460,205.3 ms | 21 files, 41.33 GB, 35,245,288 trade lines |

Combined implication:

- about 568,026.6 ms, or about 9.5 minutes, of history loading before the replay loop even begins on this late-period date

Implications:

- Once the history window is full, history loading becomes the dominant runtime cost.
- TSE is the clear cold-start bottleneck because it carries most of the history bytes.
- Any optimization that does not materially reduce history rebuild work will have limited effect on late-period daily runtime and month-scale batch runtime.

### Startup work outside history loading is small

Measured on 2026-02-11:

| Operation | Time |
| --- | ---: |
| `load_symbol_reference()` | 240.3 ms |
| `derive_prev_day_limit_up()` | 480.9 ms |
| `load_group_membership()` | 22.8 ms |

That means optimization effort should not focus on config parsing or reference CSV I/O first.

### Current-day parser microbenchmarks

First 100,000 emitted ticks from 2026-02-25:

| Benchmark | Time | Throughput |
| --- | ---: | ---: |
| `TSE` no filter | 4.616 s | 21,662 ticks/s |
| `TSE` group-symbol filter | 3.646 s | 27,425 ticks/s |
| `OTC` no filter | 2.870 s | 34,844 ticks/s |
| `OTC` group-symbol filter | 2.856 s | 35,019 ticks/s |

Interpretation:

- `tick_filter` helps on TSE, but not by an order of magnitude.
- That is expected because `iterate_market_file()` still reads every line from the text file. The filter mostly avoids full `MarketTick` construction for skipped symbols; it does not avoid file scan I/O.
- The current group universe is only about 1,796 symbols out of roughly 45k reference symbols, so symbol filtering is already aggressive in logical terms. The remaining cost is dominated by scanning and parsing text.

### cProfile on the parser path

`iterate_market_file("TSE", "20260225")` for 100,000 emitted ticks:

- total profiled runtime: 9.24 s
- top cumulative functions:
  - `iterate_market_file()`
  - `parse_trade_line()`
  - `_get_best_prices()`
  - `MarketTick` / `QuotePair` object construction
  - `TextIOWrapper.readline()`

The largest parser-specific contributors were:

- `parse_trade_line()`: 6.34 s cumulative
- `_get_best_prices()`: 3.18 s cumulative
- `readline()`: 1.28 s cumulative

This confirms that current-day replay is dominated by:

1. text parsing
2. best-bid/best-ask extraction from depth lines
3. per-tick object allocation

## Runtime Cost Map By Subsystem

### 1. Config and reference data

Relevant code:

- `config/load_legacy_ini.py`
- `config/normalize_strategy_config.py`
- `reference_data/load_symbol_reference.py`
- `reference_data/derive_prev_day_limit_up.py`
- `reference_data/load_group_membership.py`

Runtime assessment:

- not a bottleneck
- total startup cost is well under 1 second in the measured late-period sample

Optimization priority:

- low

### 2. History-window construction

Relevant code:

- `market_data/load_history_window.py`
- `market_data/parse_format6_replay_rows.py`
- `market_data/market_data_records.py`
- `replay/replay_session.py`

This is the primary bottleneck for late-period replays.

### Why it is expensive

`load_history_window()` does all of the following for every replay day:

1. scans the data directory for eligible dates
2. picks up to 21 files per market
3. reads every line of every selected text file
4. fully parses every `Trade,...` line into a `MarketTick`
5. updates cumulative volume trackers
6. updates cumulative trading-value trackers
7. updates per-day total trading value

### Important waste in the current implementation

#### A. The current day is parsed into history slot `0` even though screening uses only days `1..20`

`load_history_window()` returns 21 slots and includes the target replay date at index `0`.

But both `StrongGroupEvaluator` and `StrongSingleEvaluator` only read `range(1, DAY_PER_MONTH + 1)`.

That means:

- the replay date is parsed once during history construction
- then parsed again during `readFileMerged()`
- the history copy of the replay date is currently unused by the screening logic

This is a direct and low-risk opportunity to remove duplicated work.

#### B. `val_cum` is built but not used

`load_history_window()` constructs:

- `vol_cum`
- `val_cum`
- `trading_val`

In the Python runtime, only `vol_cum` and `trading_val` are used. `val_cum` is not consumed later in `replay_session.py` or the screening modules.

So current history loading does extra per-tick work and stores extra data structures that the replay path does not read.

#### C. History parsing uses the full current-day `MarketTick` parser

Inside `_parse_vol_cum_from_file()`, history loading calls:

```python
tick = parse_trade_line(line, "", "")
```

For history construction, only these fields are needed:

- symbol
- match time
- price
- quantity

But `parse_trade_line()` still constructs a full `MarketTick`, including bid/ask arrays and other fields that are irrelevant for history loading.

This is avoidable object churn in the most expensive stage of the system.

### Expected optimization impact

This stage is the highest-leverage target by far.

Any of the following should materially improve runtime:

- persistent binary history caches
- skipping history slot `0`
- eliminating `val_cum`
- using a lightweight history parser
- reusing neighboring-day history windows in batch mode

### 3. Current-day replay parsing and merge

Relevant code:

- `replay/iterate_market_file.py`
- `replay/merge_market_streams.py`
- `market_data/parse_format6_replay_rows.py`

### Current characteristics

- full text scan of OTC and TSE replay files
- line-by-line `readline()` processing
- `Trade`/`Depth` pairing in Python
- best bid/ask parsing with repeated string searching and digit scanning
- `MarketTick` allocation per emitted event

### Important findings

#### A. `tick_filter` reduces parsing work, but not scan work

`iterate_market_file()` still reads the entire file and checks each candidate line. The filter only avoids full parsing for skipped symbols.

That means:

- symbol filtering helps, especially on TSE
- but it cannot solve the core text-scan cost on its own

#### B. Best-price extraction is expensive

`_get_best_prices()` is one of the heaviest parser helpers in the cProfile output. It repeatedly uses:

- `find()`
- `split()`
- per-character `isdigit()` loops

This is a clear candidate for a faster parser, ideally on bytes or via a specialized fast path for the exact depth format present in the replay files.

#### C. `MarketTick` allocation is heavier than necessary

Each `MarketTick` contains:

- one `match` `QuotePair`
- five bid `QuotePair`s
- five ask `QuotePair`s

Current replay logic mostly consumes only:

- `tick.match`
- `tick.bid[0]`
- `tick.ask[0]`
- a few scalar flags

The full 5x5 depth object structure is expensive relative to the actual strategy needs.

### 4. Screening and feature computation

Relevant code:

- `screening/evaluate_strong_group.py`
- `screening/evaluate_strong_single.py`
- `signals/evaluate_signal_a.py`
- `signals/evaluate_signal_b.py`
- `state/group_state.py`
- `state/rolling_window.py`
- `market_data/market_data_records.py`

### Current-config hot path

Under the committed config, the per-tick strategy path is effectively:

- `IndexCalc.calc()`
- `StrongGroupEvaluator.on_tick()`
- `evaluate_signal_a()`
- exit checks

`StrongSingle` and `SignalB` are disabled, but there is still some avoidable overhead from disabled-feature calls.

### Strong-group complexity notes

`StrongGroupEvaluator.on_tick()` contains several patterns that are fine today but are likely to become the next bottleneck once history loading is fixed:

- `_group_percentage_chg()` loops over all group members
- `_group_percentage_chg()` is called multiple times per group per tick
- 20-day historical volume sums are recomputed with repeated `query()` calls
- `GroupRank.get_rank()`, `is_top_n()`, and `iter_ranked()` sort maps repeatedly

Given the current dataset:

- average group size is modest, about 13.9 members
- largest group size is 105 members
- most symbols belong to only one group

So this is probably not the first runtime fire, but it is the first CPU-side optimization target after history I/O is addressed.

### Disabled feature overhead that still exists

Even with current config:

- `StrongSingleEvaluator.on_tick()` is still called and returns immediately
- `SignalBState` is still lazily constructed per symbol
- `evaluate_signal_b()` is still called and returns immediately

This is not the main bottleneck, but it is unnecessary work in the hottest loop and should be gated outside the loop for free wins.

### `NumTracker` is inefficient for its current use

`merge_market_streams()` updates `NumTracker` on every emitted tick.

`NumTracker`:

- stores timestamps in a Python list
- expires old elements with `pop(0)`

That is O(n) per expiration.

The current strategy only uses `trade_count <= 3` to emulate a volatility-pause/disposition guard, so this tracker is a candidate for simplification or a `deque`-based rewrite.

### 5. Execution and reporting

Relevant code:

- `execution/*.py`
- `reporting/write_order_log_csv.py`
- `reporting/build_trade_report_rows.py`
- `reporting/build_daily_summary.py`
- `reporting/build_category_summary.py`

Runtime assessment:

- currently secondary
- execution logic is small relative to parsing and screening
- reporting cost is low on low-trade days

One avoidable I/O cost exists:

- `OrderLogWriter.write_entry()` and `write_leave()` flush the main CSV on every event

This is not the main problem for today’s workload, but it should become buffered if trade counts rise or if replay speed becomes high enough that output flushing starts to matter.

## High-Impact Optimization Opportunities

The list below is ordered by expected payoff under the committed config.

### P0. Add a persistent history cache

Evidence:

- `src/tw_signal_engine/market_data/build_volume_caches.py` is currently a placeholder
- `legacy/cpp/QuoteSv/QuoteSv.cpp` already contains a `VOLCACHE` design

Why it matters:

- late-period single-day cold start rereads about 50 GB of history text
- January 2026 batch replay would reread about 623.74 GB total under the current implementation

Recommended direction:

- persist the minimal history data needed by screening
- load cached binary arrays instead of reparsing text
- benchmark both cold-cache build time and warm-cache replay time

### P0. Stop loading history slot `0`

Why it matters:

- current day is parsed once into history and then again during replay
- screening code only uses history slots `1..20`

Expected effect:

- saves one full replay day of history parsing per market
- removes duplicate work with no clear behavior dependency in the current code

### P0. Stop building unused `val_cum`

Why it matters:

- `val_cum` is returned by `load_history_window()` but not used by the Python runtime
- every history tick currently updates both volume and trading-value cumulative trackers

Expected effect:

- less per-tick work during the dominant history stage
- lower memory usage

### P0. Add a lightweight history parser

Why it matters:

- history loading only needs symbol, timestamp, price, and qty
- it currently pays full `MarketTick` construction cost

Expected effect:

- less object churn
- less Python-level work inside the most expensive stage

### P1. Fix replay-universe construction

Current code in `replay_session.py` does:

```python
set(strong_group.symbol_is_valid.keys())
```

That includes every symbol seen during validity initialization, not only the symbols whose validity flag is `True`.

Current evidence:

- the clean 2025-12-31 run reported `tickFilter: 1796 symbols`
- that matches the full group universe plus `0050`

Why it matters:

- invalid strong-group symbols are still read from current-day replay files
- `StrongGroupEvaluator.on_tick()` immediately returns `False` for them
- the parse cost is paid even though the strategy does not use those symbols

Expected effect:

- direct reduction in current-day parser work

### P1. Gate disabled features outside the hot loop

Current unnecessary work:

- `strong_single.on_tick(...)` call when strong-single is disabled
- `SignalBState` setup and `evaluate_signal_b(...)` call when `SignalB` is disabled

Expected effect:

- small but free improvement
- cleaner hot-path code for future profiling

### P1. Reduce parser object churn

Candidates:

- replace full bid/ask arrays with best-bid/best-ask fields in the replay-only tick type
- parse history rows into plain tuples or slot-based structs
- avoid repeated string splitting where a positional parser is sufficient

### P1. Rewrite depth parsing

Current hotspot:

- `_get_best_prices()` is one of the top cumulative parser costs

Candidate approaches:

- byte-oriented parser
- purpose-built best-price scanner
- native extension or Rust/Cython helper if Python-only improvements are insufficient

### P2. Incrementalize strong-group calculations

Current repeated work:

- repeated group-member scans
- repeated sorting in `GroupRank`
- repeated 20-day historical aggregation per candidate tick

Candidate direction:

- keep rolling per-group aggregate percent-change state
- maintain ranks incrementally rather than sorting on demand

This becomes important after history loading is addressed.

### P2. Replace `NumTracker` list with `deque` or a simpler first-N tracker

Why it matters:

- `pop(0)` is O(n)
- the current strategy only needs a very small early-trade threshold

### P3. Buffer reporting writes

Why it matters:

- low current payoff
- good cleanup once replay loop speed improves

## Batch-Scale Findings

`run_batch_replay.py` is a sequential loop over `run_daily_replay()`. There is no cross-day cache reuse.

That has major consequences.

### Late-February mini-batch: 2026-02-11 to 2026-02-25

- 4 replay days
- unique replay files read for current-day loops: 9.86 GB
- history files reread under current implementation: 204.33 GB
- total text volume if run as-is: 214.19 GB

### January 2026 month-scale batch: 2026-01-02 to 2026-01-30

- 21 replay days
- unique replay-day bytes: 50.64 GB
- repeated history-window bytes under current implementation: 573.10 GB
- total text volume if run as-is: 623.74 GB

Interpretation:

- month-scale runtime today is dominated by repeated history reparse, not by current-day replay loops
- a history cache or sliding-window reuse strategy is not an optimization detail; it is the difference between a usable monthly benchmark and an unnecessarily expensive one

## Benchmarking Plan For Future Optimization Work

The rest of this report focuses on how to benchmark changes in a way that will stay useful over time.

### Benchmarking Principles

Always record:

- exact date range
- exact command
- whether the run was cold-cache or warm-cache
- Python version
- whether the code was run via `uv run` or `PYTHONPATH=src python`
- wall time
- stage times
- replay bytes and history bytes
- emitted tick count
- completed trade count

Important note:

- do not use `uv run` inside the timed loop if you care about clean runtime numbers
- either install once before timing or run with `PYTHONPATH=src python ...`

Recommended timing primitive inside code:

- `time.perf_counter_ns()`

Recommended output:

- structured JSON or CSV alongside human-readable logs

## Per-Stock Benchmarks

Purpose:

- isolate hot-loop cost without monthly history dominating every measurement

Suggested benchmark types:

### 1. Stock loop only

Build history once in-process, then replay only:

- one liquid symbol
- one mid-liquidity symbol
- one low-liquidity symbol
- always include `0050` because market-gate logic depends on it

Use:

```python
tick_filter = {symbol, "0050"}
```

Metrics:

- emitted ticks
- wall time
- ticks per second
- ns per emitted tick
- entries and exits if strategy logic is enabled

### 2. Stock cold start

Measure the same symbol-specific replay but include:

- reference-data load
- history build
- replay loop

Why both are needed:

- loop-only shows parser and strategy hot-path improvements
- cold-start shows whether optimization work helps the real user workflow

## Per-Day Benchmarks

Use a fixed date ladder with different workload shapes.

Recommended baseline dates in this repository:

| Tier | Date | Why |
| --- | --- | --- |
| small | 2025-12-31 | shallow history window, clean full-sample runtime available |
| medium | 2026-02-23 | full 21-day history window, mid-sized replay day |
| large | 2026-02-25 | full 21-day history window, one of the largest replay days in the dataset |

Track these stage timings separately:

- config + references
- OTC history load
- TSE history load
- history merge
- screening init
- merged replay loop
- final closeout
- report generation
- total

Suggested acceptance rule for future optimizations:

- require at least 3 runs per date
- compare medians
- treat anything under 5 percent as noise unless it is reproduced on all tiers

## Per-Month Benchmarks

Recommended fixed batch:

- 2026-01-02 through 2026-01-30

Why:

- exactly 21 trading days are available in the repository for that range
- it is long enough to expose repeated history work

Metrics to record:

- batch wall time
- average day wall time
- P50, P95, and max day wall time
- total replay bytes
- total reread history bytes
- total emitted ticks
- total trades

For month-scale benchmarking, record two modes:

### 1. Cold batch

Start a fresh process and time the whole month.

This is the user-facing baseline for current code.

### 2. Warm or cached batch

Use the same date range after:

- persistent history cache is built, or
- in-process sliding windows are enabled

This is the number that should move the most after the first major optimization pass.

## Recommended Benchmark Harness Changes

To make optimization work easier to compare, add a dedicated benchmark entrypoint instead of relying on ad hoc shell timing.

Suggested features:

- `--benchmark-json path`
- `--benchmark-tag name`
- `--tick-filter symbol1,symbol2,...`
- `--skip-reports`
- `--history-mode text|cache`
- `--profile cprofile`

Suggested stage schema:

```json
{
  "date": "20260225",
  "config": {
    "signal_a": true,
    "signal_b": false,
    "strong_group": true,
    "strong_single": false
  },
  "workload": {
    "tick_filter_symbols": 1796,
    "ticks_processed": 0,
    "replay_bytes": 0,
    "history_bytes": 0
  },
  "timings_ms": {
    "load_refs": 0,
    "history_otc": 0,
    "history_tse": 0,
    "history_merge": 0,
    "screen_init": 0,
    "replay_loop": 0,
    "reporting": 0,
    "total": 0
  }
}
```

That benchmark output should become the source of truth for future optimization reports.

## Recommended Optimization Sequence

If the goal is fastest practical payoff without changing strategy behavior, the best sequence is:

1. remove history slot `0`
2. stop building `val_cum`
3. add a lightweight history parser
4. fix replay-universe construction to use only valid symbols
5. gate disabled features outside the hot loop
6. add a persistent history cache
7. then optimize strong-group incremental math and ranking

Why this order:

- steps 1 through 5 are behavior-preserving and localized
- they reduce waste in the currently dominant stages
- step 6 is the largest long-term win but deserves separate benchmark coverage because it changes operational behavior
- step 7 matters most after the large I/O waste is removed

## Bottom Line

The replay runtime is currently split into two regimes:

- early dates: current-day replay loop dominates
- late dates and monthly batches: history-window rebuild dominates overwhelmingly

The biggest current performance problems are not subtle:

- reparsing large text history windows every day
- parsing the replay date twice
- building unused history data
- paying full-object parse cost where a tiny history record would do
- replaying a broader symbol universe than the strategy actually needs

If future optimization work fixes only the current-day parser and leaves history loading unchanged, month-scale runtime will still be dominated by repeated text parsing. The first serious optimization pass should therefore treat history construction as the primary target and current-day replay parsing as the secondary target.
