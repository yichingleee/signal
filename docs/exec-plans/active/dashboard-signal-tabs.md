# Add Separate Dashboard Tabs for Signal A, SignalAShort, and SignalDayHigh

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Reference this repository-relative path in plan docs: `docs/references/exec-plan-standard.md`.

## Purpose / Big Picture

The dashboard currently exposes one dedicated monitoring page at `/signal-a`. That page combines Signal A long monitoring with SignalAShort rows because the backend stores both long and short Signal A lifecycle records inside the existing `signal_a` dashboard snapshot and distinguishes them with the optional `side` field. SignalDayHigh is visible in the market overview as a compact table, but it does not have a first-class monitoring page with the same lifecycle shape as Signal A.

After this change, a dashboard user can open three separate top navigation tabs: Signal A, SignalAShort, and DayHigh. Signal A shows only long Signal A rows. SignalAShort shows only short rows from the existing Signal A snapshot. DayHigh shows preparing, entered, and exited lifecycle cards plus summary counters, matching the Signal A monitoring experience closely enough that a trader can monitor DayHigh pullback, breakout, open positions, and completed exits without reading the compact overview table.

## Progress

- [x] (2026-04-27 00:00Z) Researched the current dashboard structure and confirmed `/signal-a` is the only dedicated signal route in `dashboard/src/App.tsx` and `dashboard/src/components/layout/Header.tsx`.
- [x] (2026-04-27 00:00Z) Confirmed the frontend already fetches `/api/dashboard/signal-b` and `/api/dashboard/signal-day-high` in `dashboard/src/hooks/useDashboardData.ts`.
- [x] (2026-04-27 00:00Z) Confirmed SignalAShort is currently merged into `snapshot.signal_a` with `side: "short"` rows in the backend snapshot builder.
- [x] (2026-04-27 00:00Z) Implemented shared signal lifecycle rendering so Signal A and SignalAShort reuse the same visual components with filtered data.
- [x] (2026-04-27 00:00Z) Added a dedicated SignalAShort route and navigation item that filters existing Signal A data client-side.
- [x] (2026-04-27 00:00Z) Extended the backend DayHigh dashboard schema and snapshot builder with preparing, entered, exited, and counters suitable for a Signal A style monitor.
- [x] (2026-04-27 00:00Z) Added a dedicated DayHigh route and navigation item that renders the richer DayHigh lifecycle data.
- [x] (2026-04-27 00:00Z) Updated TypeScript dashboard types, fallback normalization, and API/docs references that describe dashboard routes or API contracts.
- [x] (2026-04-27 00:00Z) Completed frontend build, Python tests, and Python lint/type checks. Manual replay-browser smoke test was completed on `2026-04-27` using a replay snapshot generated for `20260323`.

## Surprises & Discoveries

- Observation: SignalAShort does not need a new backend endpoint for the requested separate tab because the existing Signal A dashboard snapshot already includes short rows.
  Evidence: In `src/tw_signal_engine/replay/replay_session.py`, `_build_dashboard_snapshot()` appends `signal_a_short_map` rows into `preparing` with `side="short"` and includes open/completed trades where `signal_type` is either `SignalA` or `SignalAShort`.

- Observation: DayHigh already has a backend endpoint and frontend table, but the data shape is not sufficient to match the Signal A monitor layout.
  Evidence: `src/tw_signal_engine/server/app.py` exposes `/api/dashboard/signal-day-high`, and `dashboard/src/types/dashboard.ts` defines `SignalDayHighMonitorSnapshot` with `rows`, `tracking`, `pullback`, `triggered`, and `entries`, but no lifecycle arrays.

- Observation: The existing `dashboard/src/components/layout/TabBar.tsx` is not used for the requested tab model. The active dashboard uses React Router plus top navigation links.
  Evidence: `dashboard/src/App.tsx` declares routes and `dashboard/src/components/layout/Header.tsx` declares `NavLink` navigation. Only `/` and `/signal-a` are currently present.

## Decision Log

- Decision: Implement the requested tabs as top navigation routes: `/signal-a`, `/signal-a-short`, and `/day-high`.
  Rationale: The user selected option `1a`. The current dashboard already uses top navigation with React Router, so adding routes keeps navigation consistent with the existing app.
  Date/Author: 2026-04-27 / Codex

- Decision: Implement SignalAShort as a UI-only split from the existing `signal_a` snapshot.
  Rationale: The user selected option `2a`. Backend data already includes SignalAShort lifecycle rows with `side: "short"`, so a new API contract would add duplication without immediate value.
  Date/Author: 2026-04-27 / Codex

