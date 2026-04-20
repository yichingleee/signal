# Reduce `readFileMerged` Runtime With Three Low-Risk Wins

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document is maintained in accordance with `docs/references/exec-plan-standard.md`. It is self-contained: a contributor should be able to start from this file and implement, validate, and benchmark the three low-risk optimizations without relying on prior chat context.

## Purpose / Big Picture

Daily parquet replay for `20260326` currently spends most of runtime inside `[TIMING] readFileMerged`, and profiling shows this stage is dominated by Python-side screening work in `StrongGroupEvaluator.on_tick()`. After this plan ships, a contributor can run the same replay command and observe materially lower `[TIMING] readFileMerged` and `[TIMING] TOTAL` while preserving strategy behavior and report outputs.

The three low-risk wins are intentionally narrow and behavior-preserving. They do not introduce new dependencies, they do not change data-source truth policy, and they do not change strategy thresholds. They remove avoidable work that is already proven unnecessary by current control flow and current config.

## Progress

- [x] (2026-04-20T00:00:00Z) Wrote this execution plan based on in-repo profiling and replay measurements on `20260326`.
- [x] Implement Win 1: build replay universe from `StrongGroup` true-valid symbols only.
- [x] Implement Win 2: compute group average percentage change at most once per `(group, tick)` in `StrongGroupEvaluator.on_tick()`.
- [x] Implement Win 3: avoid unconditional 20-day volume-query computation when filter knobs that need it are disabled.
- [x] Add and update unit tests covering new helper behavior and strong-group hot-path guard logic.
- [x] Run replay A/B benchmarks and confirm runtime improvement plus output parity.
- [x] Update this plan’s `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` with implementation evidence.

## Surprises & Discoveries

- Observation: `readFileMerged` is dominated by strategy CPU, not sidecar or reporting overhead.
  Evidence: On `20260326` with parquet + fresh caches + sidecar, the run logged `readFileMerged: 33913 ms`, `TOTAL: 57473 ms`, and cProfile showed `StrongGroupEvaluator.on_tick` at `58.441s` cumulative and `_group_percentage_chg` at `20.021s` cumulative.

- Observation: Disabling `StrongGroup` collapses `readFileMerged` runtime by about three quarters.
  Evidence: Same replay date and inputs with only config toggle changes produced `readFileMerged: 7999 ms` (`-76.41%` versus baseline), and disabling `SignalA` in addition changed little (`7893 ms`).

- Observation: replay universe currently includes many symbols already known invalid for strong-group screening.
  Evidence: For `20260326`, `symbol_is_valid` had `1064` keys but only `346` true values. Current replay universe path uses `set(strong_group.symbol_is_valid.keys())`, not true-valid subset.

- Observation: replay row count inflation from invalid-symbol inclusion is measurable.
  Evidence: For `20260326` parquet filters, universe from all keys yielded `1,300,675` rows; universe from true-valid symbols plus `0050` yielded `1,141,712` rows (`-158,963`, `-12.22%`).

- Observation: parquet provider front-end read/sort is not the primary bottleneck.
  Evidence: Instrumented provider-only pass measured about `0.704s` for read+concat+sort versus about `5.795s` for Python-side batch conversion and `MarketTick` construction.

- Observation: Initial Win-3 refactor introduced parity drift despite identical strategy qualification.
  Root-cause evidence: `StrongGroupEvaluator` report metadata (`MatchInfo`) stopped aligning because `should_update` and lazy `vol_ratio` evaluation order changed.

- Observation: After restoring baseline `ans`/`should_update` evaluation order and gating only unnecessary `query` calls, report outputs align exactly again.
  Evidence: `diff` of `report_trades.csv` is empty for both `20260320` and `20260326`.

## Decision Log

- Decision: keep scope to exactly three low-risk wins and avoid data-structure rewrites (symbol-id arrays, native kernels) in this plan.
  Rationale: The user asked for low-risk wins first. Larger refactors have higher blast radius and should be a follow-up plan after confirming gains from these safe changes.
  Date/Author: 2026-04-20 / Codex

- Decision: require strategy-output parity checks as acceptance gates, not runtime gains alone.
  Rationale: All three wins are intended as no-behavior-change optimizations. Runtime-only validation is insufficient for a trading engine.
  Date/Author: 2026-04-20 / Codex

- Decision: apply Win 1 consistently in replay and live/server tick-filter construction.
  Rationale: `run_daily_replay`, `run_live`, and `run_server` currently build universe from the same broad key set pattern. Consistency reduces future divergence and surprise.
  Date/Author: 2026-04-20 / Codex

- Decision: preserve report metadata update semantics when introducing lazy volume lookups.
  Rationale: the `match_info` fields are part of behavioral parity; we kept baseline sequencing and only defer queries when no longer used by either filters or reporting.
  Date/Author: 2026-04-20 / Codex

## Outcomes & Retrospective

Completed with parity preserved.

