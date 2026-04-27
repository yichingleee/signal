# Align SignalDayHigh Engine State With Dashboard Display

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Reference this repository-relative path in plan docs: `docs/references/exec-plan-standard.md`.

## Purpose / Big Picture

After this change, a dashboard user can read the DayHigh route and the DayHigh summary on the market overview page without guessing how they relate to the Python engine. The UI will show the same state progression the engine actually evaluates: an anchored intraday high, a confirmed pullback from that high, a breakout attempt, and then either a live holding or a completed exit. The main observable improvement is that the DayHigh summary counts, table rows, and lifecycle cards will describe the same population of symbols instead of mixing hidden engine state with partially exposed UI state.

Today the dashboard already has a dedicated `DayHigh 監測` route, but the page is only partially aligned with the engine. The engine tracks a DayHigh pattern from the first valid high onward, while the dashboard table hides that tracking phase entirely and only starts listing a symbol after pullback or trigger. The result is that the overview summary can report tracking activity that the DayHigh table does not show, and the trigger rows do not preserve enough pre-breakout context to explain why the signal fired.

## Progress

- [x] (2026-04-27 00:00Z) Investigated the current SignalDayHigh evaluator, replay snapshot builder, FastAPI endpoint, and React DayHigh pages.
- [x] (2026-04-27 00:00Z) Confirmed that the dashboard already has a dedicated DayHigh route at `dashboard/src/pages/DayHighMonitor.tsx` and a compact DayHigh table on the overview page.
- [x] (2026-04-27 00:00Z) Confirmed the current parity gaps that must drive the implementation plan: hidden tracking rows, ambiguous summary counters, and loss of trigger-time context after breakout reset.
- [x] (2026-04-27 00:00Z) Authored this implementation plan and added it under `docs/exec-plans/active/`.
- [x] (2026-04-27 00:20Z) Implement backend snapshot changes so DayHigh dashboard data exposes every user-visible phase and preserves trigger-time context.
- [x] (2026-04-27 00:20Z) Implement frontend DayHigh summary and table changes so counts, labels, and rows describe the same population of symbols.
- [x] (2026-04-27 00:22Z) Add regression tests and manual replay verification for the new DayHigh display behavior.

## Surprises & Discoveries

- Observation: the engine and the dashboard disagree about what “tracking” means today.
  Evidence: `src/tw_signal_engine/replay/replay_session.py` computes `tracking` as `sum(1 for state in signal_day_high_map.values() if state.established_high > 0)`, which includes any symbol with an anchor high, even if it is no longer in the pure pre-pullback phase.

- Observation: the DayHigh table never renders a row with `status="tracking"` even though the snapshot builder has code for that status.
  Evidence: `src/tw_signal_engine/replay/replay_session.py` only appends state rows when `pullback_confirmed`, `triggered`, or `entries > 0` is true. A pure tracking-only state does not pass that guard, so the `else "tracking"` branch is effectively unreachable for normal rows.

- Observation: the evaluator resets the state before returning a breakout trigger, so the dashboard cannot reconstruct the exact breakout context from the mutable state alone.
  Evidence: `src/tw_signal_engine/signals/evaluate_signal_day_high.py` saves `trigger_high = state.established_high`, calls `_reset_for_new_high(state, price, match_time_str)`, then sets `state.triggered = True` and returns. The previous established high and pullback low are overwritten before the snapshot builder reads the state.

- Observation: the schema already carries more DayHigh information than the current UI shows.
  Evidence: `src/tw_signal_engine/server/dashboard_snapshot.py` includes `established_high_time` and `pullback_time` in `SignalDayHighMonitorEntry`, but `dashboard/src/components/overview/SignalTables.tsx` currently renders only symbol, name, group, established high, pullback low, entries, and status.