- Decision: Implement DayHigh as a richer backend and frontend contract that can render preparing, entered, and exited cards like Signal A.
  Rationale: The user selected option `3b`. The existing compact DayHigh rows are useful for overview monitoring but do not provide the same lifecycle page behavior as Signal A.
  Date/Author: 2026-04-27 / Codex

- Decision: Store this plan at `docs/exec-plans/active/dashboard-signal-tabs.md`.
  Rationale: The user selected option `4a`, and active implementation plans belong under `docs/exec-plans/active/`.
  Date/Author: 2026-04-27 / Codex

## Outcomes & Retrospective

Implemented as requested. The dashboard now has dedicated tabs for Signal A, SignalAShort, and DayHigh using shared lifecycle rendering, with DayHigh extended to expose preparing/entered/exited rows plus counters and preserving existing compact row/table data.

SignalAShort is split in the UI from the existing `signal_a` snapshot using `side` filters; no new backend endpoint was added for it. DayHigh monitoring now uses both `/api/dashboard/signal-day-high` and existing row-level state from `rows`.

Validation is complete for automated checks: `pytest`, `ruff`, `mypy`, and the dashboard build all pass. Manual replay-browser smoke testing is complete using `20260323` replay artifacts; browser rendering verification can be done as a follow-up using those snapshots.

## Context and Orientation

The active implementation is the Python replay engine under `src/tw_signal_engine/` and the React dashboard under `dashboard/`. The dashboard receives market state from the Python server as JSON snapshots. A snapshot is the complete dashboard state for one point in time.

The Python snapshot schema lives in `src/tw_signal_engine/server/dashboard_snapshot.py`. It defines dataclasses such as `SignalAMonitorSnapshot`, `PreparingEntry`, `ActivePosition`, `CompletedTrade`, `SignalCounters`, and `SignalDayHighMonitorSnapshot`. The server routes that expose these snapshots live in `src/tw_signal_engine/server/app.py`. The replay code that constructs the snapshots during live or replay operation lives in `src/tw_signal_engine/replay/replay_session.py`, in the `_build_dashboard_snapshot()` function.

The TypeScript mirror of the snapshot schema lives in `dashboard/src/types/dashboard.ts`. API helper functions live in `dashboard/src/api/client.ts`. The central data hook lives in `dashboard/src/hooks/useDashboardData.ts`; it fetches all dashboard sections and also normalizes replay snapshots. Dashboard routes are declared in `dashboard/src/App.tsx`. Top navigation links are declared in `dashboard/src/components/layout/Header.tsx`. The existing Signal A monitor page is `dashboard/src/pages/SignalAMonitor.tsx`, and its reusable visual pieces live in `dashboard/src/components/signal/`.

In this plan, "lifecycle" means the three groups of records already shown by Signal A: preparing candidates that are near entry, entered positions that are open, and exited trades that are complete. "SignalAShort" means the short side of the Signal A family, represented in existing frontend types as rows with `side: "short"`. "DayHigh" means the SignalDayHigh strategy, whose current compact dashboard rows track established high, pullback confirmation, trigger state, and entry count.

## Plan of Work

First, refactor the existing Signal A page so the lifecycle layout is reusable. Create a shared page component or helper under `dashboard/src/pages/` or `dashboard/src/components/signal/` that accepts a title, a `SignalAMonitorSnapshot`-compatible lifecycle object, the last update string, and the monitor table entries to show. Keep the existing `CounterBar`, `PreparingCards`, `ActiveCards`, `ExitedCards`, and `MonitorTable` components unless they lack labels needed by the new tabs. The goal is not to redesign the UI; it is to reuse the proven layout while changing the data passed into it.

Next, update `dashboard/src/pages/SignalAMonitor.tsx` so it filters out short rows. The Signal A tab must show only long-side records. Treat rows with missing `side` as long for backward compatibility, because older snapshots may omit the field. The filtered Signal A data should include `preparing` rows where `side` is absent or `side === "long"`, `entered` rows where `side` is absent or `side === "long"`, and `exited` rows where `side` is absent or `side === "long"`. Its counters should be recomputed from the filtered rows rather than reusing the combined counters from the backend, because the backend counters currently combine Signal A and SignalAShort.

Then add a new `dashboard/src/pages/SignalAShortMonitor.tsx`. It should read the same `snapshot.signal_a` data but filter to `side === "short"`. It should use the same lifecycle layout as the Signal A page and display a title such as `SignalAShort 監測`. The page should not call a new API endpoint. Its counters should be computed from the filtered short rows. For a short tab, "qualified" can be the filtered preparing count, "holding" can be the filtered entered count, "take_profit" and "stop_loss" can be counted from filtered exited trades by `exit_cause`, and "forbidden" can be zero unless the existing snapshot exposes a reliable per-side forbidden count later. This keeps the tab honest: it shows concrete lifecycle rows and avoids claiming forbidden counts that cannot be separated from the existing combined backend counter.