1. before/after timings (`20260320`):

   - Baseline (`tickFilter: 1065`): `readFileMerged: 57511 ms`, `TOTAL: 82408 ms`, `Total ticks processed: 1545124`
   - Optimized (`tickFilter: 333`): `readFileMerged: 34878 ms`, `TOTAL: 60168 ms`, `Total ticks processed: 1287609`
   - Improvement: `readFileMerged` -39.5%, `TOTAL` -27.0%.

2. before/after timings (`20260326`):

   - Baseline (`tickFilter: 1065`): `readFileMerged: 51589 ms`, `TOTAL: 76462 ms`, `Total ticks processed: 1300675`
   - Optimized (`tickFilter: 347`): `readFileMerged: 31035 ms`, `TOTAL: 56629 ms`, `Total ticks processed: 1141712`
   - Improvement: `readFileMerged` -39.9%, `TOTAL` -25.9%.

3. output parity:

   - `20260320`: no diff on `report_trades.csv` between `log/parity-before-20260320/20260320/report_trades.csv` and `log/parity-after-20260320/20260320/report_trades.csv`.
   - `20260326`: no diff on `report_trades.csv` between `log/parity-before-20260326/20260326/report_trades.csv` and `log/parity-after-20260326/20260326/report_trades.csv`.

4. validation:

   - `uv run pytest tests -q`
   - `uv run ruff check src tests`
   - `uv run mypy src`

5. residual bottleneck:
   - Remaining runtime is dominated by tick intake + per-tick strategy/dashboard-state updates. The low-risk wins captured here did not touch I/O shape or reporting pipeline logic. Next optimization should target `MarketTick` materialization and ranking/snapshot update paths.

## Context and Orientation

The daily replay orchestration is in `src/tw_signal_engine/replay/replay_session.py`. The line `[TIMING] readFileMerged` covers the provider iteration loop and per-tick strategy processing. In parquet mode, ticks come from `src/tw_signal_engine/market_data/parquet_replay_provider.py` and are consumed by screening, signal, entry, and exit logic inside that loop.

The dominant strategy hot path is `src/tw_signal_engine/screening/evaluate_strong_group.py`, specifically `StrongGroupEvaluator.on_tick()`. This function currently performs repeated group average calculations and repeated historical volume queries on every candidate path, even when related feature flags are disabled.

Replay-universe construction lives in `src/tw_signal_engine/replay/build_replay_universe.py` and is called from `run_daily_replay`, `run_live`, and `run_server`. Today these callers pass all keys from `strong_group.symbol_is_valid` rather than true-only symbols.

Key test modules for this work are:

- `tests/unit/test_replay_universe.py`
- `tests/unit/test_replay_session.py`
- `tests/unit/test_parquet_replay_provider.py`
- `tests/unit/test_market_gate.py`

Add a dedicated strong-group optimization test module if existing tests do not directly cover new helper/control-flow behavior.

## Plan of Work

### Milestone 1: True-valid replay universe symbols only (Win 1)

At the end of this milestone, replay and live/server subscription filters should include only symbols that passed strong-group validity precomputation, plus existing required symbols such as `0050` and strong-single valid symbols. This removes known-dead symbols before provider filtering and before per-tick screening execution.

Edit `src/tw_signal_engine/replay/replay_session.py`, `src/tw_signal_engine/cli/run_live.py`, and `src/tw_signal_engine/cli/run_server.py` so each caller derives a `set[str]` of true-valid strong-group symbols via a shared helper. Add that helper in `src/tw_signal_engine/replay/build_replay_universe.py` with a stable name such as `extract_valid_group_symbols(symbol_is_valid: Mapping[str, bool]) -> set[str]`. Keep `build_replay_universe()` behavior unchanged once given input sets.

Update tests in `tests/unit/test_replay_universe.py` to verify that false-valued entries are excluded by the helper. Add one replay-session unit test (or update an existing one) to assert that constructed tick filter uses true-valid symbols and still includes `0050`.

### Milestone 2: Remove duplicate group-average recomputation (Win 2)

At the end of this milestone, `StrongGroupEvaluator.on_tick()` should compute a group average percentage change once for validation/ranking flow per `(group, tick)`, rather than computing in `_is_valid_group()` and then computing again immediately after passing validation.

Refactor `src/tw_signal_engine/screening/evaluate_strong_group.py` so validation logic can accept a precomputed average percentage. One safe pattern is to replace `_is_valid_group(symbol, group)` with `_eval_group_validity(symbol, group, avg_pct)` or return `(is_valid, avg_pct)` from the validation helper. Preserve existing threshold logic and floating-point formulas.

Add a targeted unit test module (for example `tests/unit/test_evaluate_strong_group_optimizations.py`) that constructs a minimal evaluator fixture and asserts the refactored helper is used correctly without changing qualification outcomes on deterministic synthetic ticks.

### Milestone 3: Gate expensive 20-day volume queries (Win 3)

At the end of this milestone, `StrongGroupEvaluator.on_tick()` should not execute the unconditional `sum(self.vol_cum[i].query(...))` path when no enabled condition needs it for this tick.

