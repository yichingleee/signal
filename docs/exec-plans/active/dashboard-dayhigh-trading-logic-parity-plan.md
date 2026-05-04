# Make the Dashboard Replicate Full DayHigh Trading Logic

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

If `docs/exec-plans/PLANS.md` is ever added to this repository, this plan must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a trader using the dashboard can follow the DayHigh strategy end to end without reading Python code or cross-referencing CSV reports. The `DayHigh 監測` route will explain four distinct things for each relevant symbol:

1. why the symbol is or is not currently selected by the strong-group stock-selection rules;
2. where the symbol is inside the DayHigh pattern monitor, from anchored high through pullback and breakout;
3. why a triggered entry was allowed or blocked by the entry filter stack; and
4. how an open or closed DayHigh position will exit, or did exit, including stop basis, time exit, limit-up overnight carry, and final leave cause.

The visible outcome is not that React re-implements the strategy. The visible outcome is that the dashboard mirrors the Python engine's own decisions with enough structured data to explain them. A user should be able to open one page and answer: "Was this stock selected?", "Did the DayHigh setup arm?", "Why did entry happen or fail?", and "What exit policy applies now or what exit cause already happened?"

## Progress

- [x] (2026-04-27 00:00Z) Investigated the current dashboard, DayHigh product spec, replay snapshot builder, and UI rendering to identify where trading logic is and is not exposed.
- [x] (2026-04-27 00:00Z) Confirmed the current parity gap: the dashboard renders fragments of DayHigh state, but it does not replicate full stock-selection, entry-filter, or exit-policy logic.
- [x] (2026-04-27 00:00Z) Authored this ExecPlan under `docs/exec-plans/active/`.
- [x] (2026-04-27 11:12Z) Implemented backend DayHigh explainability snapshots for stock selection, entry gating, and exit policy.
- [x] (2026-04-27 11:12Z) Persisted the richer DayHigh snapshot shape through replay snapshot writing and backward-compatible replay loading.
- [x] (2026-04-27 11:12Z) Redesigned the DayHigh route and overview summary so the dashboard shows end-to-end DayHigh logic, not only partial lifecycle state.
- [x] (2026-04-27 11:12Z) Added focused Python tests and passed backend/frontend validation commands for the new DayHigh logic display.

## Surprises & Discoveries

- Observation: the current dashboard is explicitly a monitoring UI for engine state, not a second strategy implementation.
  Evidence: `docs/design-docs/dashboard-architecture.md` says the dashboard "surfaces ... state that is already produced by the Python engine."

- Observation: strong-group cards expose useful market context but not the full DayHigh selection logic.
  Evidence: `dashboard/src/components/groups/GroupCard.tsx` renders group averages, VWAP, and volume ratios, but not raw member rank, M1 status, VWAP-band pass/fail, disposition blocking, or selection-rejection reasons.

- Observation: the DayHigh route shows pattern phases and lifecycle cards, but it still omits key entry and exit logic details.
  Evidence: `src/tw_signal_engine/replay/replay_session.py` populates DayHigh `rows`, `preparing`, `entered`, and `exited`, but the UI components do not show block reasons, stop basis, time-exit deadline, overnight-eligibility state, or exit cause text.

- Observation: current DayHigh lifecycle cards display placeholder stop-loss and take-profit values rather than the real DayHigh exit policy.
  Evidence: `_build_dashboard_snapshot()` currently emits `stop_loss=0.0` and `take_profit=0.0` for DayHigh preparing and entered rows in `src/tw_signal_engine/replay/replay_session.py`, and the cards render those values directly.

- Observation: entry-filter block reasons already exist in engine logic, but the dashboard does not surface them per symbol.
  Evidence: `src/tw_signal_engine/execution/create_entry_trade.py` returns concrete reasons such as `entry_time_limit`, `prev_day_limit_up`, `volatility_pause`, `already_holding`, and `max_entry_price`, while `src/tw_signal_engine/reporting/funnel_tracker.py` already records aggregate block counts and reasons.