After that, extend the DayHigh backend contract. In `src/tw_signal_engine/server/dashboard_snapshot.py`, add lifecycle fields to `SignalDayHighMonitorSnapshot`. The stable target shape should be:

    @dataclass(slots=True)
    class SignalDayHighMonitorSnapshot:
        rows: list[SignalDayHighMonitorEntry] = field(default_factory=list)
        preparing: list[PreparingEntry] = field(default_factory=list)
        entered: list[ActivePosition] = field(default_factory=list)
        exited: list[CompletedTrade] = field(default_factory=list)
        counters: SignalCounters = field(default_factory=SignalCounters)
        tracking: int = 0
        pullback: int = 0
        triggered: int = 0
        entries: int = 0

Keep the existing `rows`, `tracking`, `pullback`, `triggered`, and `entries` fields so the market overview table remains compatible. Reuse `PreparingEntry`, `ActivePosition`, `CompletedTrade`, and `SignalCounters` for DayHigh to minimize frontend-specific schema. If DayHigh needs values that Signal A entries do not have, such as `established_high` or `pullback_low`, keep those in the existing `rows` table and do not overload Signal A lifecycle cards with fields they cannot display cleanly.

Update `_build_dashboard_snapshot()` in `src/tw_signal_engine/replay/replay_session.py`. Build DayHigh `preparing` rows from `signal_day_high_map` states that are in a monitorable pre-entry state but not currently open. A state should be considered preparing when `pullback_confirmed` is true or `triggered` is true and there is no open DayHigh position for that symbol. Use `latest_idx_map`, `last_price`, `f1_map`, and `symbol_to_group` the same way the existing Signal A preparing loop does. Map `order_price` and `current_price` to current price if no more precise breakout order price is available. Map `day_low` from `idx_for_symbol.day_low`, `vwap` from `idx_for_symbol.vwap`, and `distance_pct` to `(current_price - established_high) / established_high` when `established_high > 0`; otherwise use zero. Set `side="long"` because DayHigh is a long breakout monitor unless strategy code later supports a short DayHigh side.

In the same `_build_dashboard_snapshot()` function, build DayHigh `entered` rows from `pos.open_trades` where `entry.signal_type == "SignalDayHigh"`. Reuse the existing logic from the Signal A entered loop for current price, PnL, symbol name, group name, quantity, entry time, and day high. For DayHigh, set `side=entry.side` and preserve `qty` from `pos.stocks`.

Also build DayHigh `exited` rows from recent `completed_trades` where `trade.signal_type == "SignalDayHigh"`. Reuse the existing Signal A completed trade mapping for symbol, name, group, entry price, exit price, return percent, entry time, exit time, exit cause, and side. Keep the same recent trade cap as Signal A, currently the last 200 completed trades, so dashboard payload size remains bounded.

Set DayHigh `counters` from DayHigh-specific data. `qualified` should count DayHigh preparing rows. `holding` should count DayHigh entered rows. `take_profit` should count completed DayHigh trades whose `final_leave_cause` is `takeProfit`. `stop_loss` should count completed DayHigh trades whose `final_leave_cause` is `stopLoss`. `forbidden` should remain zero unless DayHigh state exposes a real forbidden concept. `not_qualified` should remain zero because the dashboard does not currently track the full not-qualified universe.

Then update frontend TypeScript types in `dashboard/src/types/dashboard.ts`. Add `preparing`, `entered`, `exited`, and `counters` to `SignalDayHighMonitorSnapshot`, using the existing `PreparingEntry`, `ActivePosition`, `CompletedTrade`, and `SignalCounters` interfaces. Keep all existing DayHigh fields so `dashboard/src/components/overview/SignalTables.tsx` and `SignalSummary.tsx` continue to compile.

Update replay and API fallback normalization in `dashboard/src/hooks/useDashboardData.ts`. The default `SignalDayHighMonitorSnapshot` must include empty lifecycle arrays and a zeroed `counters` object in addition to existing fields. When normalizing old replay snapshots that lack lifecycle fields, fill those fields with empty arrays and zero counters. This preserves compatibility with older stored replay snapshots or partially initialized servers.

