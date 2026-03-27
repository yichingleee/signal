# Traded-Symbol Intraday Chart Execution Plan

> **Goal**: For each stock traded by the strategy on a replay day, generate a per-stock intraday price-time PNG that clearly marks VWAP, signal, entry, and exit points with reason labels.
> **Scope baseline (confirmed)**: PNG output, replay-row granularity, annotate all signal/entry/exit events for traded symbols, session cumulative VWAP, and no new feature flag (always part of normal chart generation path).

---

## Objective And Done Definition

### Objective

Extend the reporting/charting pipeline so daily replay output includes one intraday timeline chart per traded symbol, with enough annotation detail to explain each executed trade lifecycle on that symbol.

### Done Definition

A replay day is considered complete for this feature when all of the following are true:

1. For every symbol present in `completed_trades`, a file named `chart_trade_day_<symbol>.png` exists in that day’s log directory.
2. Each chart includes:
   - intraday traded-price line (replay granularity)
   - session cumulative VWAP line
   - all executed signal markers
   - all entry markers and entry-reason labels
   - all exit markers and exit-reason labels
3. Labels are readable and deterministic (stable ordering and placement across runs).
4. Existing chart generation remains compatible with `--no-charts` (global chart kill-switch remains authoritative).
5. Unit + smoke + integration tests for this feature pass.

---

## Current-State Findings

1. The engine currently writes aggregate/day-level charts via `reporting/generate_charts.py` and `reporting/charts/*`, but no per-symbol intraday timeline chart exists.
2. `TradeRecord` contains `entry_time_raw`, `entry_price`, `exit_time_raw`, and `final_leave_cause`, but no explicit `exit_price` field, which is needed for exact exit-point plotting.
3. The replay loop already processes tick-level data at the required granularity, but it does not persist a full-day tick trace per traded symbol.
4. Existing order logs include entry/leave events, but deriving clean plotting series solely from log CSV adds avoidable parsing coupling and can lose VWAP continuity context.

---

## Design Decisions

### Decision 1: Full-Day Intraday Series Acquisition

Use a dedicated post-trade trace extraction pass for traded symbols only (second stream pass over OTC+TSE files with `tick_filter=traded_symbols`).

Rationale:
- Guarantees full-day line from session open even when entry occurs late.
- Avoids high memory cost of buffering every candidate symbol during main replay.
- Reuses deterministic stream merge path already in production (`merge_market_streams`).

### Decision 2: Event Source of Truth

Use `TradeRecord` as the primary event source for signal/entry/exit annotations, with one schema addition:
- add `exit_price: float` to `TradeRecord` and populate it in `trade_ledger.record_close()`.

Rationale:
- Keeps chart logic dependent on typed records, not ad hoc CSV parsing.
- Ensures marker price matches execution accounting.

### Decision 3: Signal Annotation Semantics

For executed trades, treat signal time as entry tick time (current engine behavior executes on trigger tick). Annotate both signal and entry at that timestamp with offset labels so both are visible.

Rationale:
- Matches current replay flow (`evaluate_signal_*` -> `should_enter` -> `execute_entry` in same tick).
- Meets requirement to explicitly label signal and entry without changing strategy behavior.

### Decision 4: Rollout Behavior

No additional config flag. The feature is always part of daily chart generation whenever charts are enabled. Existing `--no-charts` continues to disable all charts.

---

## Target Outputs

For a day with traded symbols `{2330, 2317}` under `./log/<folder>/<date>/`:

- `chart_trade_day_2330.png`
- `chart_trade_day_2317.png`

Optional manifest (recommended for discoverability):

- `report_trade_day_charts.csv` with columns:
  - `Symbol`
  - `ChartFile`
  - `TradeCount`
  - `SignalCount`
  - `EntryCount`
  - `ExitCount`

Manifest is not required for correctness but makes downstream batch inspection easier.

---

## Implementation Plan

## Phase 1 — Data Contracts And Minimal Schema Extension ✅ COMPLETED

### 1.1 Extend trade record with exit price ✅ COMPLETED

**Files**
- `src/tw_signal_engine/records/market_event_records.py`
- `src/tw_signal_engine/execution/trade_ledger.py`
- `tests/unit/test_records.py`
- `tests/unit/test_replay_session.py` (or existing close-path tests)

**Changes**
1. Add `exit_price: float = 0.0` to `TradeRecord`.
2. In `record_close()` set `exit_price=price / 10000.0` (using close tick price actually used for leave decision path).
3. Keep all existing PnL/cost calculations unchanged.

**Acceptance**
- Existing tests pass with new default.
- Exit price is populated for normal exits and force-close path.

### 1.2 Introduce internal chart timeline models ✅ COMPLETED

**New file**
- `src/tw_signal_engine/reporting/charts/trade_day_models.py`