- Observation: DayHigh has one extra block path outside `should_enter()`, so a dashboard that only shows generic entry filters would still be incomplete.
  Evidence: replay integration blocks DayHigh when the matched group already has at least `max_group_limit_up_count` limit-up symbols, with reason `day_high_group_limit_up_count`.

- Observation: exit causes are preserved in the engine but not fully surfaced in the current DayHigh cards.
  Evidence: `trade_ledger.on_tick_exit()` records `final_leave_cause` values such as `stopLoss`, `timeExit`, `takeProfit`, `bailout`, and `overnightExit`, but `dashboard/src/components/signal/ExitedCards.tsx` does not render `exit_cause` text for the user.

## Decision Log

- Decision: treat "replicate full trading logic" as "mirror the Python engine's decisions in dashboard snapshots," not "duplicate trading calculations in React."
  Rationale: the engine is the source of truth and already contains the authoritative DayHigh, strong-group, entry-filter, and exit-policy rules. Re-implementing those rules in the frontend would create silent divergence risk.
  Date/Author: 2026-04-27 / Codex

- Decision: scope this plan to DayHigh first, even though some of the resulting snapshot plumbing should be reusable by Signal A, SignalAShort, and Signal B later.
  Rationale: the user's question and the current dashboard-parity gap are specifically about the DayHigh strategy. DayHigh already has a dedicated route and is the clearest place to establish an end-to-end "strategy explainability" pattern.
  Date/Author: 2026-04-27 / Codex

- Decision: build structured backend explanation records for selection, entry gating, and exit policy instead of adding ad hoc strings to existing cards.
  Rationale: the missing parity is multidimensional. Users need booleans, numeric thresholds, ranks, prices, timestamps, and explicit reasons. A structured schema is easier to test, persist in replay snapshots, and render in multiple UI components.
  Date/Author: 2026-04-27 / Codex

- Decision: refactor existing rule functions where necessary so the dashboard explanation data comes from the same code paths as trading decisions.
  Rationale: `should_enter()` already returns a block reason, and DayHigh exit policy already exists in execution modules. Any dashboard-facing explainability layer must share those calculations rather than approximate them independently.
  Date/Author: 2026-04-27 / Codex

- Decision: keep old replay snapshots loading through frontend normalization instead of requiring a replay-cache migration.
  Rationale: replay mode depends on historical Parquet snapshots. A schema expansion should be backward compatible by filling missing fields with explicit empty defaults.
  Date/Author: 2026-04-27 / Codex

## Outcomes & Retrospective

This plan is implemented. The dashboard now carries a DayHigh `logic` payload from the engine, including selection pass/fail reasons, entry-filter outcomes, and open/closed exit-policy explanations. The DayHigh route renders these sections in sequence, while the overview exposes compact `selected / armed / blocked / holding` counters and links operators to `/day-high`.

The main lesson from implementation is unchanged: the critical gap was a data contract gap, not a rendering gap. Once the snapshot contract mirrored engine decisions, the UI could explain behavior without re-implementing strategy logic in React.

## Context and Orientation

The active trading engine is the Python replay/live engine under `src/tw_signal_engine/`. The dashboard is the React application under `dashboard/`, served by FastAPI. A "dashboard snapshot" is the complete per-minute UI payload. The backend schema lives in `src/tw_signal_engine/server/dashboard_snapshot.py`; the matching frontend schema lives in `dashboard/src/types/dashboard.ts`; live/replay loading and normalization live in `dashboard/src/hooks/useDashboardData.ts`; replay snapshot persistence lives in `src/tw_signal_engine/reporting/snapshot_writer.py`.

For DayHigh specifically, the trading logic is distributed across four subsystems:

1. Stock selection. `src/tw_signal_engine/screening/evaluate_strong_group.py` ranks groups and members. DayHigh requires a top `G1-G10` group, member rank `M1`, raw rank `R1`, disposition handling, and a configurable VWAP percent-change band.
2. Signal monitoring. `src/tw_signal_engine/signals/evaluate_signal_day_high.py` tracks the anchored intraday high, pullback confirmation, and breakout trigger state. `src/tw_signal_engine/state/signal_state.py` stores the mutable DayHigh state.
3. Entry gating and execution. `src/tw_signal_engine/execution/create_entry_trade.py` applies generic entry filters through `should_enter()` and creates the trade through `execute_entry()`. `src/tw_signal_engine/replay/replay_session.py` also applies the DayHigh-specific group limit-up block before calling `should_enter()`.
4. Exit logic. `src/tw_signal_engine/execution/trade_ledger.py` calls stop-loss, time-exit, take-profit, and bailout helpers. For DayHigh, `src/tw_signal_engine/execution/signal_policy.py` disables take-profit and bailout, `src/tw_signal_engine/execution/apply_stop_loss_exit.py` uses the DayHigh VWAP stop family, and overnight carry behavior is orchestrated in `src/tw_signal_engine/replay/replay_session.py`.

The current dashboard already exposes some of this logic:

- the market overview shows strong groups and a compact DayHigh table;
- the DayHigh route shows phase rows plus preparing, entered, and exited cards;
- completed trades already carry `exit_cause` in the backend snapshot.

But the current UI still cannot answer several operator questions without reading code or CSVs:

- Why is this symbol selected or not selected as the DayHigh stock today?
- Which selection rule failed: group rank, member rank, raw rank, VWAP band, disposition block, or group limit-up crowding?
- Which generic entry filter blocked the trade: time window, prev-day limit-up, volatility pause, already holding, `0050` gate, or max entry price?
- What is the actual stop-loss number for this open DayHigh trade?
- Will this symbol be forced out at `13:20`, or is it eligible to carry overnight if limit-up locked?
- Did the position exit because of stop loss, time exit, or overnight first-trade exit?

This plan closes those gaps without moving strategy logic into the browser.

## Plan of Work

The work should land in five milestones.

### Milestone 1: Define a DayHigh explainability snapshot contract

Start by extending `src/tw_signal_engine/server/dashboard_snapshot.py` and `dashboard/src/types/dashboard.ts` with a schema that can represent DayHigh trading logic from selection to exit. Avoid overloading existing generic Signal A card types for everything. Keep the existing lifecycle arrays because they remain useful, but add DayHigh-specific explanation records.

Introduce a new nested object on `SignalDayHighMonitorSnapshot`, tentatively named `logic`, with the following substructures:

- `selection_rows`: per-symbol strong-group selection explanations for the DayHigh-relevant symbol set;
- `entry_rows`: per-symbol DayHigh entry gate explanations for symbols that reached a meaningful DayHigh trigger or pre-trigger state;
- `exit_rows`: richer views of open and recently closed DayHigh positions, including stop basis and leave cause text;
- `funnel`: aggregate counters and block reasons for DayHigh-related flow visible on the current snapshot.

The exact dataclass names are up to the implementer, but the final schema must let the UI render these user-facing facts directly:

- group name, group rank, member rank, raw member rank, M1 symbol;
- current price, VWAP, VWAP percent change, month trading value, volume ratio;
- whether each DayHigh selection predicate passed or failed;
- DayHigh phase, trigger time, and anchor/pullback context;
- whether each entry gate passed or failed, plus the final block reason string when blocked;
- actual DayHigh stop anchor and stop price;
- time-exit deadline, overnight-hold eligibility, current limit-up-lock state, and final leave cause.

Keep the additions backward compatible. Existing overview and lifecycle screens should continue to render while the richer route is being built.

### Milestone 2: Refactor engine rule paths to emit explainable, shared decisions

The dashboard must not infer rule outcomes from loosely related state. Refactor the engine where necessary so rule evaluation produces structured explanation data as a byproduct of the same code path used for trading.