- Observation: the current DayHigh page reuses the generic Signal A lifecycle counters, which are useful for positions but not sufficient for DayHigh state progression.
  Evidence: `dashboard/src/pages/DayHighMonitor.tsx` passes `snapshot.signal_day_high.counters` into `SignalMonitorLayout`, while the overview summary in `dashboard/src/components/overview/SignalSummary.tsx` separately uses `tracking`, `pullback`, `triggered`, and `entries`.

## Decision Log

- Decision: treat backend snapshot changes as in scope instead of trying to solve the problem with UI-only relabeling.
  Rationale: the current data contract does not expose a complete DayHigh progression, and the evaluator discards breakout context before the snapshot is built. A UI-only change would still leave the dashboard unable to explain real engine behavior.
  Date/Author: 2026-04-27 / Codex

- Decision: define the target UI around explicit DayHigh phases rather than around the generic Signal A counter vocabulary.
  Rationale: DayHigh is a breakout strategy with a pre-entry state machine, not a near-VWAP strategy. Users need to see where each symbol sits in the DayHigh sequence, especially before any entry occurs.
  Date/Author: 2026-04-27 / Codex

- Decision: preserve the existing route names and top-level navigation structure while changing the DayHigh page contents.
  Rationale: the repository already ships `/day-high` as a first-class route in `dashboard/src/App.tsx` and `dashboard/src/components/layout/Header.tsx`. The requested work is display correctness, not navigation redesign.
  Date/Author: 2026-04-27 / Codex

## Outcomes & Retrospective

This implementation completed a parity-focused DayHigh refresh by making the engine snapshot, frontend contract, and UI representation share explicit DayHigh phase semantics. The dashboard now exposes strategy-state rows for tracking/pullback/triggered/holding, preserves breakout context, and counts from one source (`phase_counts`) for consistency.

## Context and Orientation

The active trading engine is the Python replay and live server under `src/tw_signal_engine/`. The dashboard is the React single-page app under `dashboard/`. The backend emits a structured “snapshot,” which is a complete dashboard payload for one point in time. The Python snapshot schema lives in `src/tw_signal_engine/server/dashboard_snapshot.py`, and the matching TypeScript interfaces live in `dashboard/src/types/dashboard.ts`.

SignalDayHigh is the long-only “day high breakout” strategy. In this repository, its per-symbol mutable engine state is stored in `SignalDayHighState` inside `src/tw_signal_engine/state/signal_state.py`. The evaluator that updates that state lives in `src/tw_signal_engine/signals/evaluate_signal_day_high.py`. The replay code that converts engine state into dashboard JSON lives in `_build_dashboard_snapshot()` inside `src/tw_signal_engine/replay/replay_session.py`. The FastAPI route that serves the DayHigh snapshot is `GET /api/dashboard/signal-day-high` in `src/tw_signal_engine/server/app.py`.

The frontend currently consumes DayHigh data in two places. `dashboard/src/pages/MarketOverview.tsx` shows an overview summary card and a compact DayHigh table. `dashboard/src/pages/DayHighMonitor.tsx` shows the dedicated DayHigh route using the shared `SignalMonitorLayout`. The compact DayHigh table itself lives in `dashboard/src/components/overview/SignalTables.tsx`, and the overview summary metrics live in `dashboard/src/components/overview/SignalSummary.tsx`. Snapshot normalization for live and replay payloads lives in `dashboard/src/hooks/useDashboardData.ts`.

The engine’s DayHigh state machine has four user-meaningful phases that matter for the dashboard:

1. Anchored high. The engine has seen a valid intraday high and is tracking it as the current breakout anchor.
2. Pullback confirmed. Price has retraced enough from the anchor high to satisfy the pullback rule.
3. Breakout triggered. Price has moved back above the anchored high and passed the extra trigger filters.
4. Holding or exited. A trade entered on the breakout is either still open or already closed.

The dashboard does not currently expose those phases cleanly. A symbol in phase 1 contributes to the summary `tracking` count but usually has no visible row in the DayHigh table. A symbol that triggered in phase 3 is shown after the evaluator has already reset its state, so the visible row may reflect a new anchor rather than the anchor and pullback that caused the signal.

