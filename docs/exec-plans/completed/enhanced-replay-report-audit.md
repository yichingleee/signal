# Enhanced Replay Report — Audit Fix Execution Plan

> **Branch**: `feat/enhanced-replay-report`
> **Source**: Audit findings from 2026-03-25 implementation review
> **Goal**: Fix all bugs and missing features identified in the audit before merge.

---

## Fix Summary

| # | Fix | Severity | Difficulty | Phase |
|---|-----|----------|-----------|-------|
| 1 | Pass `--cost-model` and `--no-charts` to per-day replays in batch mode | **High** | Low | 1 |
| 2 | Fix broken doc link in `docs/exec-plans/active/index.md` | **Low** | Trivial | 1 |
| 3 | Increment `FunnelTracker.group_qualified_ticks` in replay session | **Medium** | Low | 2 |
| 4 | Add `ConcurrentPositions` and `CapitalUtilized` to `report_daily.csv` | **Medium** | Medium | 2 |
| 5 | Add `group_qualified_ticks` row to funnel report | **Low** | Trivial | 2 |

---

## Phase 1 — Bug Fixes (P0/P1) ✅ COMPLETED

### 1.1 Pass CLI flags through batch replay to per-day replays

**File**: `src/tw_signal_engine/cli/run_batch_replay.py`

**Problem**: `run_daily_replay()` call at lines 65-73 does not pass `cost_model_override` or `no_charts`, so:
- Per-day trades have zero cost fields even when `--cost-model` is specified. Batch reports then aggregate incorrect zeros.
- Per-day charts are always generated even when `--no-charts` is specified.

**Change**: Add two parameters to the `run_daily_replay()` call inside the date loop:

```python
day_trades = run_daily_replay(
    trade_date=date,
    config_path=args.config,
    data_dir=args.data_dir,
    files_dir=args.files_dir,
    group_file=args.group_file,
    log_folder=batch_folder,
    history=merged_history,
    no_charts=args.no_charts,              # NEW
    cost_model_override=args.cost_model,   # NEW
)
```

**Tests**: Add 2 tests to `tests/unit/test_batch_reports.py`:
- `test_cost_model_override_propagated`: Mock `run_daily_replay` and verify `cost_model_override` kwarg is passed.
- `test_no_charts_propagated`: Same for `no_charts`.

### 1.2 Fix broken doc link

**File**: `docs/exec-plans/active/index.md`

**Current** (line 3):
```text
replay-runtime-optimization-execution-plan.md
```

**Change to**:
```text
enhanced-replay-report-audit.md (this file, the current active plan)
```

The old runtime optimization plan has been moved to `docs/exec-plans/completed/`.

**Verification**: `test_local_markdown_links_resolve` should pass.

---

## Phase 2 — Missing Features (P2) ✅ COMPLETED

### 2.1 Increment `funnel.group_qualified_ticks`

**File**: `src/tw_signal_engine/replay/replay_session.py`

**Context**: The pipeline flow is: universe ticks → group/single screening → signal evaluation → entry filter → execution. The `group_qualified_ticks` counter should capture ticks that pass screening (i.e., `match_type != "None"`).

**Change**: After the screening block (line 338), before signal evaluation (line 340), add:

```python
if match_type != "None":
    funnel.group_qualified_ticks += 1
```

This increments for every tick where the symbol qualifies as StrongGroup, StrongSingle, or Both — the intermediate funnel step between "valid group symbols" and "signal triggered".

### 2.2 Add `group_qualified_ticks` to funnel report

**File**: `src/tw_signal_engine/reporting/build_funnel_report.py`

**Change**: Insert a row for `Group Qualified Ticks` in the `stages` list, between `Valid Group Symbols` and `Signal Triggered`:

```python
stages = [
    ("Universe", funnel.universe_count),
    ("Valid Group Symbols", funnel.valid_group_symbols),
    ("Group Qualified Ticks", funnel.group_qualified_ticks),   # NEW
    ("Signal Triggered", funnel.signal_triggered),
    ("Entry Filter Blocked", funnel.entry_filter_blocked),
    ("Executed Trades", funnel.executed_trades),
]
```

