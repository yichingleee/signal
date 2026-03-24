# Enhanced Replay Report — Execution Plan

> **Branch**: `feat/enhanced-replay-report`
> **Goal**: Transform the replay report from descriptive (what happened) to diagnostic (why it worked, whether it is robust, whether it is implementable).

---

## Evaluation Summary

| # | Improvement | Importance | Difficulty | Phase | Decision |
|---|------------|-----------|-----------|-------|----------|
| 1 | Decision Funnel | Critical | Medium | 1 | **Include** — instrument replay loop with counters |
| 2 | Cost & Execution Realism | Critical | Medium | 1 | **Include** — configurable fees/tax, default 0, explicit in report |
| 3 | Trade Path Decomposition | Critical | High | 2 | **Include** — MAE/MFE, slice PnL, time-to-TP |
| 4 | Filter Attribution (Shadow) | Critical | High | Deferred | **Phase 1: Log block reasons only**; shadow returns deferred |
| 5 | Statistical Robustness | High | Low | 2 | **Include** — pure post-processing on existing data |
| 6 | Concentration Analysis | High | Low | 2 | **Include** — pure post-processing |
| 7 | Regime Conditioning | Medium-High | Medium | 3 | **Include** — 0050 chg% + time buckets available |
| 8 | Portfolio-Level Risk | High | Medium | 3 | **Include** — batch aggregation needed |
| 9 | Edge Attribution | Medium-High | High | Deferred | **Skip** — requires multi-pass replay architecture |
| 10 | Parameter Sensitivity | Medium | High | Deferred | **Skip** — requires grid-search orchestration layer |

**Deferral rationale**: Shadow analysis logs block reasons now (cheap) so data is ready later. Edge attribution and parameter sensitivity require multi-pass replay / grid-search orchestration — orthogonal to report enhancements.

---

## New Dependencies

```toml
# pyproject.toml — add to [project.dependencies]
"matplotlib>=3.8",
"numpy>=1.26",
```

`numpy` for statistical computations (bootstrap CI, skew, kurtosis). `matplotlib` for chart outputs. No `scipy`.

---

## Phase 1 — Data Model & Engine Instrumentation  **[COMPLETED]**

**Goal**: Enrich the data flowing through the pipeline so downstream reports have the fields they need.

### 1.1 Extend `TradeRecord` with path & cost fields

**File**: `records/market_event_records.py`

New fields (all default 0 / empty):

| Category | Fields |
|----------|--------|
| Trade path | `mae_pct`, `mfe_pct`, `mae_price`, `mfe_price`, `time_to_first_tp_sec`, `tp_slices_filled`, `tp_pnl`, `residual_pnl` |
| Cost model | `gross_pnl`, `commission`, `tax`, `net_pnl` |
| Context | `trade_date` (YYYYMMDD), `entry_hour_bucket` (e.g. "09:00-09:15") |

### 1.2 Track MAE/MFE during trade lifetime

- **`state/position_state.py`**: Add `trade_low` / `trade_high` dicts (per-symbol lowest/highest price since entry).
- **`execution/trade_ledger.py`**: Update tracking in `on_tick_exit()` on every tick; compute MAE/MFE vs entry price in `record_close()`.

### 1.3 Track TP slice fills

**File**: `execution/apply_take_profit_plan.py`

Add to `EntryTrade`: `first_tp_time_raw`, `tp_slices_filled`, `tp_realized_pnl` (all default 0). Update `check_take_profit` to increment counters on each fill.

### 1.4 Cost model in config

- **`config/strategy_config.py`** — add to `ExecutionConfig`: `commission_rate`, `tax_rate`, `slippage_bps` (all default 0.0).
- **`config/normalize_strategy_config.py`** — map from `[Order]` section in `parameter.cfg`.
- **`execution/trade_ledger.py`** — in `record_close()`, compute: `commission = (entry_notional + exit_notional) × rate`, `tax = exit_notional × rate`, `net_pnl = gross_pnl − commission − tax`.