## Plan of Work

Implement the work in three milestones.

### Milestone 1: Make the backend snapshot describe the real DayHigh state progression

Start in `src/tw_signal_engine/server/dashboard_snapshot.py`. Replace the current loosely defined DayHigh row contract with one that is explicit about phase and trigger context. Keep the existing fields that the frontend already uses, but add the missing fields needed to explain the engine state. At minimum the final DayHigh row shape should expose a stable phase field such as `phase: "tracking" | "pullback" | "triggered" | "holding" | "exited"` and enough numeric and time fields to show both the current anchor and the last breakout context.

The cleanest implementation is to extend `SignalDayHighState` in `src/tw_signal_engine/state/signal_state.py` with dedicated snapshot-friendly fields that survive a breakout reset. Add fields such as `last_trigger_high`, `last_trigger_high_time`, `last_trigger_pullback_low`, `last_trigger_pullback_time`, and `last_trigger_time`. Populate them inside `evaluate_signal_day_high()` immediately before `_reset_for_new_high()` overwrites the old state. Do not try to infer these values later from `open_trades`; they belong to signal state, not execution state.

Then update `_build_dashboard_snapshot()` in `src/tw_signal_engine/replay/replay_session.py`. Remove the guard that hides pre-pullback tracking rows from `day_high_rows`. The rows collection must include every symbol whose DayHigh state is active enough to be user-visible, including a pure anchored-high tracking state. At the same time, keep the existing `preparing`, `entered`, and `exited` lifecycle arrays for the dedicated page because those remain useful for trade monitoring.

When building the snapshot, compute DayHigh phase counts from the same row list that the UI renders. The dashboard must never show a summary count for a population that has no corresponding rows. Replace the overloaded `tracking` meaning with two explicit ideas:

- `tracking`: the count of rows currently in the pure anchored-high phase, before pullback confirmation.
- `pullback`: the count of rows currently waiting for a breakout after pullback confirmation.
- `triggered`: the count of rows that triggered but are not open positions anymore only if such a transient phase still exists in the row model.
- `holding`: the count of open DayHigh positions.

If the existing top-level summary contract becomes too ambiguous, add a `phase_counts` object to `SignalDayHighMonitorSnapshot` and keep the old scalar fields only as backward-compatible aliases during the migration. The preferred end state is for the React code to read from `phase_counts`, not to reinterpret a mix of legacy scalar names.

Add backend tests that prove the new semantics. Extend `tests/unit/test_signal_day_high.py` to cover trigger-context persistence across the breakout reset. Add replay snapshot tests, either in `tests/unit/test_day_high_replay.py` or in a new focused snapshot test file, that assert a pure tracking symbol appears in `signal_day_high.rows`, that pullback rows preserve their low and times, and that a triggered or holding row carries the last pre-breakout anchor context.

### Milestone 2: Redesign the DayHigh dashboard display around explicit phases

Update `dashboard/src/types/dashboard.ts` so the TypeScript contract mirrors the backend additions exactly. Then update `dashboard/src/hooks/useDashboardData.ts` to normalize older replay payloads safely. Older payloads may lack new DayHigh fields, so the normalizer must synthesize empty strings, zeroes, or empty phase counts instead of crashing.

Redesign `dashboard/src/components/overview/SignalTables.tsx` for DayHigh. The compact overview table should stop acting like a generic trade table and start acting like a state-machine summary. Keep the row count manageable, but add the columns needed to explain progression. The recommended columns are symbol, group, phase, anchor high, anchor time, pullback low, pullback time, breakout time or last trigger time, entries, and status badge. Use the new phase field for the primary label instead of inferring everything from `status`.

Update `dashboard/src/components/overview/SignalSummary.tsx` to use the same phase counts that back the table rows. The summary card should report counts such as tracking, pullback, breakout-ready or triggered, and holding. Do not count hidden rows. If the backend keeps both legacy scalar counts and a new `phase_counts` object, the summary should prefer the explicit object and fall back only for backward compatibility.

