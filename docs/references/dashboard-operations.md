# Dashboard Operations

This document captures the stable operator-facing rules for the repository's dashboard.

Related docs:
- Dashboard design: [../design-docs/dashboard-architecture.md](../design-docs/dashboard-architecture.md)
- Runtime conventions: [runtime-conventions.md](runtime-conventions.md)

## 1. What the dashboard depends on

The dashboard has two deployable parts:
- the FastAPI server under `src/tw_signal_engine/server/`
- the static React build output under `dashboard/dist/`

The server can run without the built frontend, but the browser UI at `/` only exists when `dashboard/dist/` is present.

## 2. Frontend build expectation

Before serving the dashboard through FastAPI, install the frontend dependencies in `dashboard/` and produce a production build with `npm run build`.

If `dashboard/dist/` is missing:
- API endpoints still work
- the mounted SPA does not exist
- opening `/` will not show the dashboard

## 3. Live mode expectations

In live mode the browser expects both:
- Socket.IO event `dashboard:snapshot` for low-latency updates
- REST endpoints as a fallback refresh path

The UI still polls every two seconds in live mode, so API regressions will show up even if the socket path is healthy.

## 4. Replay mode expectations

Replay mode depends on snapshot data, not only the original market data inputs.

Required behavior:
- generate replay snapshot artifacts before using the replay dashboard workflow
- start the server in replay mode only after those artifacts exist
- expect the slider and replay jump controls to be limited to the stored snapshot time range

If replay snapshots are absent, the replay status or jump flow can initialize but the dashboard will have nothing useful to render.

## 5. Intentional unavailable modules

The overview page deliberately shows placeholders for features that do not exist in this engine yet.

Current intentional gaps:
- burst groups
- intraday burst stocks
- Signal C summary

Do not treat those cards as UI bugs unless the underlying module-availability contract changes.

## 6. UI behavior that affects debugging

- Section visibility on the overview page is persisted in browser `localStorage` under `tw-signal-dashboard-sections`.
- Replay snapshots may arrive with `dashboard_*` field names, and the frontend normalizes them before rendering.
- Signal B has no dedicated route and is only visible from the overview page.
- The `/day-high` stock-selection table should match replay eligibility. A row marked selected has passed the current strong-group gates used by replay, including M1/R1 rank, group-rank floor, VWAP band, disposition and previous-limit-up blocks, and max volume-ratio rejection.
- DayHigh `overnight_eligible_now` is not a generic locked-limit-up flag. It should become true only after `exit_time_limit` when `hold_overnight_on_limit_up=true` and the open position is still locked limit-up.