### 1.5 Decision funnel counters

**New file**: `reporting/funnel_tracker.py`

```python
@dataclass
class FunnelTracker:
    universe_count: int = 0
    valid_group_symbols: int = 0
    group_qualified_ticks: int = 0
    signal_triggered: int = 0
    entry_filter_blocked: int = 0
    entry_filter_reasons: dict[str, int]  # reason → count
    executed_trades: int = 0
```

**`replay/replay_session.py`**: Instrument main loop — increment counters after each pipeline stage (universe build → validity → group screening → signal eval → entry filter → execution).

### 1.6 Block reason logging (filter attribution prep)

**File**: `execution/create_entry_trade.py`

Change `should_enter()` return type from `bool` → `tuple[bool, str | None]`. Return the specific block reason string when False. Store in `FunnelTracker.entry_filter_reasons`.

---

## Phase 2 — Enhanced Report Modules (Per-Day)  **[COMPLETED]**

**Goal**: Add new CSV reports and upgrade existing ones using the enriched data model.

### 2.1 Enhanced trade report

**File**: `reporting/build_trade_report_rows.py`

Add columns to `report_trades.csv`: `MAE%`, `MFE%`, `MAEPrice`, `MFEPrice`, `TimeToFirstTP`, `TPSlicesFilled`, `GrossPnL`, `Commission`, `Tax`, `NetPnL`, `TPPnL`, `ResidualPnL`, `TradeDate`, `EntryHourBucket`.

### 2.2 Funnel report

**New file**: `reporting/build_funnel_report.py` → `report_funnel.csv`

Two sections: (1) Pipeline stages with count, pass rate, cumulative pass rate. (2) Block reason breakdown with count and percentage.

### 2.3 Statistical robustness report

**New file**: `reporting/build_statistics_report.py` → `report_statistics.csv`

Metrics: median PnL, std dev, expectancy (absolute + bps), payoff ratio, skewness, kurtosis, bootstrap 95% CI for mean return and profit factor (10k resamples). All computed with `numpy` only.

### 2.4 Concentration report

**New file**: `reporting/build_concentration_report.py` → `report_concentration.csv`

Sections: top symbols, top dates, top groups by PnL. Contribution percentiles: top 1%, 5%, 10%, and remainder.

### 2.5 Trade path report

**New file**: `reporting/build_trade_path_report.py` → `report_trade_paths.csv`

One row per trade: `Symbol`, `EntryTime`, `MAE%`, `MFE%`, `TimeToTP(sec)`, `TPSlices`, `TPPnL`, `ResidualPnL`, `PeakUnrealizedPnL`, `TroughUnrealizedPnL`, `LeaveCause`.

### 2.6 Cost summary in `report_summary.csv`

**File**: `reporting/build_daily_summary.py`

Add rows: Total Gross PnL, Total Commission, Total Tax, Total Net PnL, Net Profit Factor, Avg Net Return%. Always shown (even when costs = 0).

---

## Phase 3 — Multi-Day Aggregation & Regime Analysis  **[COMPLETED]**

**Goal**: Aggregate batch replay results into portfolio-level and regime-conditioned reports.

### 3.1 Batch result collector

**File**: `cli/run_batch_replay.py`

Collect all `TradeRecord` lists and daily summary dicts across dates. Pass to `generate_batch_reports()`.

### 3.2 Daily equity & risk report

**New file**: `reporting/build_daily_equity_report.py` → `report_daily.csv`

Columns: `Date`, `Trades`, `GrossPnL`, `NetPnL`, `CumPnL`, `Drawdown`, `DrawdownPct`, `WinRate`, `AvgReturn%`, `ConcurrentPositions`, `CapitalUtilized`.

### 3.3 Rolling metrics

**New file**: `reporting/build_rolling_metrics.py` → `report_rolling.csv`

20-day rolling windows: hit rate, expectancy, profit factor, avg holding duration.

### 3.4 Regime report

**New file**: `reporting/build_regime_report.py` → `report_regime.csv`

