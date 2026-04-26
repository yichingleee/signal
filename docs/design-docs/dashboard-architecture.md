# Dashboard Architecture

This document describes the dashboard that is actually implemented in the repository today: the FastAPI server under `src/tw_signal_engine/server/` and the React SPA under `dashboard/`.

Related docs:
- Live data provider and session-hook design: [live-data-architecture.md](live-data-architecture.md)
- Dashboard runtime prerequisites and operator gotchas: [../references/dashboard-operations.md](../references/dashboard-operations.md)
- Top-level replay architecture: [runtime-architecture.md](runtime-architecture.md)

## 1. Scope and repo map

The dashboard is a monitoring UI for engine state, not a control plane for strategy configuration. It surfaces strong groups, strong singles, VWAP proximity, Signal A, SignalAShort, Signal B, and SignalDayHigh state that is already produced by the Python engine.

Primary implementation files:
- Backend API and SPA mounting: `src/tw_signal_engine/server/app.py`
- Thread-safe live bridge: `src/tw_signal_engine/server/live_state.py`
- Canonical snapshot schema: `src/tw_signal_engine/server/dashboard_snapshot.py`
- Frontend shell and routing: `dashboard/src/App.tsx`
- Frontend data transport and mode switching: `dashboard/src/hooks/useDashboardData.ts`
- Frontend shared types: `dashboard/src/types/dashboard.ts`

## 2. Runtime model

The backend exposes the same dashboard API surface in two modes.

- `live`: `LiveState` is updated by engine session hooks and pushed to the UI over Socket.IO, with REST polling kept as a fallback.
- `replay`: `ReplayManager` serves stored snapshots and the UI drives time travel with `POST /api/replay/jump`.

The frontend is mode-aware for transport only. It does not maintain separate page trees for live and replay data.

## 3. Backend responsibilities

`src/tw_signal_engine/server/app.py` owns three dashboard-facing concerns.

### 3.1 API surface

The UI consumes these endpoints:
- `GET /api/status`: discover current server mode and basic readiness.
- `GET /api/dashboard/groups`: strong-group cards and ranked members.
- `GET /api/dashboard/singles`: strong-stock table.
- `GET /api/dashboard/vwap`: VWAP watchlist.
- `GET /api/dashboard/signal-a`: Signal A and SignalAShort lifecycle data.
- `GET /api/dashboard/signal-b`: Signal B monitor rows and counters.
- `GET /api/dashboard/signal-day-high`: SignalDayHigh monitor rows and counters.
- `GET /api/dashboard/modules`: module availability metadata used for parity placeholders.
- `GET /api/dashboard/status`: dashboard-specific readiness metadata.
- `GET /api/replay/status`: replay time range for the slider.
- `POST /api/replay/jump`: return the snapshot at or before a requested minute.

### 3.2 Live push path

In live mode the server emits `dashboard:snapshot` over Socket.IO. The push loop deduplicates on snapshot identity before sending so the browser does not re-render identical data continuously between minute-boundary snapshot updates.

### 3.3 Static serving

If `dashboard/dist/` exists, FastAPI mounts it at `/` after registering API routes. This is why a missing frontend build produces a working API server with no dashboard UI.

## 4. Snapshot contract

`dashboard_snapshot.py` is the schema boundary between Python and TypeScript. `dashboard/src/types/dashboard.ts` mirrors that schema for the UI.

The top-level snapshot contains:
- `timestamp`, `time_raw`, `tick_count`
- `groups`
- `singles`
- `vwap_monitor`
- `signal_a`
- `signal_b`
- `signal_day_high`
- `modules`

Important design detail: the frontend also normalizes replay payloads that still use stored `dashboard_*` field names. That compatibility logic lives in `useDashboardData.ts`, which lets replay snapshots and live snapshots feed the same React components.

## 5. Frontend structure

The SPA is a small React 19 + TypeScript + Vite application.

### 5.1 Application shell

`dashboard/src/App.tsx` composes:
- `Header`
- `StatusBar`
- route content via `react-router-dom`
- `TimelineSlider` when the backend reports replay mode

### 5.2 Route map

The implemented routes are:
- `/`: `MarketOverview`
- `/signal-a`: `SignalAMonitor`
- `/signal-a-short`: `SignalAShortMonitor`
- `/day-high`: `DayHighMonitor`

There is no dedicated Signal B route. Signal B is presented on the overview page as a monitored section.

### 5.3 Overview page

`dashboard/src/pages/MarketOverview.tsx` is the densest page in the UI.

It renders:
- strong groups via `GroupGrid`
- strong stocks via `SinglesTable`
- VWAP watchlist via `VWAPTable`
- cross-signal summaries via `SignalSummary`
- Signal B and SignalDayHigh tables inside collapsible sections
- unavailable parity cards for burst groups, intraday burst stocks, and Signal C
- toast notifications for `near_vwap`, Signal B `trade_zone` or `triggered`, and SignalDayHigh `pullback` or `triggered`

Section open/closed state is persisted in browser `localStorage` under `tw-signal-dashboard-sections`.

### 5.4 Signal lifecycle pages

`SignalAMonitor`, `SignalAShortMonitor`, and `DayHighMonitor` share the same layout pattern through `components/signal/SignalMonitorLayout.tsx`.

That shared layout always shows:
- counters
- preparing cards
- active position cards
- exited trade cards
- a monitor table when the page needs per-symbol rows

This keeps the signal-family pages visually aligned while letting each route supply its own data slice.

## 6. Transport behavior in the browser

`useDashboardData.ts` centralizes all mode switching.

Live mode behavior:
- open a Socket.IO connection
- listen for `dashboard:snapshot`
- fall back to REST polling every two seconds
- mark the UI stale if no fresh data is received for a while

Replay mode behavior:
- disconnect the socket
- fetch replay status
- jump to the earliest available minute
- drive slider jumps with `POST /api/replay/jump`
- emulate playback locally by stepping one minute every second while the play toggle is on

## 7. Intentional parity gaps

The overview intentionally shows unavailable cards for modules the engine does not implement yet. Today those placeholders cover burst groups, intraday burst stocks, and Signal C summary, and they are backed by module metadata instead of being ad hoc hidden UI.

## 8. Essential gotchas

- The dashboard UI is served only from built static assets in `dashboard/dist/`.
- Replay pages depend on stored snapshot data, not just raw replay inputs.
- The frontend tolerates both live snapshot keys and stored replay `dashboard_*` keys because replay data is persisted in a different field shape.
- Signal B is an overview section, not a first-class route.

## 9. Source-of-truth rule

When the dashboard docs drift, prefer these code locations over historical notes:
- route and shell behavior: `dashboard/src/App.tsx`
- transport and replay behavior: `dashboard/src/hooks/useDashboardData.ts`
- API contract: `src/tw_signal_engine/server/app.py`
- schema: `src/tw_signal_engine/server/dashboard_snapshot.py` and `dashboard/src/types/dashboard.ts`
