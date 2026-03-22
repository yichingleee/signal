# Replay Runtime Optimization Verification

## Scope

This report documents the verification of the replay runtime optimizations implemented per the execution plan at `docs/exec-plans/active/replay-runtime-optimization-execution-plan.md`. It covers correctness validation, performance benchmarks against the baselines established in `docs/design-docs/replay-runtime-optimization-research.md`, and a critical bug found and fixed during verification.

Measured on 2026-03-22/23 using the same machine and data as the original research report.

## Optimizations Implemented

The following phases were implemented (details in the execution plan):

| Phase | Description |
| --- | --- |
| 0 | Benchmark harness CLI (`run_benchmark.py`) |
| 1 | History slot 0 elimination, lightweight parser, val_cum removal, HistoryWindow named result |
| 2 | Persistent binary volume cache (JSON per market/date) |
| 3 | Rolling history provider for batch mode |
| 4 | Disabled-feature gating, deque-based NumTracker, buffered CSV I/O |
| 5 | Index-based symbol extraction in replay parser |
| 6 | Precomputed month aggregates, cached prev_close, GroupRank sorted-view cache |

## Critical Bug Found During Verification

### `_merge_history_windows()` mutated shared objects in-place

During the first full batch run, the engine OOM'd after 12 of 21 dates (exit code 137). Symptoms:

- `readFileMerged` degraded from ~38s to 234s over 12 dates
- `getGroup` degraded from 6ms to 1,908ms
- Trade results diverged from standalone runs (data corruption)

Root cause: `_merge_history_windows()` merged TSE data into OTC `LinearVolumeTracker` objects by calling `.extend()` on shared lists, and merged `trading_val` dicts by mutating OTC dicts directly. Since the rolling history provider reuses these objects across dates, TSE data accumulated repeatedly on each batch step.

Fix: create new `LinearVolumeTracker` and `dict` objects during merge instead of mutating inputs. After the fix:

- Memory usage stayed stable across all 21 dates
- `getGroup` stayed under 21ms throughout
- Batch and standalone results matched exactly

## Correctness Validation

### Test Suite

106 unit tests pass (up from 83 pre-optimization), including new tests for:

- History window construction and slot exclusion
- Lightweight history parser
- Volume cache build/load/staleness
- Rolling history provider

```
uv run pytest tests -q  →  106 passed in 0.29s
uv run ruff check src tests  →  clean
uv run mypy src  →  clean
```

### Batch vs Standalone Cross-Validation

The following dates were run both as standalone `run_daily_replay` and inside the January 2026 batch via `run_batch_replay`. Trade counts and PnL match exactly in all cases.

| Date | Trades | PnL | Match |
| --- | ---: | ---: | --- |
| 20260102 | 8 | 813,318 | yes |
| 20260105 | 2 | 150,337 | yes |
| 20260107 | 4 | 496,737 | yes |
| 20260130 | 1 | -119,565 | yes |

### Warm Cache vs Cold Cache Consistency

2026-02-11 was run twice (first cold, then warm cache). Both produced identical trade results:

- 2 trades: symbols 1303 and 1815
- PnL: 611,030
- Entry/exit times, prices, and all report fields identical

## Performance: Single-Day Benchmarks

### 2025-12-31 (shallow history window, smallest available day)

Baseline from research report: **57,722 ms total**

| Stage | Baseline | Optimized | Notes |
| --- | ---: | ---: | --- |
| getTickData OTC | 3,909 ms | 0 ms | Earliest date, no prior history |
| getTickData TSE | 13,954 ms | 0 ms | Earliest date, no prior history |
| getGroup | 5 ms | 7 ms | — |
| readFileMerged | 39,389 ms | 18,529 ms | Parser optimizations |
| **TOTAL** | **57,722 ms** | **18,884 ms** | **3.1x speedup** |

Ticks processed: 1,322,689 (unchanged).

### 2026-02-11 (full 21-day history, late-period)

Baseline from research report: history loading alone took **568,027 ms** (~9.5 minutes).

| Stage | Baseline | Optimized (cold) | Optimized (warm cache) |
| --- | ---: | ---: | ---: |
| getTickData OTC | 107,821 ms | 58,986 ms | 11,628 ms |
| getTickData TSE | 460,205 ms | 241,330 ms | 47,376 ms |
| getGroup | — | 60 ms | 15 ms |
| readFileMerged | — | 40,159 ms | 38,117 ms |
| **TOTAL** | **~630,000 ms est.** | **340,961 ms** | **97,479 ms** |

Ticks processed: 1,289,262 (unchanged). Trades: 2, PnL: 611,030 (unchanged).

Cold history improvement: **1.7x** (lightweight parser + val_cum removal).

Warm cache improvement: **~6.5x** vs baseline.

### 2026-02-25 (largest available day, 21-day history)

| Stage | Optimized (partial cache) |
| --- | ---: |
| getTickData OTC | 20,046 ms |
| getTickData TSE | 102,768 ms |
| getGroup | 89 ms |
| readFileMerged | 70,695 ms |
| **TOTAL** | **194,079 ms** |

Ticks processed: 1,839,450. Trades: 2, PnL: -344,938.