For generic entry filters, refactor `src/tw_signal_engine/execution/create_entry_trade.py`. Add a structured helper such as `evaluate_entry_filters(...) -> EntryFilterEvaluation`, where the returned object includes individual booleans for each filter and the final `block_reason`. Keep `should_enter()` as a thin wrapper or update its callers to use the structured object directly. The goal is that the dashboard can render the same filter outcomes the engine used, not a second approximation.

For DayHigh-specific gating, capture the group-limit-up block in a structured DayHigh entry-decision record in `src/tw_signal_engine/replay/replay_session.py`. This record must coexist cleanly with `should_enter()` output so the user can see both the DayHigh-specific gate and the generic entry filters.

For strong-group selection, extend `src/tw_signal_engine/screening/evaluate_strong_group.py` so the replay loop can obtain a current per-symbol explanation for the DayHigh-relevant symbol set. The explanation does not need to cover every stock in the market. It must cover the symbols already material to DayHigh monitoring: symbols currently in `signal_day_high_map`, currently selected strong-group members, currently open DayHigh positions, and recently exited DayHigh positions. The explanation should surface both the ranks and the reasons a symbol is not currently selected.

For exit policy, add a small shared description helper in the execution layer, not in the UI. A suitable home is `src/tw_signal_engine/execution/signal_policy.py` or a new execution helper module. The helper should describe the applicable DayHigh stop anchor, computed stop price, time-exit deadline, whether take-profit and bailout are disabled, and whether overnight carry can apply. This will replace the current `0.0` placeholders in DayHigh cards.

### Milestone 3: Build richer DayHigh snapshot assembly and replay persistence

Update `_build_dashboard_snapshot()` inside `src/tw_signal_engine/replay/replay_session.py` to populate the new DayHigh explainability structures. The builder already has access to the latest price map, index state, open trades, completed trades, strong-group context, and DayHigh signal state. Use those to assemble one coherent DayHigh snapshot instead of scattering logic between multiple UI components.

The builder should produce at least four DayHigh views:

1. Selection view. A list that explains which symbol is currently the group-selected DayHigh candidate and why nearby symbols are not selected.
2. Monitoring view. The existing phase rows, preserving anchor and pullback context.
3. Entry-decision view. A list or detail set showing which triggered or nearly triggered symbols passed or failed each entry gate and why.
4. Exit-policy view. Open-position rows with explicit DayHigh stop and time-exit values, plus recent closed trades with visible leave-cause and overnight details.

Update `src/tw_signal_engine/reporting/snapshot_writer.py` only as needed. Because it already persists raw `dashboard_signal_day_high` JSON, the main requirement is to ensure the richer snapshot is written through intact. Do not add a replay-cache migration. Instead, ensure the frontend normalizer can load older snapshots that lack the new fields.

If the replay snapshot row shape is widened elsewhere, update `src/tw_signal_engine/server/app.py` and `src/tw_signal_engine/server/live_state.py` only to preserve endpoint passthrough behavior. The live endpoint should return the richer structure automatically once the backend snapshot dataclasses include it.

### Milestone 4: Redesign the DayHigh route and overview summary around engine explanations

Redesign `dashboard/src/pages/DayHighMonitor.tsx` so it becomes an end-to-end DayHigh logic page instead of a mixed phase/lifecycle page. Keep the existing lifecycle cards, but add two new operator-facing sections above them:

- a stock-selection section that explains strong-group qualification and current DayHigh candidate ranking;
- an entry-decision section that explains whether a symbol is armed, triggered, blocked, or entered, and why.

The recommended route order is:

1. DayHigh phase summary bar;
2. strong-group stock-selection table or cards;
3. DayHigh phase table;
4. entry-gate checklist or decision table;
5. open-position cards with real stop/time/overnight policy;
6. exited-trade cards with explicit leave-cause text.

Add dedicated frontend components under `dashboard/src/components/signal/` or `dashboard/src/components/overview/` rather than overloading the generic Signal A cards with too many conditional branches. A small set of focused DayHigh components will be easier to maintain:

- `DayHighSelectionTable.tsx`
- `DayHighEntryDecisionTable.tsx`
- `DayHighExitPolicyCards.tsx` or an enriched `ActiveCards` variant for DayHigh only

