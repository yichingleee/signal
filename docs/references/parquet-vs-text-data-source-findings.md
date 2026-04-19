# Parquet Integration Status and Data-Source Separation Findings

Date: 2026-04-20

## Purpose

This document records:

1. whether parquet integration is completed in the Python replay engine,
2. key issues and behavior differences between parquet and legacy text (`TSEQuote`/`OTCQuote`) ingestion,
3. how to adopt the new direction: stop forcing strict parquet-vs-text parity, and treat parquet as a separate data source with its own truth contract.

## Scope and Evidence

Primary implementation evidence was collected from:

- `src/tw_signal_engine/cli/run_daily_replay.py`
- `src/tw_signal_engine/cli/run_batch_replay.py`
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/market_data/parquet_io.py`
- `src/tw_signal_engine/market_data/parquet_history_loader.py`
- `src/tw_signal_engine/market_data/parquet_replay_provider.py`
- `src/tw_signal_engine/replay/iterate_market_file.py`
- `src/tw_signal_engine/market_data/parse_history_trades.py`
- `src/tw_signal_engine/market_data/day_bar_loader.py`
- `tests/unit/test_parquet_history_loader.py`
- `tests/unit/test_parquet_replay_provider.py`
- `scripts/compare_text_vs_parquet.py`
- `docs/exec-plans/active/market-data-parquet-migration.md`
- `docs/exec-plans/active/parquet-text-ground-truth-parity-filter.md`
- `docs/references/runtime-conventions.md`
- `docs/design-docs/runtime-architecture.md`
- `README.md`
- `CLAUDE.md`

## Executive Summary

Parquet integration is functionally implemented and active as the replay default, but migration is not fully "closed" under the old parity policy.

- Completed:
  - parquet loaders/providers exist and are wired into daily and batch replay.
  - CLI default is already parquet for replay.
  - guards for missing `Symbols_YYYYMMDD.csv` under parquet mode are implemented.
- Not completed under the old migration definition:
  - strict text-vs-parquet output parity (`report_trades.csv`) is still not consistently achieved on several tracked dates.
  - text path retirement milestones are still pending.

Under the new direction, this is acceptable if we redefine acceptance criteria from strict cross-source identity to source-specific correctness and observability.

## Current Integration Status

### 1. Parquet is first-class in replay CLIs

- `run_daily_replay` exposes `--data-source {text,parquet}` with default `parquet`.
- `run_batch_replay` also defaults to `parquet`, discovers dates from `TWSE/*.parquet` and `TPEX/*.parquet`, and guards dates missing `Symbols_*.csv`.

### 2. Replay session supports both paths

`run_daily_replay()` in replay session branches by `data_source`:

- history:
  - text: `load_history_window`
  - parquet: `load_parquet_history_window`
- tick provider:
  - text: `FileReplayProvider`
  - parquet: `ParquetReplayProvider`

### 3. Parquet path includes feed-specific handling

- Shared parquet filters and conversion:
  - `matchFlag == "Y"` and `time >= 09:00:00.000000` status-equivalence filter.
  - `to_int_price` uses `round(price * 10000)`.
- Replay provider additionally enforces `tradeVolume > 0`.
- Known feed gap handling:
  - parquet feed omits `00*` symbols (including `0050`), so replay adds a `0050` proxy stream from legacy text when available, else falls back to day-bar open synthesis.

## Key Differences: Parquet vs Legacy Text (OTC and TSEQuote)

## A. File layout and source mapping

- Legacy text:
  - one file per market/day: `TSEQuote.YYYYMMDD`, `OTCQuote.YYYYMMDD`.
- Parquet:
  - one file per market/day under separate dirs: `TWSE/YYYYMMDD.parquet`, `TPEX/YYYYMMDD.parquet`.
  - engine maps `TSE -> TWSE`, `OTC -> TPEX`.

Impact:

- different storage/index behavior and availability checks,
- separate guard logic for symbol files is now required and implemented.

## B. Row inclusion/filter semantics

- Legacy text replay stream:
  - parsed from `Trade,...` rows with optional paired depth row.
  - row accepted when `status_code == 0`.
- Parquet replay stream:
  - accepted when `matchFlag == "Y"`, `time >= 09:00`, and `tradeVolume > 0`.

Impact:

- stream shape can differ even if cumulative traded volume is close.
- differences in zero-quantity/quote-like snapshots can still perturb intraday state (day high/low, ranking timing), changing marginal entry decisions.

## C. Quantity semantics and history effects

- Legacy text history:
  - uses parsed text trade qty field directly.
- Parquet history:
  - uses `tradeVolume` from parquet rows.

Impact:

- `MonthTradingVal` / `VolRatio` may drift across sources on some dates.
- this can change screening qualification and trade membership.

## D. Symbol-universe difference (`00*`, including `0050`)

- Legacy text contains many `00*` symbols.
- Parquet omits `00*` symbols (documented in active migration findings), including `0050`.

Impact:

- core replay loop already excludes `00*` symbols from trading logic.
- `0050` is special because market gate depends on it.
- current mitigation:
  - parquet mode attempts a text proxy for `0050`,
  - otherwise synthesizes from day-bar open.
- still a data-source difference by definition; parity cannot be assumed.

## E. Path-specific infra differences

- Text mode depends on volume cache and rolling history behavior.
- Parquet mode now has its own binary day-cache + rolling history path.
  - cache module: `market_data/parquet_history_cache.py`
  - rolling provider: `market_data/parquet_rolling_history.py`
  - precompute CLI: `python -m tw_signal_engine.cli.build_parquet_history_cache`

Impact:

- performance and failure modes differ.
- operational checks should be source-specific.

## Why Strict Parity Is the Wrong Acceptance Gate Now

Existing evidence in active plan notes already shows:

- several dates still produce non-float output diffs under text vs parquet A/B replay,
- root causes are dominated by source-data semantic differences, not simple conversion bugs,
- 00-symbol coverage differences and stream-shape differences are structural.

Given this, treating parquet as "must be byte-identical to text" turns expected upstream-source differences into false failures, and blocks migration closure indefinitely.

## Recommended New Contract (Source-Separated Truth)

Adopt this policy:

1. `text` and `parquet` are two valid replay data sources.
2. each source must be internally consistent and deterministic for the same source input.
3. cross-source equality is observational, not a hard gate.
4. differences must be explainable, monitored, and documented.

## Required acceptance criteria under new policy

For parquet mode:

- replay runs complete with valid outputs and no source-contract violations,
- schema/required-column checks pass,
- source guards are explicit (missing symbols files, missing parquet files),
- key invariants hold:
  - chronological tick order,
  - non-negative volumes,
  - expected market mapping (`TSE`/`OTC`),
  - valid price scaling and time conversion,
  - stable output given identical parquet inputs.

For text mode:

- preserve as compatibility/fallback path until retirement decision is explicit.

For cross-source comparison:

- keep diff tooling as diagnostics only,
- classify diffs into:
  - expected source differences,
  - potential regressions.

## Files and Docs That Should Change

This section lists what should change to adopt the new policy cleanly.

## Priority 0: policy docs and active plans

1. `docs/exec-plans/active/parquet-text-ground-truth-parity-filter.md`
   - current purpose enforces text as canonical truth for parquet normalization.
   - action: mark obsolete under new policy, or convert into an archived investigation record.

2. `docs/exec-plans/active/market-data-parquet-migration.md`
   - current M6 gate still expects strict output parity; M8 retirement depends on this.
   - action: replace strict parity gate with source-contract gate + diff classification.
   - action: rewrite success criteria and pending milestones accordingly.

3. `docs/exec-plans/active/index.md`
   - action: rename/remove references that imply text-ground-truth enforcement as active policy.

## Priority 1: user-facing runtime docs

4. `docs/references/runtime-conventions.md`
   - currently text-centric in layout/examples.
   - action: document both source layouts and clarify default replay source and guard behavior.

5. `docs/design-docs/runtime-architecture.md`
   - currently text-only in several lifecycle descriptions.
   - action: add explicit dual replay source flow and source-separation contract.

6. `docs/design-docs/live-data-architecture.md`
   - currently frames replay default around `FileReplayProvider`.
   - action: update provider descriptions to include parquet replay path as first-class.

7. `README.md`
   - examples still default to `exec/data` text layout.
   - action: add parquet-root examples and a short explanation of source-specific truth.

8. `CLAUDE.md`
   - currently points commands/assumptions to `exec/data` text replay.
   - action: align default examples and guidance with current parquet default.

9. `ARCHITECTURE.md`
   - action: update top-level runtime flow narrative so it does not imply text-only merge path.

## Priority 2: scripts/tests and observability

10. `scripts/compare_text_vs_parquet.py`
    - currently framed as parity-gate script.
    - action: reposition as diagnostic/audit script, with difference classification output.

11. `tests/unit/test_parquet_history_loader.py`
12. `tests/unit/test_parquet_replay_provider.py`
    - currently include text-anchored tolerance parity checks.
    - action: keep optional cross-source checks as non-gating diagnostics.
    - action: strengthen source-internal invariants (determinism, schema, ordering, guards).

13. `src/tw_signal_engine/replay/replay_session.py`
14. `src/tw_signal_engine/reporting/build_trade_report_rows.py`
    - action: consider adding explicit `data_source` provenance into logs/reports/metadata so analysts can reason about source-driven differences without ambiguity.

## Migration Closure Recommendation

Declare parquet integration complete for replay path once:

1. the policy/documentation shifts above are merged,
2. source-contract checks are green for parquet mode on representative dates,
3. cross-source diff tooling is converted to diagnostic reporting (not release gate),
4. the team explicitly decides long-term status of legacy text path (`fallback` vs `retire`).

## Practical Risks If Docs Are Not Updated

- engineers will continue chasing strict parity that is no longer the objective,
- plan state remains contradictory (default already parquet, but acceptance still text-equality),
- incident triage will waste time because source-specific differences look like regressions by default,
- eventual deprecation decisions become blocked by outdated success criteria.

## Appendix: Concrete Code/Doc Evidence Pointers

- parquet default in daily CLI: `src/tw_signal_engine/cli/run_daily_replay.py:20-23`
- parquet default in batch CLI: `src/tw_signal_engine/cli/run_batch_replay.py:71-74`
- replay source branching and parquet guard: `src/tw_signal_engine/replay/replay_session.py:442-450`, `:477-492`, `:624-641`
- parquet `0050` mitigation path: `src/tw_signal_engine/replay/replay_session.py:563-604`, `:696-711`
- shared parquet status filter and mapping: `src/tw_signal_engine/market_data/parquet_io.py:40-43`, `:57-60`, `:98-110`
- parquet history loader behavior: `src/tw_signal_engine/market_data/parquet_history_loader.py:87-107`
- parquet replay loader behavior: `src/tw_signal_engine/market_data/parquet_replay_provider.py:57-65`, `:118-137`
- legacy text replay filter behavior: `src/tw_signal_engine/replay/iterate_market_file.py:90-92`
- legacy text history qty behavior: `src/tw_signal_engine/market_data/parse_history_trades.py:53-60`
- active parity assumptions in plans:
  - `docs/exec-plans/active/market-data-parquet-migration.md:27-30`
  - `docs/exec-plans/active/parquet-text-ground-truth-parity-filter.md:8-10`, `:58-60`
- currently text-centric conventions docs:
  - `docs/references/runtime-conventions.md:5-19`, `:70-73`
  - `docs/design-docs/runtime-architecture.md:9-13`, `:29-34`, `:63-69`
  - `README.md:11-17`, `:29-36`
  - `CLAUDE.md:26-32`, `:44-45`