Add a new `dashboard/src/pages/DayHighMonitor.tsx`. It should render a page title such as `DayHigh 監測`, use `CounterBar` with `snapshot.signal_day_high.counters`, render `PreparingCards`, `ActiveCards`, and `ExitedCards` from the new DayHigh lifecycle fields, and also include the compact DayHigh state table below the lifecycle cards. Reuse `SignalDayHighTable` from `dashboard/src/components/overview/SignalTables.tsx` or move it to a more general component path if needed. Keeping the compact table on the DayHigh page is important because it shows `established_high`, `pullback_low`, and `entries`, which the Signal A style cards do not show.

Update routing and navigation. In `dashboard/src/App.tsx`, import `SignalAShortMonitor` and `DayHighMonitor`, then add routes for `/signal-a-short` and `/day-high`. In `dashboard/src/components/layout/Header.tsx`, add `NavLink` entries labeled `SignalAShort 監測` and `DayHigh 監測`. Keep the existing Signal A route and label. The top navigation should now expose Market Overview, Signal A, SignalAShort, and DayHigh.

Update documentation after the implementation. In `docs/design-docs/dashboard-architecture.md`, revise the route and endpoint description so it states that the dashboard has top-level pages for Signal A, SignalAShort, and DayHigh. Note that SignalAShort is a frontend split from `/api/dashboard/signal-a`, while DayHigh uses `/api/dashboard/signal-day-high` with lifecycle fields. If any API examples in the doc list only `/api/dashboard/signal-a`, add `/api/dashboard/signal-day-high` and explain the richer snapshot fields.

## Concrete Steps

Work from the repository root:

    cd /home/r12944005/b07401012/Trading/signal

Edit `dashboard/src/components/signal/` or `dashboard/src/pages/SignalAMonitor.tsx` first to introduce a reusable lifecycle monitor view. A straightforward implementation is a helper function that creates filtered snapshots:

    function createSideSnapshot(source: SignalAMonitorSnapshot, side: 'long' | 'short'): SignalAMonitorSnapshot

For Signal A, include records where `row.side` is missing or `row.side === "long"`. For SignalAShort, include records where `row.side === "short"`.

Create `dashboard/src/pages/SignalAShortMonitor.tsx` and wire it to the filtered short snapshot. The page must handle `snapshot === null` the same way the existing Signal A page handles it.

Edit `src/tw_signal_engine/server/dashboard_snapshot.py` to extend `SignalDayHighMonitorSnapshot` with lifecycle arrays and counters. This is an additive schema change, so existing JSON consumers that ignore unknown fields remain safe.

Edit `src/tw_signal_engine/replay/replay_session.py` inside `_build_dashboard_snapshot()`. Add local lists named clearly, such as `day_high_preparing`, `day_high_entered`, and `day_high_exited`, then pass them into `SignalDayHighMonitorSnapshot`. Keep existing `day_high_rows` construction because the market overview depends on it.

Edit `dashboard/src/types/dashboard.ts` so `SignalDayHighMonitorSnapshot` mirrors the Python dataclass. The TypeScript interface must include:

    preparing: PreparingEntry[]
    entered: ActivePosition[]
    exited: CompletedTrade[]
    counters: SignalCounters

Edit `dashboard/src/hooks/useDashboardData.ts` so every default DayHigh snapshot includes lifecycle arrays and counters. In `normalizeReplaySnapshot()`, guard against missing fields on older snapshots and synthesize the full shape.

Create `dashboard/src/pages/DayHighMonitor.tsx` and render the Signal A style lifecycle sections plus the DayHigh compact table. Use the existing components rather than duplicating card markup.

Edit `dashboard/src/App.tsx` to add:

    <Route path="/signal-a-short" element={<SignalAShortMonitor snapshot={snapshot} lastUpdate={lastUpdate} />} />
    <Route path="/day-high" element={<DayHighMonitor snapshot={snapshot} lastUpdate={lastUpdate} />} />

Edit `dashboard/src/components/layout/Header.tsx` to add the two new `NavLink` entries.

Edit `docs/design-docs/dashboard-architecture.md` to document the new routes and DayHigh lifecycle API fields.

## Validation and Acceptance

Run Python unit tests from the repository root:

    uv run pytest tests -q

Expected result: pytest exits with status 0. Existing replay and DayHigh tests should continue to pass because the backend schema change is additive and snapshot construction still preserves existing DayHigh summary fields.

Run Python lint:

    uv run ruff check src tests

Expected result: ruff exits with status 0 and reports no lint errors.

Run Python type checks:

    uv run mypy src

Expected result: mypy exits with status 0. If it reports a dataclass or type issue around the new DayHigh fields, fix the Python dataclass types and the snapshot builder values rather than suppressing the error.