Update `dashboard/src/components/overview/SignalSummary.tsx` and, if necessary, `dashboard/src/pages/MarketOverview.tsx` so the overview page reports a concise DayHigh logic summary. Keep it compact. The overview should answer "how many selected / armed / blocked / holding" and link the operator to `/day-high` for the full explanation surface.

Update `dashboard/src/components/signal/ExitedCards.tsx` or add a DayHigh-specific exited-trade renderer so users can see `exit_cause` text directly instead of inferring it from PnL color.

### Milestone 5: Document, test, and prove live/replay parity

Update `docs/design-docs/dashboard-architecture.md` to describe the new DayHigh explainability sections and the rule that the dashboard mirrors engine decisions through snapshot contracts. Document the meaning of the new DayHigh fields in plain language.

Add focused tests in Python first. The critical acceptance tests are backend tests because the snapshot contract is the source of truth. Add or extend tests in:

- `tests/unit/test_day_high_replay.py`
- `tests/unit/test_signal_day_high.py`
- a new focused file such as `tests/unit/test_day_high_dashboard_snapshot.py`

The tests must cover at least:

- selection-state exposure for a symbol that is tracked but not currently selected;
- entry-filter explanation for a blocked symbol, including a concrete `block_reason`;
- real DayHigh stop/time/overnight policy values for an open position;
- closed-trade exit-cause exposure, including `overnightExit`;
- replay compatibility when the frontend receives an older snapshot without the new fields.

Then validate the frontend with `npm run build` and a replay smoke test using a DayHigh-active historical date. The replay test must verify that the same minute shows consistent data across the overview summary, the DayHigh route, and the raw `/api/dashboard/signal-day-high` JSON.

## Concrete Steps

Work from the repository root:

    cd /Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal

Read the current DayHigh product spec and confirm the target behavior before editing backend contracts:

    rtk sed -n '1,220p' docs/product-specs/dayhigh-breakout-strategy-spec.md
    rtk sed -n '1,220p' exec/cfg/parameter_dayhigh.cfg

Implement Milestone 1 by editing these files first:

    src/tw_signal_engine/server/dashboard_snapshot.py
    dashboard/src/types/dashboard.ts
    dashboard/src/hooks/useDashboardData.ts

Add the new DayHigh explainability structures with safe defaults on both backend and frontend. In `useDashboardData.ts`, normalize missing fields from old replay snapshots to empty arrays, empty objects, zeroes, or empty strings as appropriate.

Implement Milestone 2 by refactoring the shared engine rule paths:

    src/tw_signal_engine/execution/create_entry_trade.py
    src/tw_signal_engine/screening/evaluate_strong_group.py
    src/tw_signal_engine/replay/replay_session.py
    src/tw_signal_engine/execution/signal_policy.py
    src/tw_signal_engine/execution/apply_stop_loss_exit.py
    src/tw_signal_engine/execution/trade_ledger.py

The key design requirement is that dashboard explanation data must come from the same decision code as the engine. Do not add a second copy of entry-filter or exit-policy logic in the replay snapshot builder or in React.

Implement Milestone 3 by enriching snapshot assembly and passthrough:

    src/tw_signal_engine/replay/replay_session.py
    src/tw_signal_engine/reporting/snapshot_writer.py
    src/tw_signal_engine/server/app.py
    src/tw_signal_engine/server/live_state.py

Confirm that the richer `signal_day_high` object survives both live mode and replay snapshot serialization.

Implement Milestone 4 by editing or adding the DayHigh UI components:

    dashboard/src/pages/DayHighMonitor.tsx
    dashboard/src/components/overview/SignalSummary.tsx
    dashboard/src/pages/MarketOverview.tsx
    dashboard/src/components/overview/SignalTables.tsx
    dashboard/src/components/signal/ExitedCards.tsx
    dashboard/src/components/signal/ActiveCards.tsx
    dashboard/src/components/signal/PreparingCards.tsx
    dashboard/src/components/signal/DayHighPhaseBar.tsx