Implement a local guard in `on_tick()` with explicit booleans derived from config, for example `need_vol_ratio_for_filters` and `need_vol_ratio_for_reporting`. Ensure trade decisions remain unchanged. When `member_cond1_enabled` is false and `entry_max_vol_ratio <= 0`, avoid the 20-day query for decision logic. If `vol_ratio` is needed for `MatchInfo` reporting fields, compute it lazily at the point of `MatchInfo` update rather than unconditionally before ranking/entry decisions.

Add tests that pin this control flow. A practical approach is monkeypatching/stubbing `LinearVolumeTracker.query` to count invocations and asserting zero invocations in configurations where no condition depends on volume ratio, while confirming decisions still match prior expected outcomes on the same synthetic stream.

## Concrete Steps

Run all commands from repository root:

    cd /home/r12944005/b07401012/Trading/signal

Create a baseline timing log for `20260326` before edits:

    /usr/bin/time -v uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder timing-baseline-20260326 \
      --no-charts 2>&1 | tee /tmp/replay_baseline_20260326.log

Implement Milestone 1 changes in:

    src/tw_signal_engine/replay/build_replay_universe.py
    src/tw_signal_engine/replay/replay_session.py
    src/tw_signal_engine/cli/run_live.py
    src/tw_signal_engine/cli/run_server.py
    tests/unit/test_replay_universe.py
    tests/unit/test_replay_session.py

Implement Milestone 2 and Milestone 3 changes in:

    src/tw_signal_engine/screening/evaluate_strong_group.py
    tests/unit/test_evaluate_strong_group_optimizations.py

Run focused tests after each milestone:

    uv run pytest tests/unit/test_replay_universe.py tests/unit/test_replay_session.py -q
    uv run pytest tests/unit/test_evaluate_strong_group_optimizations.py tests/unit/test_market_gate.py -q

Run broader replay/parquet regressions:

    uv run pytest tests/unit/test_parquet_replay_provider.py tests/unit/test_parquet_history_loader.py tests/unit/test_entry_filters.py -q

Run repo quality gates:

    uv run ruff check src tests
    uv run mypy src

Run post-change timing capture:

    /usr/bin/time -v uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder timing-optimized-20260326 \
      --no-charts 2>&1 | tee /tmp/replay_optimized_20260326.log

Run output parity checks on at least two dates:

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260320 --data-source parquet --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg --log-folder parity-before-20260320 --no-charts

    uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260320 --data-source parquet --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg --log-folder parity-after-20260320 --no-charts

    diff -u log/parity-before-20260320/20260320/report_trades.csv log/parity-after-20260320/20260320/report_trades.csv

Repeat parity check for `20260326`.

## Validation and Acceptance

Acceptance is behavioral and performance-based.

Behavioral acceptance requires:

1. unit tests added for all three wins and passing;
2. existing targeted replay/parquet tests passing;
3. identical `report_trades.csv` between before and after builds for validation dates (`20260320`, `20260326`) under the same config and data roots.

Performance acceptance requires:

1. `[TIMING] readFileMerged` on `20260326` is lower after the change than baseline, measured on the same machine and command shape;
2. `[TIMING] TOTAL` is lower after the change;
3. the improvement is not driven by disabling strategy features.

Use the timing logs in `/tmp/replay_baseline_20260326.log` and `/tmp/replay_optimized_20260326.log` to extract and compare stage timings.

## Idempotence and Recovery

These edits are source-only and idempotent. Re-running test and timing commands is safe. If a milestone fails validation, revert only the milestone’s local edits and keep prior validated milestones.

If parity diff appears after Milestone 2 or 3, first bisect by temporarily toggling only one win at a time. Keep Win 1 if it passes parity independently, then isolate the offending control-flow refactor in `evaluate_strong_group.py`.

## Artifacts and Notes

Record implementation evidence here as indented snippets while executing this plan. Keep the snippets short and focused.

Expected timing-line shape:

    [TIMING] getTickData OTC: ... ms
    [TIMING] getTickData TSE: ... ms
    [TIMING] getGroup: ... ms
    [TIMING] readFileMerged: ... ms
    [TIMING] TOTAL: ... ms

Expected parity check result after successful implementation:

    $ diff -u .../report_trades.csv .../report_trades.csv
    (no output)

## Interfaces and Dependencies

Use only existing project dependencies in `pyproject.toml` (`pyarrow`, `numpy`, etc.). Do not add new libraries for this plan.

At the end of implementation, these interfaces should exist and be used:

- `extract_valid_group_symbols(symbol_is_valid: Mapping[str, bool]) -> set[str]` in `src/tw_signal_engine/replay/build_replay_universe.py` (exact name can differ if documented consistently, but keep a stable helper for all callers).
- `build_replay_universe(...)` remains the composition point for group/single/proxy symbol union.
- `StrongGroupEvaluator` keeps current public behavior; refactors inside `on_tick()` must preserve outputs.

The replay CLI command contract and existing config schema must remain unchanged.

Revision note, 2026-04-20: Initial plan drafted to implement three low-risk runtime wins identified by on-repo timing/profiling research for `readFileMerged`.