**Dataclasses**
- `IntradayPoint(time_raw: int, price: float, vwap: float)`
- `TradeMarker(kind: str, time_raw: int, price: float, label: str)`
- `SymbolTradeDay(symbol: str, points: list[IntradayPoint], markers: list[TradeMarker])`

**Acceptance**
- Types are mypy-clean and used by trace-builder + renderer modules.

---

## Phase 2 — Traded-Symbol Intraday Trace Builder ✅ COMPLETED

### 2.1 Build replay-granularity price/VWAP traces ✅ COMPLETED

**New file**
- `src/tw_signal_engine/reporting/build_trade_day_traces.py`

**Public function**
- `build_trade_day_traces(trade_date: str, data_dir: str, traded_symbols: set[str], prev_day_limit_up: dict[str, bool]) -> dict[str, list[IntradayPoint]]`

**Algorithm**
1. Return empty dict if `traded_symbols` is empty.
2. Run `merge_market_streams("OTC", trade_date, "TSE", trade_date, ...)` with `tick_filter=traded_symbols`.
3. For each trade tick (`tick.trade_code == 1`, positive price/qty):
   - append price point
   - update cumulative notional/volume per symbol
   - compute session VWAP = cum_notional / cum_volume
4. Store all points per symbol in chronological order.

**Edge handling**
- If cumulative volume is zero at a point (defensive), fallback VWAP to current price.
- Skip malformed/zero-price ticks.

**Acceptance**
- Generated series length equals number of accepted trade ticks per symbol.
- Time order strictly non-decreasing.

### 2.2 Build annotation markers from completed trades ✅ COMPLETED

**In same module**
- `build_trade_markers(trades: list[TradeRecord]) -> dict[str, list[TradeMarker]]`

**Marker spec per trade**
1. Signal marker
   - `kind="signal"`
   - `time=entry_time_raw`
   - `price=entry_price`
   - `label=f"Signal {signal_type} ({enter_cause}) @ {HH:MM:SS}"`
2. Entry marker
   - `kind="entry"`
   - `time=entry_time_raw`
   - `price=entry_price`
   - `label=f"Entry {entry_price:.2f} ({enter_cause})"`
3. Exit marker
   - `kind="exit"`
   - `time=exit_time_raw`
   - `price=exit_price`
   - `label=f"Exit {exit_price:.2f} ({final_leave_cause})"`

**Acceptance**
- Marker count is exactly `3 * len(trades_for_symbol)`.
- Labels include reason text for signal/entry/exit.

---

## Phase 3 — Per-Symbol Trade-Day Chart Renderer ✅ COMPLETED

### 3.1 Add dedicated chart module ✅ COMPLETED

**New file**
- `src/tw_signal_engine/reporting/charts/trade_day_timeline.py`

**Public function**
- `plot_trade_day_timeline(symbol_day: SymbolTradeDay, log_dir: str) -> None`

**Chart layout**
1. Single panel (default 14x7 @ existing DPI) for readability.
2. Price line: solid primary color.
3. VWAP line: dashed accent color.
4. Marker glyphs:
   - signal: triangle (`^`)
   - entry: circle (`o`)
   - exit: X (`X`)
5. Marker annotation boxes with lightweight collision handling:
   - sort markers by `(time_raw, kind_priority)`
   - apply alternating y-offset tiers for markers sharing near-identical x positions
6. Title example: `<symbol> Intraday Price vs VWAP (YYYYMMDD)`.
7. Legend includes all plotted components.

**File naming**
- `chart_trade_day_<symbol>.png`

**Acceptance**
- Chart is generated for symbols with at least one point and one trade marker.
- Annotation text includes signal type and leave cause.

### 3.2 Styling integration ✅ COMPLETED

**Files**
- `src/tw_signal_engine/reporting/charts/_style.py`
- optionally `src/tw_signal_engine/reporting/charts/__init__.py`

**Changes**
- Reuse existing palette/backend helpers.
- Add small helper for marker annotation style (box alpha, font size) if needed.

**Acceptance**
- Visual style consistent with existing report chart suite.

---

## Phase 4 — Wiring Into Report Pipeline ✅ COMPLETED

### 4.1 Daily chart entrypoint integration ✅ COMPLETED

**Files**
- `src/tw_signal_engine/reporting/generate_charts.py`
- `src/tw_signal_engine/replay/replay_session.py`

**Changes**
1. Extend `generate_daily_charts(...)` signature to include the context required for trace extraction:
   - `trade_date`
   - `data_dir`
   - `prev_day_limit_up`
2. In `_generate_reports(...)`, pass these values when invoking `generate_daily_charts(...)`.
3. In `generate_daily_charts(...)`:
   - keep current aggregate charts
   - derive traded symbol set from `trades`
   - build traces and markers
   - generate one timeline chart per traded symbol