| Dimension | Buckets |
|-----------|---------|
| Market state (0050 open chg%) | `<-1%`, `-1% to 0%`, `0% to 1%`, `>1%` |
| Entry hour | `09:00-09:15`, `09:15-09:30`, `09:30-10:00`, `10:00+` |
| Group rank | `1-5`, `6-10`, `11-20` |

Per bucket: count, win rate, total PnL, avg return%, profit factor.

---

## Phase 4 — Visualizations (Matplotlib PNG)  **[COMPLETED]**

**Goal**: Generate publication-quality static charts alongside CSV data.

### 4.1 Module structure

```
reporting/charts/
├── __init__.py
├── _style.py            # Shared colors, fonts, figure sizes
├── equity_curve.py      # Cumulative PnL + drawdown
├── pnl_distribution.py  # Histogram + KDE of trade returns
├── mae_mfe_scatter.py   # MAE vs MFE scatter by leave cause
├── concentration.py     # Lorenz-style cumulative PnL curve
├── category_bars.py     # PnL by signal/cause/leave
├── regime_heatmap.py    # Hour × market state heatmap
├── funnel.py            # Horizontal bar: decision funnel
├── rolling_metrics.py   # Rolling hit rate + expectancy
└── trade_scatter.py     # Return% vs holding duration
```

### 4.2 Shared style (`_style.py`)