Some history dates between January and February were not yet cached, so this was a partial-cache run. With full warm cache, this would be closer to the 2026-02-11 warm-cache profile.

## Performance: January 2026 Monthly Batch (21 trading days)

### Baseline Estimate

From the research report:

- 21 replay days, 50.64 GB of unique replay-day data
- 573.10 GB of repeated history-window rereads under the old implementation
- Total text volume: **623.74 GB**
- Estimated runtime: **hours** (extrapolating from per-day cold-start measurements)

### Optimized Batch (warm cache + rolling history)

Command:

```bash
PYTHONPATH=src python -u -m tw_signal_engine.cli.run_batch_replay \
  --start 20260102 --end 20260130 \
  --data-dir exec/data --files-dir exec/files \
  --group-file exec/files/group.csv --config exec/cfg/parameter.cfg
```

**Total wall time: 19 minutes 27 seconds** (1,166.75s wall, 1,106.45s user).

Per-date breakdown:

| Date | readFileMerged (ms) | Total (ms) | Trades | PnL |
| --- | ---: | ---: | ---: | ---: |
| 20260102 | 51,364 | 51,670 | 8 | 813,318 |
| 20260105 | 44,216 | 44,531 | 2 | 150,337 |
| 20260106 | 45,477 | 45,842 | 2 | -192,649 |
| 20260107 | 52,199 | 52,586 | 4 | 496,737 |
| 20260108 | 47,691 | 48,054 | 3 | -557,066 |
| 20260109 | 40,324 | 40,628 | 3 | -457,837 |
| 20260112 | 43,428 | 43,737 | 7 | 440,021 |
| 20260113 | 44,034 | 44,360 | 2 | -40,359 |
| 20260114 | 47,396 | 47,704 | 5 | 221,083 |
| 20260115 | 41,884 | 42,214 | 1 | 418,193 |
| 20260116 | 48,061 | 48,378 | 2 | -283,132 |
| 20260119 | 54,088 | 54,407 | 2 | 236,083 |
| 20260120 | 54,754 | 55,100 | 3 | 69,809 |
| 20260121 | 54,317 | 54,657 | 2 | 26,873 |
| 20260122 | 67,448 | 67,803 | 1 | -9,731 |
| 20260123 | 48,525 | 48,853 | 5 | 69,815 |
| 20260126 | 60,446 | 60,795 | 3 | 505,195 |
| 20260127 | 51,292 | 51,686 | 5 | 733,503 |
| 20260128 | 62,250 | 62,586 | 4 | -656,536 |
| 20260129 | 57,871 | 58,299 | 1 | -147,493 |
| 20260130 | 52,093 | 52,424 | 1 | -119,565 |

Summary statistics:

| Metric | Value |
| --- | --- |
| Total dates | 21 |
| Total wall time | 19m 27s |
| Average per-day total | 55.6s |
| Min per-day total | 40.6s (20260109) |
| Max per-day total | 67.8s (20260122) |
| getGroup range | 6–21 ms (stable, no degradation) |
| History load per day | ~0 ms (rolling provider + cache) |
| History bytes re-read | 0 (all from cache) |
| Total ticks processed | 34,422,839 |
| Total trades | 66 |

### Batch Performance Comparison

| Metric | Baseline (estimated) | Optimized |
| --- | ---: | ---: |
| History text re-read | 573.10 GB | 0 GB (cached) |
| Total text scanned | 623.74 GB | ~50.64 GB (replay only) |
| Wall time | hours (est.) | 19m 27s |
| Memory stability | N/A | Stable (no degradation over 21 dates) |

## Where Runtime Goes Now

After optimization, the remaining cost is dominated by the current-day replay loop (`readFileMerged`), which is pure text parsing of the replay files.

Approximate cost breakdown for a warm-cache late-period date:

| Component | % of total |
| --- | ---: |
| History loading | ~0% (cached) |
| readFileMerged (replay loop) | ~95% |
| Screening init (getGroup) | <1% |
| Reporting | <1% |
| Config + references | <1% |

The next optimization targets, in order of expected impact:

1. **Replay parser**: `parse_trade_line()` and `_get_best_prices()` remain the hottest functions. A byte-oriented or native parser would further reduce the ~50s per-day replay loop.
2. **Strong-group incremental math**: `_group_percentage_chg()` scans all group members per tick. Incremental rolling state would reduce this.
3. **Replay universe filtering**: The `tick_filter` set includes all group symbols (valid or not). Tightening this further would reduce parser invocations.

## Methodology

All measurements used `PYTHONPATH=src python -u` (not `uv run`) to avoid resolver overhead in timing. Wall time was measured with the `time` shell builtin. Stage times were measured with `time.time()` inside the Python code.

Cache state for each benchmark:

- **2025-12-31**: No prior history files exist (earliest date). Cache irrelevant.
- **2026-02-11 cold**: No cache files present. Caches built during the run.
- **2026-02-11 warm**: All 20 prior-day caches present from the cold run.
- **January batch**: All caches pre-built from the 2026-02-11 cold run and the batch itself.

Python version: CPython (system default via `uv`).

Hardware: Same machine as the original research report (macOS Darwin 24.6.0).