Revise `dashboard/src/pages/DayHighMonitor.tsx` and, if necessary, `dashboard/src/components/signal/SignalMonitorLayout.tsx`. The dedicated DayHigh route should still show preparing, entered, and exited lifecycle cards, but it needs a DayHigh-specific state section ahead of those cards so the route explains the progression before entry. The simplest layout is:

- a DayHigh phase summary bar
- a DayHigh state table showing all tracked symbols
- the existing preparing cards
- the existing active position cards
- the existing exited trade cards

Do not overload the generic Signal A `CounterBar` labels for the primary DayHigh progression display. Those counters can remain for lifecycle monitoring if useful, but the route needs explicit DayHigh language for the strategy-state portion. If the generic `CounterBar` becomes misleading, add a dedicated `DayHighPhaseBar` component under `dashboard/src/components/signal/` and keep the existing `CounterBar` only for shared Signal A style pages.

Review toast logic in `dashboard/src/pages/MarketOverview.tsx`. Today the DayHigh toast fires only for `pullback` and `triggered`. After the phase redesign, keep that behavior unless the new product decision explicitly wants tracking toasts. Tracking is too noisy for default toasts.

### Milestone 3: Validate parity, then update docs

After code changes are in place, update `docs/design-docs/dashboard-architecture.md` so it describes the DayHigh route as a two-layer view: strategy-state progression plus trade lifecycle. Document the meaning of the DayHigh phase fields and the backward-compatibility normalization in `useDashboardData.ts`.

Validation must prove both engine parity and user-visible clarity. Run focused Python tests for the evaluator and replay snapshot behavior, then the full repository validation commands from `AGENTS.md`. Build the dashboard and manually inspect a replay session that contains at least one DayHigh setup. If there is no convenient historical replay date with a setup, create or extend a unit test fixture that renders snapshot JSON for a tracking-only symbol, a pullback symbol, and a holding symbol so the frontend can be exercised deterministically.

## Concrete Steps

Work from the repository root unless a step says otherwise:

    cd /home/r12944005/b07401012/Trading/signal

Implement Milestone 1 by editing these files in order:

    src/tw_signal_engine/state/signal_state.py
    src/tw_signal_engine/signals/evaluate_signal_day_high.py
    src/tw_signal_engine/server/dashboard_snapshot.py
    src/tw_signal_engine/replay/replay_session.py
    tests/unit/test_signal_day_high.py
    tests/unit/test_day_high_replay.py

When editing the evaluator, preserve its current trigger conditions and only add the state needed for dashboard parity. The goal is not to change DayHigh strategy behavior. The goal is to preserve the exact context that existed when the trigger occurred.

Implement Milestone 2 by editing:

    dashboard/src/types/dashboard.ts
    dashboard/src/hooks/useDashboardData.ts
    dashboard/src/components/overview/SignalTables.tsx
    dashboard/src/components/overview/SignalSummary.tsx
    dashboard/src/pages/DayHighMonitor.tsx
    dashboard/src/components/signal/SignalMonitorLayout.tsx
    dashboard/src/components/signal/CounterBar.tsx

Prefer adding a DayHigh-specific summary component rather than making `CounterBar` dynamically reinterpret its labels for one route. A dedicated component is easier to read and less likely to regress Signal A pages.

Implement Milestone 3 by editing:

    docs/design-docs/dashboard-architecture.md
    docs/exec-plans/active/index.md

The final validation sequence should be:

    uv run pytest tests/unit/test_signal_day_high.py tests/unit/test_day_high_replay.py tests/unit/test_server.py -q
    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Then build the dashboard:

    cd /home/r12944005/b07401012/Trading/signal/dashboard
    npm run build

Return to the repository root and run a replay-backed server using the command from `README.md` that matches the local data. Open the dashboard in a browser and verify the DayHigh overview summary and the DayHigh route against the same replay minute.

## Validation and Acceptance