**Tests**: Update `tests/unit/test_funnel_tracker.py`:
- Add test verifying `group_qualified_ticks` increments correctly.
- Update existing report output test to expect the new row.

### 2.3 Add `ConcurrentPositions` and `CapitalUtilized` to daily equity report

**File**: `src/tw_signal_engine/reporting/build_daily_equity_report.py`

**Approach**: Compute from existing trade data — no new fields needed on `TradeRecord` or changes to `replay_session.py`. Both metrics can be derived from entry/exit timestamps and entry price:

- **`ConcurrentPositions`**: For each date, find the maximum number of overlapping trades by scanning entry/exit times. A trade is "open" from `entry_time_raw` to `exit_time_raw`. Sweep-line: sort all (time, +1/-1) events, track running count, record max.
- **`CapitalUtilized`**: Sum of `entry_price * shares` for all concurrently open positions at peak. Approximate as `config.position_cash * ConcurrentPositions` since each trade uses one position unit. Simpler: use `trades_count_at_peak * position_cash_per_trade`, where `position_cash_per_trade` is derivable from `pnl / return_pct * 100` for any trade with nonzero return.

**Change**: Add helper function and update CSV output:

```python
def _max_concurrent_and_capital(trades: list[TradeRecord]) -> tuple[int, float]:
    """Compute max concurrent positions and peak capital utilized for a day."""
    events: list[tuple[int, int]] = []  # (time, +1 or -1)
    for t in trades:
        events.append((t.entry_time_raw, 1))
        events.append((t.exit_time_raw, -1))
    events.sort()

    max_concurrent = 0
    current = 0
    for _, delta in events:
        current += delta
        if current > max_concurrent:
            max_concurrent = current

    # Approximate capital: each position uses one unit of position_cash
    # Derive position_cash from the first trade with nonzero return
    position_cash = 0.0
    for t in trades:
        if t.return_pct != 0:
            position_cash = t.pnl / t.return_pct * 100
            break

    capital_utilized = max_concurrent * position_cash
    return max_concurrent, capital_utilized
```

Update CSV header and row:

```python
w.writerow([
    "Date", "Trades", "GrossPnL", "NetPnL", "CumPnL",
    "Drawdown", "DrawdownPct", "WinRate", "AvgReturn%",
    "ConcurrentPositions", "CapitalUtilized",   # NEW
])

# In the loop:
max_conc, capital = _max_concurrent_and_capital(trades)
w.writerow([
    date, n,
    f"{gross:.0f}", f"{net:.0f}", f"{cum_pnl:.0f}",
    f"{dd:.0f}", f"{dd_pct:.1f}%",
    f"{win_rate:.1f}%", f"{avg_ret:.2f}%",
    str(max_conc), f"{capital:.0f}",             # NEW
])
```

**Tests**: Add to `tests/unit/test_daily_equity_report.py`:
- `test_concurrent_positions_computed`: 3 overlapping trades, verify max concurrent = 2.
- `test_capital_utilized_computed`: Verify `capital = max_concurrent * position_cash`.
- `test_no_overlap_concurrent_is_one`: Non-overlapping trades, verify max concurrent = 1.

---

## Verification

Run after all changes:

```bash
uv run pytest tests -q            # All tests pass (including previously failing doc link test)
uv run mypy src                   # Type checking
uv run ruff check src tests       # Linting
```

Expected: 0 failures (the 8 golden parity failures are pre-existing missing baseline data, unrelated to this fix).

---

## Files Changed

| File | Change Type |
|------|-------------|
| `src/tw_signal_engine/cli/run_batch_replay.py` | Bug fix — pass 2 kwargs |
| `docs/exec-plans/active/index.md` | Bug fix — update link |
| `src/tw_signal_engine/replay/replay_session.py` | Feature — increment counter |
| `src/tw_signal_engine/reporting/build_funnel_report.py` | Feature — add row |
| `src/tw_signal_engine/reporting/build_daily_equity_report.py` | Feature — add 2 columns + helper |
| `tests/unit/test_funnel_tracker.py` | Test — new counter test |
| `tests/unit/test_daily_equity_report.py` | Test — 3 new tests |
