# Dashboard Monitoring Parity Execution Plan

## Objective

Build `signal/dashboard` into a monitoring dashboard that follows the source `StockScreening` dashboard described in `docs/monitoring-and-simulation-architecture-report.md`, while exposing only data this repository can actually produce.

## Source comparison

The source dashboard has Strong Groups, Burst Groups, Intraday Burst Stocks, Strong Stocks, VWAP Watchlist, Signal C summary, DayHigh summary, section toggles, group detail modals, toast/status notifications, and replay controls.

The current `signal` dashboard already has Strong Groups, Strong Singles, VWAP monitor, Signal A monitor, replay controls, Socket.IO live snapshots, and polling fallback.

The `signal` engine also evaluates `SignalAShort`, `SignalB`, and `SignalDayHigh`, but the dashboard currently does not expose them as first-class monitoring surfaces.

## Phases

1. Extend dashboard contracts with module availability metadata, `SignalB`, and `SignalDayHigh` snapshots.
2. Add API endpoints for module status, `SignalB`, and `SignalDayHigh`, including live and replay fallbacks.
3. Persist the new dashboard JSON fields in replay snapshot parquet rows.
4. Extend React types, data loading, and replay normalization for the new fields.
5. Replace the tab-only overview with source-style stacked sections and `localStorage` section toggles.
6. Add unavailable cards for source-only Burst Groups, Intraday Burst Stocks, and Signal C summary.
7. Surface `SignalAShort`, `SignalB`, and `SignalDayHigh` in summaries, badges, detail tables, and toasts.
8. Add group-card modal drilldown for source-dashboard interaction parity.

## Acceptance criteria

- All source-dashboard modules are represented in the main operator view.
- Available modules use real live/replay data from this repo.
- Unavailable source-only modules are clearly labeled and never mocked.
- `SignalAShort`, `SignalB`, and `SignalDayHigh` are visible in the dashboard.
- Existing replay timeline behavior remains intact.

## Out of scope

- Porting Burst Group, Intraday Burst Stock, or Signal C engine logic.
- Replacing React/Vite with the source repo static HTML architecture.
- Full standalone Signal C or DayHigh pages.
- Running validation unless explicitly requested.