Non-interactive backend (`matplotlib.use("Agg")`). Color palette: win (#2ecc71), loss (#e74c3c), neutral (#95a5a6), primary (#2c3e50), accent (#3498db). Figure: 12×6 @ 150 DPI.

### 4.3 Chart inventory

| Chart | Output File | Key Details |
|-------|-------------|-------------|
| Equity + Drawdown | `chart_equity_curve.png` | Top: cumulative net PnL line. Bottom: drawdown filled area (red). |
| PnL Distribution | `chart_pnl_distribution.png` | Histogram colored win/loss, vertical mean/median lines, annotated skew/kurtosis. |
| MAE/MFE Scatter | `chart_mae_mfe.png` | X=MAE%, Y=MFE%, colored by leave cause, diagonal breakeven. |
| Concentration | `chart_concentration.png` | Sorted trades (desc) vs cumulative PnL %, reference uniform line, top 5%/10% annotated. |
| Category Bars | `chart_category_pnl.png` | 3 grouped bar charts: PnL by signal type, enter cause, leave cause. |
| Regime Heatmap | `chart_regime_heatmap.png` | Rows=market state, cols=entry hour, cell=avg return% (diverging colormap), text=count+win rate. |
| Decision Funnel | `chart_funnel.png` | Horizontal bars shrinking left-to-right, pass rate labels. |
| Rolling Metrics | `chart_rolling_metrics.png` | Batch only. Dual-axis: rolling 20-day win rate (L) + expectancy (R). |
| Trade Scatter | `chart_trade_scatter.png` | X=holding duration (min), Y=return%, color=leave cause, size=notional. |

### 4.4 Entry point

**New file**: `reporting/generate_charts.py`

- `generate_daily_charts(trades, funnel, log_dir)` — called from `_generate_reports()`.
- `generate_batch_charts(all_trades, daily_summaries, log_dir)` — called from `generate_batch_reports()`.

---

## Phase 5 — Integration & Testing  **[COMPLETED]**

### 5.1 Wire into replay session

- Pass `FunnelTracker` through `replay_session.py` main loop.
- Pass `config.execution` (with cost params) to `record_close()`.
- Call `generate_daily_charts()` from `_generate_reports()`.

### 5.2 Wire into batch replay

- Collect all trades and daily summaries in `run_batch_replay.py`.
- Call `generate_batch_reports()` and `generate_batch_charts()` at end.

### 5.3 CLI flags

Add to both CLI entry points:
- `--no-charts` — skip chart generation (faster, CSV only).
- `--cost-model` — override cost params: `"commission=0.001425,tax=0.0015"`.

### 5.4 Testing strategy

**Principle**: Five test layers; each catches a different class of bug. Every new or modified module gets at least one test.

#### Layer 1: Unit tests — new modules (~50 tests, 8 files)

| Test File | Covers | Phase |
|-----------|--------|-------|
| `test_trade_path.py` | MAE/MFE tracking + population in `record_close()` | 1 |
| `test_cost_model.py` | Cost calculation (zero costs, known rates, losing trades) | 1 |
| `test_funnel_tracker.py` | Counter increments, reason accumulation, division-by-zero | 1 |
| `test_statistics_report.py` | Median, std, skew, kurtosis, bootstrap CI; edge cases (1 trade, all-win, all-loss) | 2 |
| `test_concentration_report.py` | Top-N contribution, uniform vs skewed PnL, negative total PnL | 2 |
| `test_regime_report.py` | Bucket boundary assignment, per-bucket metrics, empty buckets | 3 |
| `test_daily_equity_report.py` | Cumulative PnL, drawdown, recovery, single-day degenerate case | 3 |
| `test_rolling_metrics.py` | Window < 20 days, rolling win rate/expectancy correctness | 3 |

Helper factory: `_make_trade(symbol, pnl, return_pct, mae_pct, mfe_pct, ...)` in each file, following existing `_make_tick()` / `_make_pos()` patterns.

#### Layer 2: Unit tests — modified modules (~25 tests)

| Modified Module | Key Verification |
|----------------|-----------------|
| `should_enter()` → `tuple[bool, str \| None]` | Update existing 7 tests in `test_entry_filters.py` to unpack tuple; add 1 test per block reason. |
| `record_close()` (costs + MAE/MFE) | Extend `test_replay_session.py` to assert `gross_pnl`, `net_pnl`, `commission`, `tax`, MAE/MFE. |
| `PositionState` / `EntryTrade` / `TradeRecord` new fields | Add to existing `test_records.py` — verify correct defaults. |
| `ExecutionConfig` new fields | Add to `test_config.py` — verify default 0.0 and correct INI parsing. |
| `check_take_profit()` slice counters | New `test_take_profit_tracking.py` — simulate fills, verify counts and PnL. |

#### Layer 3: Report output integration tests (~30 tests, 2 files)

**`tests/unit/test_report_output.py`** — Verify each new CSV report writes correct structure and values using synthetic `TradeRecord` lists + `tmp_path`. Classes: `TestFunnelReport`, `TestStatisticsReport`, `TestConcentrationReport`, `TestTradePathReport`, `TestEnhancedTradeReport`, `TestEnhancedSummaryReport`.

**`tests/unit/test_batch_reports.py`** — Verify `report_daily.csv`, `report_rolling.csv`, `report_regime.csv` with classes for cumulative PnL, drawdown, bucket boundaries.

#### Layer 4: Chart smoke tests (~15 tests, 1 file)

**`tests/unit/test_charts_smoke.py`** — Skip if `matplotlib` not installed. For each chart: verify no crash, output PNG exists, file size > 1KB. Edge cases: n=0, n=1, all-wins, all-losses.

#### Layer 5: Golden test parity

- New `TradeRecord` fields all have defaults → existing `compare_trade_reports()` unaffected.
- Add golden assertion: with zero costs, `gross_pnl == pnl`, `net_pnl == pnl`, `mae_pct ≤ 0`, `mfe_pct ≥ 0`.
- `should_enter()` signature change verified by `mypy` (catches any caller expecting `bool`).
- Optional `@pytest.mark.slow` performance regression test: enhanced tracking < 10% overhead.

#### Verification checkpoints

Run after each phase before proceeding:

```bash
uv run pytest tests -q            # All tests pass
uv run mypy src                   # Type checking (catches should_enter callers)
uv run ruff check src tests       # Linting
uv run pytest tests/golden -m golden -q  # Core PnL unchanged
```

Phase-specific spot-checks: verify new CSV files exist, have correct columns/rows, and batch aggregation sums are consistent.

#### Test count summary

| Layer | Est. Tests |
|-------|-----------|
| Unit — new modules | ~50 |
| Unit — modified modules | ~25 |
| Report output integration | ~30 |
| Chart smoke tests | ~15 |
| Golden parity + perf | ~3 |
| **Total new** | **~123** |

Combined with existing ~100 tests → **~220+ tests**.

#### What we do NOT test

| Omission | Reason |
|----------|--------|
| Chart pixel accuracy | Visual; smoke tests catch crashes |
| Bootstrap CI exact values | Randomized; tested via degenerate cases |
| Multi-process batch | Engine is single-threaded |
| Real market data in unit tests | Covered by golden parity + manual spot-checks |

---

## Output File Summary

### Per-Day Reports

| File | Status | Description |
|------|--------|-------------|
| `report_trades.csv` | Enhanced | +MAE/MFE, costs, path data |
| `report_summary.csv` | Enhanced | +cost rows, net metrics |
| `report_by_category.csv` | Unchanged | — |
| `report_funnel.csv` | **New** | Pipeline stage counts & pass rates |
| `report_trade_paths.csv` | **New** | MAE/MFE, TP slices, peak/trough per trade |
| `report_statistics.csv` | **New** | Median, std, skew, kurtosis, bootstrap CI |
| `report_concentration.csv` | **New** | Top symbols/dates/groups, percentile contributions |
| `chart_*.png` (7 charts) | **New** | Equity, distribution, MAE/MFE, concentration, category, funnel, scatter |

### Batch-Only Reports

| File | Description |
|------|-------------|
| `report_daily.csv` | Equity curve, drawdown, daily metrics |
| `report_rolling.csv` | Rolling 20-day hit rate, expectancy, PF |
| `report_regime.csv` | Performance by market state × entry hour |
| `report_statistics.csv` | Aggregated stats across all trades |
| `report_concentration.csv` | Aggregated concentration |
| `chart_*.png` (4 charts) | Equity, rolling metrics, regime heatmap, distribution |

---

## Implementation Order

```
Phase 1: Data Model & Engine Instrumentation
├── 1.1–1.3  TradeRecord fields, MAE/MFE tracking, TP slice tracking
├── 1.4      Cost model in config + trade_ledger
├── 1.5–1.6  FunnelTracker + should_enter() block reasons
└── Tests: Layers 1–2 for Phase 1 modules

Phase 2: Enhanced Per-Day Reports
├── 2.1–2.6  Enhanced trades, funnel, statistics, concentration, trade paths, cost summary
└── Tests: Layer 1 (stats, concentration) + Layer 3

Phase 3: Multi-Day Aggregation
├── 3.1–3.4  Batch collector, daily equity, rolling metrics, regime report
└── Tests: Layer 1 (regime, equity, rolling) + Layer 3

Phase 4: Visualizations
├── 4.1–4.4  Chart modules, shared style, entry points
└── Tests: Layer 4 (smoke tests)

Phase 5: Integration & Polish
├── 5.1–5.3  Wire into session/batch, CLI flags
└── Tests: Layer 5 (golden parity, performance)
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| MAE/MFE per-tick overhead | Dict lookup is O(1); ~2% overhead expected |
| `should_enter()` signature change breaks callers | `mypy` catches mismatches; only 2 call sites in replay_session.py |
| New TradeRecord fields break golden tests | All new fields have defaults; existing `pnl`/`return_pct` unchanged |
| matplotlib slows CLI startup | Lazy import; `--no-charts` skips entirely |
| Chart generation on headless server | `matplotlib.use("Agg")` — no display needed |

---

## Deferred Work

1. **Shadow analysis** — forward price lookup for blocked signals → `report_filter_effect.csv`
2. **Edge attribution** — multi-pass replay (raw signal / +screen / +filters / full)
3. **Parameter sensitivity** — grid search wrapper → `report_sensitivity.csv`
4. **HTML dashboard** — consolidate charts + CSVs into interactive HTML
5. **Performance regression guard** — ensure enhanced reporting ≤ 5% overhead