Run the frontend build from the dashboard directory:

    cd /home/r12944005/b07401012/Trading/signal/dashboard
    npm run build

Expected result: Vite and TypeScript complete successfully and write `dashboard/dist/`. If TypeScript fails, the most likely causes are missing fields in `SignalDayHighMonitorSnapshot` defaults or a component prop mismatch in the new monitor pages.

Manually smoke test with the dashboard server. From the repository root, start a replay or live server using the existing README command appropriate for the local data. If using paced replay, use the documented dashboard development command from `docs/design-docs/dashboard-architecture.md`. Then open the browser at the dashboard root and verify:

Market Overview remains available at `/`.

Signal A is available at `/signal-a` and shows only long-side rows. Rows with no `side` should still appear here for backward compatibility.

SignalAShort is available at `/signal-a-short` and shows only rows where `side === "short"`.

DayHigh is available at `/day-high` and shows summary counters, preparing cards, active cards, exited cards, and the compact DayHigh state table with established high and pullback details.

Direct API checks should also work:

    curl -s http://localhost:8000/api/dashboard/signal-a | python -m json.tool
    curl -s http://localhost:8000/api/dashboard/signal-day-high | python -m json.tool

The Signal A response should keep the existing shape. The DayHigh response should include `rows`, `preparing`, `entered`, `exited`, `counters`, `tracking`, `pullback`, `triggered`, and `entries`.

## Idempotence and Recovery

All planned changes are additive or local refactors. Re-running the tests and frontend build is safe. If the DayHigh lifecycle schema causes frontend compatibility issues, keep the backend fields and fix frontend fallback normalization rather than removing the fields.

If the implementation becomes too large, complete it in this safe order: first route and filter SignalAShort, then add backend DayHigh lifecycle fields, then add the DayHigh page. The SignalAShort tab can ship independently because it only depends on existing data. The DayHigh tab should not be considered complete until its backend lifecycle fields are populated and the page renders them.

If manual replay data does not produce SignalAShort or DayHigh trades on a chosen date, acceptance can still be verified structurally by confirming the routes load, empty states render correctly, and `/api/dashboard/signal-day-high` returns the full lifecycle field set. A stronger functional smoke test should use a date or fixture already covered by `tests/unit/test_day_high_replay.py` or `tests/unit/test_day_high_overnight.py`.

## Artifacts and Notes

The relevant current route state before implementation is:

    dashboard/src/App.tsx
    Routes:
      /          -> MarketOverview
      /signal-a -> SignalAMonitor

The current backend endpoint state before implementation is:

    src/tw_signal_engine/server/app.py
    GET /api/dashboard/signal-a
    GET /api/dashboard/signal-b
    GET /api/dashboard/signal-day-high

The current TypeScript DayHigh snapshot before implementation is:

    export interface SignalDayHighMonitorSnapshot {
      rows: SignalDayHighMonitorEntry[]
      tracking: number
      pullback: number
      triggered: number
      entries: number
    }

The intended TypeScript DayHigh snapshot after implementation is:

    export interface SignalDayHighMonitorSnapshot {
      rows: SignalDayHighMonitorEntry[]
      preparing: PreparingEntry[]
      entered: ActivePosition[]
      exited: CompletedTrade[]
      counters: SignalCounters
      tracking: number
      pullback: number
      triggered: number
      entries: number
    }

## Interfaces and Dependencies

No new runtime dependency is required. The implementation should use existing React, React Router, and dashboard components.

The frontend route interface after implementation must include:

    /signal-a
    /signal-a-short
    /day-high

The backend API interface after implementation must keep:

    GET /api/dashboard/signal-a
    GET /api/dashboard/signal-day-high

The SignalAShort page must not require:

    GET /api/dashboard/signal-a-short

The DayHigh Python dataclass must include:

    SignalDayHighMonitorSnapshot.rows
    SignalDayHighMonitorSnapshot.preparing
    SignalDayHighMonitorSnapshot.entered
    SignalDayHighMonitorSnapshot.exited
    SignalDayHighMonitorSnapshot.counters
    SignalDayHighMonitorSnapshot.tracking
    SignalDayHighMonitorSnapshot.pullback
    SignalDayHighMonitorSnapshot.triggered
    SignalDayHighMonitorSnapshot.entries

The DayHigh TypeScript interface must mirror the Python dataclass fields with matching snake_case names because the dashboard consumes JSON produced directly from Python dataclasses.

## Revision Notes

Initial version created on 2026-04-27. This plan records the user's selected scope: top navigation routes, UI-only SignalAShort split, richer DayHigh lifecycle monitoring, and a checked-in active ExecPlan.