Prefer creating DayHigh-specific components when a shared component would otherwise gain confusing conditional logic. This route should explain DayHigh, not flatten it into the Signal A visual model.

Implement Milestone 5 by editing docs and tests:

    docs/design-docs/dashboard-architecture.md
    tests/unit/test_signal_day_high.py
    tests/unit/test_day_high_replay.py
    tests/unit/test_day_high_overnight.py
    tests/unit/test_load_report_artifacts.py
    tests/unit/test_day_high_dashboard_snapshot.py

The exact new test filename may vary, but there must be at least one focused backend test file dedicated to the richer DayHigh dashboard snapshot contract.

Run targeted backend tests first:

    uv run pytest tests/unit/test_signal_day_high.py tests/unit/test_day_high_replay.py tests/unit/test_day_high_overnight.py -q

Expected result: the targeted DayHigh tests pass and prove snapshot values for selection, block reasons, and exit-policy explanations.

Run the broader backend validation:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Expected result: all commands exit with status 0.

Build the frontend:

    cd /Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal/dashboard
    npm run build

Expected result: Vite writes `dashboard/dist/` successfully with no TypeScript errors.

Return to the repo root and run a replay-backed server using the repository's documented flow, making sure replay snapshots were generated with `--snapshots`:

    cd /Users/liyijing/Projects/Trading/VWAP-intraday-signal/signal
    rtk uv run python -m tw_signal_engine.cli.run_server --mode replay --date <YYYYMMDD> --snapshot-dir ./cache/replay/

Open `/day-high` in the browser and compare it against the API payload:

    curl -s http://localhost:8000/api/dashboard/signal-day-high | python -m json.tool

Expected result: the UI and JSON agree on selected symbols, phase state, blocked reasons, open-position exit policy, and recent exit causes.

## Validation and Acceptance

The implementation is complete only when a human operator can verify the following behaviors from the dashboard itself.

1. Stock selection is explicit. A DayHigh-relevant symbol shows its group rank, member rank, raw member rank, and whether it passed or failed the DayHigh strong-group selection rules. If it is not selected, the UI shows which selection rule failed.

2. Signal monitoring is explicit. A DayHigh-tracked symbol still shows the current anchored high, pullback state, pullback time, and trigger context, matching the engine's phase progression.

3. Entry gating is explicit. When a symbol reaches a meaningful trigger or pre-trigger state, the UI shows which entry gates passed and which failed, including the final block reason string if no trade was entered. DayHigh-specific blocks such as `day_high_group_limit_up_count` are distinguishable from generic `should_enter()` filter reasons.

4. Exit policy is explicit for open positions. An open DayHigh position shows the actual DayHigh stop basis, computed stop price, `13:20` time-exit rule, and whether overnight carry can still happen if the stock is limit-up locked.

5. Exit outcomes are explicit for closed positions. Recent DayHigh exits show `exit_cause` text such as `stopLoss`, `timeExit`, or `overnightExit`, and the overnight case remains visible rather than being inferred indirectly.

6. Live and replay parity holds. The same DayHigh snapshot shape works through the live API, replay API, and replay snapshot files without frontend crashes. Older replay snapshots still load because missing fields are normalized safely.

7. The dashboard still does not invent data. Any module or field the engine cannot currently produce remains absent or explicitly empty rather than guessed in the UI.

The highest-value regression test is a replay scenario where:

- the symbol is strong-group adjacent but not selected at one minute;
- the symbol progresses into pullback and breakout state later;
- the breakout is blocked by an entry filter or by `day_high_group_limit_up_count`;
- an accepted trade later opens and then exits through either `stopLoss` or `overnightExit`.

The final DayHigh route must explain all of those transitions from one replay day without consulting external reports.

## Idempotence and Recovery

All schema and UI changes in this plan should be additive and safe to repeat. Re-running tests, rebuilding the dashboard, and regenerating replay snapshots are all safe.

For risky steps, use these recovery rules:

- If a new DayHigh field breaks older replay snapshots, do not delete the field. Fix `dashboard/src/hooks/useDashboardData.ts` normalization so older snapshots synthesize safe defaults.
- If a UI component becomes too conditional, split it into a DayHigh-specific component instead of weakening shared Signal A behavior.
- If a backend explanation record cannot yet be populated truthfully for a field, leave that field explicitly empty and document the gap rather than deriving it heuristically in React.
- If refactoring `should_enter()` or exit-policy helpers causes semantic drift in strategy behavior, stop and add focused tests first. The explainability refactor must preserve trading outcomes.

The safest landing order is:

1. backend schema and normalization defaults;
2. structured entry-filter evaluation;
3. strong-group explanation capture;
4. exit-policy description helpers;
5. snapshot-builder population;
6. frontend route redesign;
7. docs and final validation.

That order keeps the backend testable while the UI is still unchanged.

## Artifacts and Notes

The investigation that motivated this plan established these concrete gaps in the current code:

    dashboard/src/components/groups/GroupCard.tsx
      shows:
        group_name
        avg_pct_chg
        vol_ratio
        avg_vol_surge
        member price / chg / VWAP / vol ratio / shrink
      does not show:
        group_rank
        raw_member_rank
        M1 / R1 pass-fail
        VWAP-band pass-fail
        disposition blocking
        selection rejection reason

    src/tw_signal_engine/execution/create_entry_trade.py
      already returns block reasons such as:
        entry_time_limit
        prev_day_limit_up
        no_entry_friday
        max_0050_entry_chg
        max_0050_intra_chg
        volatility_pause
        already_holding
        single_forbidden
        max_entry_price
      but the dashboard does not expose them per symbol

    src/tw_signal_engine/replay/replay_session.py
      currently sets DayHigh preparing/entered stop_loss to 0.0
      and DayHigh entered take_profit to 0.0
      so the cards cannot explain the real DayHigh exit policy

    src/tw_signal_engine/execution/trade_ledger.py
      records final_leave_cause on TradeRecord
      including overnightExit
      but the current exited-trade cards do not show that text to the operator

The existing active plans most closely related to this work are:

- `docs/exec-plans/active/dashboard-monitoring-parity-plan.md`
- `docs/exec-plans/active/signal-day-high-dashboard-display-plan.md`

This new plan should be treated as the next-layer explainability plan after those parity plans: the dashboard already surfaces DayHigh state, and now it needs to surface the full trading logic behind that state.

## Interfaces and Dependencies

No new third-party dependency is required. The work should use the existing Python dataclasses, FastAPI server, replay snapshot writer, React, TypeScript, and Vite stack.

At the end of implementation, these interfaces should exist in repository code:

- a richer `SignalDayHighMonitorSnapshot` contract in `src/tw_signal_engine/server/dashboard_snapshot.py` and `dashboard/src/types/dashboard.ts` that includes selection, entry-decision, and exit-policy explanation data;
- a structured entry-filter evaluation type in `src/tw_signal_engine/execution/create_entry_trade.py`, used by both trading logic and dashboard snapshot assembly;
- a shared DayHigh exit-policy description helper in the execution layer;
- replay snapshot writing and loading that preserve the richer `signal_day_high` object without requiring a cache migration;
- frontend normalization that safely handles both new and old replay snapshot shapes;
- a `/day-high` route whose components render the new explanation structures directly.

The main cross-file dependencies to keep aligned are:

- `src/tw_signal_engine/server/dashboard_snapshot.py`
- `dashboard/src/types/dashboard.ts`
- `dashboard/src/hooks/useDashboardData.ts`
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/execution/create_entry_trade.py`
- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/reporting/snapshot_writer.py`

Revision note: created on 2026-04-27 after reviewing the DayHigh product spec, replay-session snapshot builder, execution filters, exit ledger, dashboard architecture, and current DayHigh UI components. The driving conclusion was that the missing feature is full engine-decision explainability in dashboard snapshots, not a frontend-only rendering tweak.
