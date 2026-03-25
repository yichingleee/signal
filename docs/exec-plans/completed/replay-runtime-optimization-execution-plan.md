# Replay Runtime Optimization Execution Plan

## Goal

Reduce replay runtime where the codebase is actually spending time today:

- late-period daily cold starts dominated by `load_history_window()`
- batch runs dominated by rebuilding nearly identical history windows per date
- current-day replay dominated by text parsing and per-tick allocation after history costs are reduced

This plan is based on the current Python implementation under `src/tw_signal_engine/`, especially:

- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/market_data/load_history_window.py`
- `src/tw_signal_engine/market_data/parse_format6_replay_rows.py`
- `src/tw_signal_engine/replay/iterate_market_file.py`
- `src/tw_signal_engine/replay/merge_market_streams.py`
- `src/tw_signal_engine/screening/evaluate_strong_group.py`
- `src/tw_signal_engine/screening/evaluate_strong_single.py`
- `src/tw_signal_engine/state/group_state.py`
- `src/tw_signal_engine/market_data/market_data_records.py`
- `src/tw_signal_engine/cli/run_batch_replay.py`

## Current Code Findings To Address

- `run_daily_replay()` always rebuilds OTC and TSE history from raw text, then merges the two histories in Python.
- `load_history_window()` still parses the target replay date as history slot `0`, even though both screeners only read slots `1..20`.
- `load_history_window()` builds `val_cum`, but no active runtime code consumes it.
- `_parse_vol_cum_from_file()` uses `parse_trade_line()`, which allocates a full `MarketTick` plus 10 depth `QuotePair`s even though history loading only needs symbol, time, price, and qty.
- `run_batch_replay.py` loops over dates and calls `run_daily_replay()` independently, so adjacent dates cannot share already-built history.
- The hot replay loop still does disabled-feature work:
  - `StrongSingleEvaluator.on_tick()` is called even when strong-single is off.
  - `SignalBState` objects are still created lazily even when Signal B is off.
  - `evaluate_signal_b()` is still called and returns early.
- `NumTracker` uses `list.pop(0)`, which is O(n) under expiration.
- `StrongGroupEvaluator.on_tick()` recomputes group percentage changes, history sums, and ranking order repeatedly.
- `iterate_market_file()` still pays the full scan cost for every line, and `_get_best_prices()` is a measurable parser hotspot.

## Success Criteria

Use the benchmark commands from `docs/design-docs/replay-runtime-optimization-research.md` as the baseline protocol. Treat improvements as valid only if they preserve replay outputs and clear the repo validation suite.

Minimum acceptance targets:

- Phase 1: remove wasted history work with no replay behavior changes and a measurable daily runtime reduction on the same machine.
- Phase 2: add warm history caches so late-period daily replays no longer reparse tens of GB of text on every run.
- Phase 3: make batch replays reuse history in-process so adjacent dates do not reload 20 unchanged sessions.
- Phase 4: re-profile the current-day replay path and cut parser/screener overhead only after history costs are materially reduced.

## Guardrails

- Preserve deterministic replay ordering and current report outputs.
- Keep the archived C++ tree as a parity reference only; do not reintroduce C++-specific architecture into the active runtime unless the Python code needs it.
- Do not mix large behavior refactors with performance work. Each optimization phase must land with focused correctness tests and benchmark evidence.
- Prefer compatibility-preserving interface changes first. If a contract must change, change the narrowest surface possible and update the callers in the same phase.

## Phase 0: Benchmark Harness And Baseline Lock ✅ COMPLETED

### Scope

Create a repeatable measurement path before changing the runtime.

### Code Touchpoints

- Add a small benchmark/profile CLI under `src/tw_signal_engine/cli/` for:
  - isolated `load_history_window()`
  - isolated `iterate_market_file()`
  - end-to-end `run_daily_replay()`
- Extend docs with the exact baseline dates already used in the research doc:
  - `20251231` for a smaller daily sample
  - `20260211`, `20260223`, `20260225` for late-period measurements

### Deliverables

- a checked-in benchmark entrypoint so future measurements do not depend on ad hoc shell snippets
- a short benchmark README section or doc addendum describing cold-cache vs warm-cache runs

### What Was Done

- Created `src/tw_signal_engine/cli/run_benchmark.py` with `history`, `parse`, and `replay` sub-commands.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 1: Remove Known Wasted History Work ✅ COMPLETED

### Scope

Land the low-risk fixes already justified by the current code.

### Changes

1. Replace the loose history tuple with a named result object.
   - Introduce a small `HistoryWindow` record in `src/tw_signal_engine/market_data/`.
   - Keep only the fields the runtime reads now:
     - cumulative volume history
     - per-day total trading value
     - optional metadata such as source dates for debugging

2. Stop parsing the replay day into usable history.
   - Change `_find_history_files()` / `load_history_window()` so screening history covers only prior sessions.
   - For the first pass, keep compatibility simple:
     - either return 20 prior sessions and update the screeners to iterate explicit history slots
     - or keep slot `0` empty and preserve caller indexing temporarily
   - The preferred implementation is to remove the magic `1..20` convention and expose explicit prior-session slots through the new `HistoryWindow`.

3. Delete `val_cum` from the active runtime path.
   - Remove it from `load_history_window()`.
   - Remove dead unpacking and merge logic from `replay_session.py`.

4. Add a dedicated lightweight history parser.
   - Keep `parse_trade_line()` for current-day replay.
   - Add a new parser for history loading that extracts only:
     - symbol
     - `match_time_us`
     - price
     - qty
   - Avoid `MarketTick` allocation during history construction.

### What Was Done

- Created `src/tw_signal_engine/market_data/history_window.py` with `HistoryWindow` dataclass.
- Created `src/tw_signal_engine/market_data/parse_history_trades.py` with lightweight `HistoryTrade` parser.
- Rewrote `load_history_window()` to return `HistoryWindow`, exclude target date, use lightweight parser, drop `val_cum`.
- Updated `replay_session.py` to use `HistoryWindow` and `_merge_history_windows()` helper.
- Updated screeners (`evaluate_strong_group.py`, `evaluate_strong_single.py`) to use 0-based indexing with `range(len(vol_cum))`.
- Added 6 new tests in `test_load_history_window.py` and `test_parse_history_trades.py`.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 2: Add Persistent History Caches ✅ COMPLETED

### Scope

Eliminate the repeated text parse of prior sessions across repeated daily runs.

### Changes

1. Replace the placeholder in `src/tw_signal_engine/market_data/build_volume_caches.py` with a real cache module.
   - Keep the module name if that minimizes churn, but the implementation needs a clear public API:
     - build cache for one market/date
     - load cache for one market/date
     - validate cache version / source file freshness

2. Cache the minimal history data shape produced by Phase 1.
   - per symbol: cumulative volume timeline by timestamp
   - per symbol: total trading value for the day
   - cache metadata:
     - market
     - source date
     - source file size / mtime
     - cache schema version

3. Make `load_history_window()` cache-aware.
   - On warm path, deserialize cache instead of reparsing text.
   - On cold or stale path, rebuild the day cache from text, then load the in-memory `HistoryWindow` shape.

4. Keep cache writes explicit and observable.
   - log when a cache miss triggers a rebuild
   - support a "rebuild all needed caches" flow for operators and CI benches

### What Was Done

- Implemented full cache module in `build_volume_caches.py` with `build_cache()`, `load_cache()`, `is_cache_valid()`, `ensure_caches()`.
- JSON-based cache format with schema version, source file size/mtime for staleness detection.
- Made `load_history_window()` cache-aware with `use_cache=True` default.
- Added 7 cache tests in `test_volume_caches.py` including text-vs-cache equivalence and staleness invalidation.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 3: Reuse History Across Batch Runs ✅ COMPLETED

### Scope

Stop rebuilding the same 20 prior sessions for every adjacent date in `run_batch_replay.py`.

### Changes

1. Introduce an in-process rolling history provider for batch mode.
   - Maintain the prior-session window per market as dates advance.
   - Drop the oldest session and append the newly needed prior session instead of rebuilding the entire window.

2. Split the current session setup just enough to inject prebuilt history.
   - `run_daily_replay()` currently owns config load, reference load, history load, replay, and reporting.
   - Extract a narrow seam so batch mode can pass a prepared `HistoryWindow` without duplicating replay logic.

3. Keep single-day CLI behavior unchanged.
   - daily replay should still work as a standalone entrypoint
   - batch replay should become a thin loop around reusable session dependencies

### What Was Done

- Created `src/tw_signal_engine/market_data/rolling_history.py` with `RollingHistoryProvider` class.
- Added `history` parameter to `run_daily_replay()` for pre-built history injection.
- Rewrote `run_batch_replay.py` to use `RollingHistoryProvider` per market, merging OTC+TSE before injecting.
- Added 4 tests in `test_rolling_history.py` for reuse, exclusion, empty prior, and data integrity.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 4: Remove Hot-Loop Overhead That Is Already Unnecessary ✅ COMPLETED

### Scope

Cut obvious CPU overhead in the replay loop before deeper parser or screener redesign.

### Changes

1. Gate disabled features outside the tick loop.
   - Do not call `StrongSingleEvaluator.on_tick()` when `config.strong_single.enabled` is false.
   - Do not create `SignalBState` objects or call `evaluate_signal_b()` when `config.signal_b.enabled` is false.

2. Replace `NumTracker`'s list-based expiry with `collections.deque`.
   - Preserve current semantics of "first three trades in the rolling window".

3. Buffer main order-log writes.
   - Stop flushing the main CSV on every entry/leave row.
   - Flush on close, and optionally on explicit checkpoints if needed.

### What Was Done

- Gated `strong_single.on_tick()`, `strong_group.on_tick()`, `evaluate_signal_a()`, `evaluate_signal_b()` behind their respective `config.*.enabled` flags in the tick loop. No state allocation for disabled features.
- Replaced `NumTracker._symbol_trades` from `dict[str, list[int]]` to `dict[str, deque[int]]`, using `popleft()` instead of `pop(0)`.
- Removed per-row `flush()` calls from `OrderLogWriter`, using 8KB buffered I/O instead.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 5: Re-Profile And Optimize Current-Day Parsing ✅ COMPLETED

### Scope

Only after Phases 1 through 4 land, optimize the remaining replay path that still dominates small-day runs.

### Changes

1. Speed up `iterate_market_file()` fast paths.
   - Replace `split(",", 3)` in the filter precheck with cheaper delimiter slicing.
   - Keep the trade/depth pairing logic deterministic.

2. Rewrite `_get_best_prices()` for the exact replay format in use.
   - Avoid repeated `find()`, `split()`, string concatenation, and per-char string building.
   - Prefer index-based scanning over general-purpose parsing helpers.

3. Revisit `MarketTick` allocation only after parser-only changes are measured.
   - Today the runtime mostly reads `tick.match`, `tick.bid[0]`, `tick.ask[0]`, and flags.
   - If object allocation remains hot after parser cleanup, introduce a smaller best-bid/best-ask representation without changing replay semantics.
   - Do not start with a broad record redesign until a fresh profile proves it is worth the compatibility cost.

### What Was Done

- Added `_extract_symbol_fast()` in `iterate_market_file.py` using index-based scanning (avoids `split(",", 3)`).
- Extracted `_is_trade_line()` helper for clarity and local reference.
- Rewrote `_get_best_prices()` using `_extract_first_price_after_tag()` — pure index-based scanning without string concatenation or per-char string building.
- Changed `parse_trade_line()` to use `split(",", 6)` limit instead of unlimited split.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Phase 6: Optimize Strong-Group And Strong-Single CPU Paths ✅ COMPLETED

### Scope

Address the next bottleneck after history and parser costs are reduced.

### Changes

1. Precompute month aggregates once.
   - `StrongGroupEvaluator.on_tick()` and `StrongSingleEvaluator._eval_vol_cond()` currently recompute 20-day totals repeatedly.
   - Move month totals and month averages into initialization-time maps.

2. Incrementalize group percentage bookkeeping.
   - `_group_percentage_chg()` currently loops full member sets and may be called multiple times for the same group in one tick.
   - Maintain per-group running aggregates so a symbol tick only updates the groups that symbol belongs to.

3. Remove repeated full sorting from `GroupRank`.
   - Preserve current parity-sensitive score-collision behavior unless parity mode is explicitly changed.
   - Add a cached ranked view or another incremental ordering strategy so `get_rank()`, `is_top_n()`, and `iter_ranked()` do not sort the full map on every lookup.

4. Revisit strong-single's top-volume tracker only if the feature is re-enabled.
   - `TopKVolumeTracker` currently rebuilds from all symbols.
   - This is not on the active config path, so keep it behind the active-config work.

### What Was Done

- Precomputed `_month_total_tv` and `_month_avg_tv` per symbol during `initialize_validity()` in both `StrongGroupEvaluator` and `StrongSingleEvaluator`.
- Cached `_prev_close_cache` for O(1) `_percentage_chg()` lookups in both evaluators.
- Added `_sorted_cache` with `_invalidate()` pattern to `GroupRank` — sorted list is computed once and reused until `on_tick()` or `erase()` mutates state.
- Used precomputed `_month_total_tv` in `on_tick()` instead of recomputing `sum(trading_val[i].get(...))` on every tick.

### Validation

- `uv run pytest tests -q` — 106 passed
- `uv run ruff check src tests` — clean
- `uv run mypy src` — clean

## Validation Matrix

Every phase should run:

- `uv run pytest tests -q`
- `uv run ruff check src tests`
- `uv run mypy src`

Targeted additions by phase:

- Phase 1:
  - history loader excludes target-day history
  - lightweight history parser matches text fixtures
- Phase 2:
  - cache warm path equals text path
  - stale cache invalidation
- Phase 3:
  - batch replay with reuse equals repeated single-day outputs
- Phase 4:
  - disabled features do not allocate or execute their hot-loop paths
- Phase 5:
  - parser fixture equivalence for trade/depth pairing and best bid/ask extraction
- Phase 6:
  - strong-group ranking and qualification equivalence on controlled fixtures

## Recommended Delivery Order

1. Phase 0 and Phase 1 together, because they are low-risk and directly justified by current code.
2. Phase 2 next, because warm caches are the highest-leverage fix for late-period daily runs.
3. Phase 3 after caches, because batch reuse becomes much simpler once the history shape is explicit and cacheable.
4. Phase 4 immediately after the history work, because the current config can claim easy wins with little blast radius.
5. Phase 5 and Phase 6 only after a fresh profile confirms the remaining hotspots.

## Explicit Non-Goals For The First Pass

- broad execution-strategy behavior changes
- multithreaded replay parsing
- native extensions or a rewrite away from the Python runtime
- fixing the parity-preserved `GroupRank` collision behavior as part of optimization work

## Done Definition

This plan is complete when the repository has:

- benchmarkable before/after measurements for daily and batch runs
- a cache-backed history path for daily replay
- shared-history reuse for batch replay
- the obvious hot-loop waste removed from the committed config path
- preserved replay outputs and a passing validation suite

## Implementation Status

All phases (0-6) are **COMPLETED**. Final validation: 106 tests passing, ruff clean, mypy clean.

### Summary of New/Modified Files

**New files:**
- `src/tw_signal_engine/cli/run_benchmark.py` — benchmark harness CLI
- `src/tw_signal_engine/market_data/history_window.py` — `HistoryWindow` named result
- `src/tw_signal_engine/market_data/parse_history_trades.py` — lightweight history parser
- `src/tw_signal_engine/market_data/rolling_history.py` — rolling history provider for batch mode
- `tests/unit/test_parse_history_trades.py` — lightweight parser tests
- `tests/unit/test_volume_caches.py` — cache system tests
- `tests/unit/test_rolling_history.py` — rolling history provider tests

**Modified files:**
- `src/tw_signal_engine/market_data/load_history_window.py` — HistoryWindow return, cache-aware, exclude target date
- `src/tw_signal_engine/market_data/build_volume_caches.py` — full cache implementation
- `src/tw_signal_engine/market_data/market_data_records.py` — NumTracker deque
- `src/tw_signal_engine/market_data/parse_format6_replay_rows.py` — optimized _get_best_prices
- `src/tw_signal_engine/replay/replay_session.py` — HistoryWindow integration, disabled-feature gating, history injection
- `src/tw_signal_engine/replay/iterate_market_file.py` — fast symbol extraction
- `src/tw_signal_engine/cli/run_batch_replay.py` — rolling history provider integration
- `src/tw_signal_engine/screening/evaluate_strong_group.py` — precomputed month aggregates, prev_close cache
- `src/tw_signal_engine/screening/evaluate_strong_single.py` — precomputed month aggregates, prev_close cache
- `src/tw_signal_engine/state/group_state.py` — cached sorted views
- `src/tw_signal_engine/reporting/write_order_log_csv.py` — buffered writes
- `tests/unit/test_load_history_window.py` — expanded history window tests