**Compatibility**
- Preserve existing behavior when `len(trades) < 2` for aggregate charts, but still generate per-symbol timeline charts if at least one trade exists.
- Preserve `--no-charts` behavior (skip everything when true).

**Acceptance**
- Single-trade day still gets per-symbol trade-day chart.
- Existing aggregate charts unchanged for multi-trade days.

### 4.2 Optional chart manifest writer ✅ COMPLETED

**New file (optional but recommended)**
- `src/tw_signal_engine/reporting/build_trade_day_chart_manifest.py`

**Behavior**
- Write `report_trade_day_charts.csv` mapping symbol to generated PNG and event counts.

**Acceptance**
- Manifest matches actual chart files.

---

## Phase 5 — Test Plan ✅ COMPLETED

### 5.1 Unit tests: new trace/marker logic ✅ COMPLETED

**New file**
- `tests/unit/test_trade_day_traces.py`

**Cases**
1. `build_trade_markers` creates 3 markers per trade with reason text.
2. Multiple trades same symbol maintain deterministic marker ordering.
3. Multi-symbol split is correct.
4. Empty input returns empty structures.

### 5.2 Unit tests: renderer smoke + edge cases ✅ COMPLETED

**File**
- `tests/unit/test_charts_smoke.py` (extend)

**Add class**
- `TestTradeDayTimelineChart`

**Cases**
1. Single-trade symbol chart renders and file size > 1KB.
2. Multiple markers at same timestamp still render (no crash).
3. Missing/empty point list skips output cleanly.

### 5.3 Integration tests: daily chart pipeline ✅ COMPLETED

**New file**
- `tests/unit/test_generate_trade_day_charts.py`

**Cases**
1. One trade -> one `chart_trade_day_<symbol>.png` produced.
2. Two symbols -> two files.
3. `no_charts=True` path produces none.
4. Aggregate chart generation still invoked under prior conditions.

### 5.4 Regression tests: schema extension ✅ COMPLETED

**Files**
- `tests/unit/test_records.py`
- `tests/unit/test_replay_session.py` / close-path tests

**Cases**
1. `TradeRecord.exit_price` default value.
2. Exit price populated on normal close and force-close.

---

## Phase 6 — Documentation Updates ✅ COMPLETED

**Files**
- `docs/references/runtime-conventions.md`
- `docs/design-docs/runtime-architecture.md`
- optionally `docs/product-specs/current-strategy-spec.md` (output artifacts section)

**Updates**
1. Add new per-symbol PNG artifact naming convention.
2. Clarify annotation contents (VWAP, signal, entry, exit with reasons).
3. Note that charts remain disabled globally via existing `--no-charts`.

---

## Performance And Risk Management

## Performance Expectations

- Additional I/O/CPU from second pass is proportional to replay file size, but symbol filtering and low memory footprint keep implementation practical.
- No impact on strategy decisions or PnL path (report-only feature).

## Key Risks

1. **Chart label overlap on high-activity symbols**
   - Mitigation: deterministic stagger offsets + concise labels.
2. **Second-pass runtime overhead**
   - Mitigation: limit extraction to `traded_symbols`; skip when no trades.
3. **Data mismatch between markers and trace points**
   - Mitigation: use `TradeRecord` price/time fields as marker source of truth; unit test exact mapping.

---

## Verification Commands

```bash
uv run pytest tests/unit/test_trade_day_traces.py -q
uv run pytest tests/unit/test_generate_trade_day_charts.py -q
uv run pytest tests/unit/test_charts_smoke.py -q
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```

---

## File Change Summary (Planned)

### New files

- `src/tw_signal_engine/reporting/build_trade_day_traces.py`
- `src/tw_signal_engine/reporting/charts/trade_day_models.py`
- `src/tw_signal_engine/reporting/charts/trade_day_timeline.py`
- `tests/unit/test_trade_day_traces.py`
- `tests/unit/test_generate_trade_day_charts.py`
- `src/tw_signal_engine/reporting/build_trade_day_chart_manifest.py` (optional)

### Modified files

- `src/tw_signal_engine/records/market_event_records.py`
- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/reporting/generate_charts.py`
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/reporting/charts/_style.py` (if annotation helper added)
- `tests/unit/test_charts_smoke.py`
- `tests/unit/test_records.py`
- `docs/references/runtime-conventions.md`
- `docs/design-docs/runtime-architecture.md`

---

## Execution Order Recommendation

1. Phase 1 (schema + models) and tests first.
2. Phase 2 (trace + markers) next with pure unit coverage.
3. Phase 3 renderer and smoke tests.
4. Phase 4 pipeline wiring and integration tests.
5. Phase 6 docs and final repo-wide validation.

This order keeps risk low: data contracts first, chart rendering second, orchestration wiring last.