The implementation is complete only when a human can verify the following behavior:

1. A symbol that has only established an anchor high, with no confirmed pullback yet, appears in the DayHigh table with a visible tracking phase. The same symbol contributes to the DayHigh summary counts, and the summary count matches the visible rows.
2. A symbol that has confirmed a pullback shows the anchor high, anchor time, pullback low, and pullback time in the DayHigh table. The UI labels this state as a pullback-ready or breakout-waiting phase instead of a generic triggered state.
3. When a breakout occurs, the dashboard still shows the pre-breakout anchor and pullback context that caused the trigger, even if the evaluator has already reset its mutable anchor state for the next cycle.
4. An open DayHigh position appears in the dedicated DayHigh route as both a state row and an active position card, without contradictory labels.
5. The market overview DayHigh summary and the DayHigh route describe the same set of symbols for the same replay minute.
6. Replay snapshots saved before this change still load in the frontend because `useDashboardData.ts` fills missing DayHigh fields safely.

Backend automated acceptance should include a test that fails before implementation and passes after it. The most important failing-before, passing-after case is a tracking-only symbol that contributes to `tracking` but is absent from `rows`. Frontend acceptance should include a successful `npm run build` and a manual replay smoke test using a snapshot minute where at least one symbol is in each of the tracking, pullback, and holding states if such a minute is available.

## Idempotence and Recovery

All planned changes are additive and can be repeated safely. Extending DayHigh state and snapshot types is safe as long as the new fields have sensible defaults in both Python dataclasses and TypeScript normalization. If a frontend build fails during the migration because new fields are not present in historical replay payloads, fix the normalizer in `dashboard/src/hooks/useDashboardData.ts` rather than removing the new schema fields.

If the implementation must be split across multiple commits, land it in this order:

1. backend state preservation and snapshot contract
2. backend tests
3. frontend normalization and rendering
4. docs and final validation

That order keeps the system testable at each step and avoids a frontend depending on fields the backend does not yet provide.

## Artifacts and Notes

The most important current-code findings that motivated this plan are:

    src/tw_signal_engine/replay/replay_session.py
      day_high_rows only include a symbol when:
        day_high_state.pullback_confirmed
        or day_high_state.triggered
        or day_high_state.entries > 0

      but tracking count is computed as:
        sum(1 for state in signal_day_high_map.values() if state.established_high > 0)

This is the core mismatch. A user can see a non-zero tracking count with no matching DayHigh tracking rows.

The current evaluator also resets state before publishing a trigger:

    src/tw_signal_engine/signals/evaluate_signal_day_high.py
      trigger_high = state.established_high
      _reset_for_new_high(state, price, match_time_str)
      state.triggered = True

Without extra preserved fields, the dashboard reads post-reset state instead of the exact trigger context.

## Interfaces and Dependencies

No new third-party dependency is required. Use the existing Python dataclasses, FastAPI server, React, TypeScript, and Vite stack.

At the end of implementation, these interfaces should exist:

- `SignalDayHighState` in `src/tw_signal_engine/state/signal_state.py` includes durable fields for the last breakout context.
- `SignalDayHighMonitorEntry` in `src/tw_signal_engine/server/dashboard_snapshot.py` includes an explicit DayHigh phase field and the times and price levels needed to explain progression.
- `SignalDayHighMonitorSnapshot` in `src/tw_signal_engine/server/dashboard_snapshot.py` includes phase counts that match the visible rows.
- The matching `SignalDayHighMonitorEntry` and `SignalDayHighMonitorSnapshot` interfaces in `dashboard/src/types/dashboard.ts` mirror the backend contract exactly.
- The DayHigh overview summary and the DayHigh route both consume the same phase-oriented snapshot model.

Revision note: created this plan on 2026-04-27 after investigating the current SignalDayHigh evaluator, replay snapshot builder, and dashboard rendering path. The plan exists because the problem is a semantic parity gap between engine state and UI display, not just a styling issue.
