# Merge `strategy-vwap-touch` into `data-migration/market-data-parquet`

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document is maintained in accordance with `docs/references/exec-plan-standard.md`.


## Purpose / Big Picture

This plan merges the strategy work from `strategy-vwap-touch` into the current data migration branch, `data-migration/market-data-parquet`, without losing either branch's user-visible behavior. After the merge, a user should be able to run daily and batch replay against the default parquet market-data source while also using the new strategy behavior from `strategy-vwap-touch`, including short Signal A compatibility, explicit SignalAShort support, SignalDayHigh, overnight carry handling, side-aware order logs, and expanded report columns.

The merge matters because both branches changed the same replay orchestration layer for different reasons. The data-migration branch made parquet the default replay source and added source provenance, source-contract validation, 0050 proxy handling, and no-output diagnostic replay. The strategy branch changed strategy semantics, execution policy, report shape, and CLI path defaults. Choosing either branch wholesale would regress the other. The correct outcome is an integrated replay engine in which market-data source selection and strategy selection are independent axes.

A human can see the completed merge working by running the normal validation commands from the repository root:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Then run at least one daily replay with `--data-source parquet` and one with `--data-source text` where local data is available. The parquet run should produce reports whose `report_trades.csv` includes `DataSource=parquet`, `Side`, `ExitTradeDate`, and `IsOvernight` columns. Strategy tests for short mode and DayHigh should pass at the same time as parquet provider and source-contract tests.


## Progress

- [x] (2026-04-20) Conflict inventory completed with `git merge-tree` and a temporary detached worktree. The merge has 12 content-conflict files: `README.md`, `docs/design-docs/live-data-architecture.md`, `docs/design-docs/runtime-architecture.md`, `docs/exec-plans/active/index.md`, `docs/references/index.md`, `docs/references/runtime-conventions.md`, `src/tw_signal_engine/cli/run_batch_replay.py`, `src/tw_signal_engine/cli/run_daily_replay.py`, `src/tw_signal_engine/replay/replay_session.py`, `src/tw_signal_engine/reporting/build_trade_report_rows.py`, `tests/unit/test_replay_session.py`, and `tests/unit/test_report_output.py`.
- [x] (2026-04-20) Branch-favoring policy agreed: preserve data-migration for parquet/source behavior, preserve `strategy-vwap-touch` for strategy/execution/report behavior, and combine both where the changes are additive.
- [x] (2026-04-20) This ExecPlan was written and registered in `docs/exec-plans/active/index.md`.
 - [x] Create a clean merge work state, confirm the current branch is `data-migration/market-data-parquet`, and capture the pre-merge test baseline.
 - [x] Merge `strategy-vwap-touch` with `--no-commit`, resolve all documentation conflicts according to this plan, and verify no unrelated uncommitted work was overwritten.
 - [x] Resolve CLI conflicts so both parquet data-source behavior and environment/default path helpers survive.
 - [x] Resolve replay-session conflicts so parquet provider selection, 0050 proxy behavior, `write_outputs`, short/day-high/overnight strategy behavior, side-aware logs, and detailed screening hooks all survive together.
 - [x] Resolve report and test conflicts so report provenance and strategy report fields are both asserted.
- [x] (2026-04-20) Run focused tests for changed areas, then full unit/lint/type validation.
- [x] (2026-04-20) Complete the merge commit and update `Outcomes & Retrospective` with validation evidence.


## Surprises & Discoveries

- Observation: Most conflicts are additive rather than mutually exclusive. The data-migration branch owns source selection and parquet runtime semantics, while `strategy-vwap-touch` owns strategy semantics and report shape.
  Evidence: `git merge-tree --write-tree HEAD strategy-vwap-touch` reported conflicts in the same files, but the conflicting hunks were typically adjacent additions such as `data_source` versus `overnight_holdings`, or `DataSource` versus `ExitTradeDate`/`IsOvernight`.

- Observation: The largest risk is not the visible conflict marker count, but preserving method signatures after auto-merged files from `strategy-vwap-touch` land.
  Evidence: `strategy-vwap-touch` changes `OrderLogWriter.write_entry()` and `write_leave()` to include a `side` argument. Data-migration adds `_NullOrderLogWriter` and no-output diagnostic replay. The integrated code must update the no-op writer and every preserved call site to the side-aware signature.

- Observation: The active plans index already had uncommitted changes before this plan was added.
  Evidence: `git status --short docs/exec-plans/active` showed `M docs/exec-plans/active/index.md` and `?? docs/exec-plans/active/readfilemerged-low-risk-wins.md`. Preserve those changes and do not claim authorship of them.


## Decision Log

- Decision: Resolve the merge as an integration, not as `ours` or `theirs` wholesale.
  Rationale: Both branches carry valid product behavior. Data-migration makes parquet replay the default and records source provenance. `strategy-vwap-touch` adds strategy modes and reporting fields. Either branch by itself is incomplete after the merge.
  Date/Author: 2026-04-20 / Codex with user approval.

- Decision: In this plan, `ours` means `data-migration/market-data-parquet` and `theirs` means `strategy-vwap-touch`.
  Rationale: The planned operation is merging `strategy-vwap-touch` into the current data-migration branch. Git conflict markers use `HEAD` for the current branch and the other branch name for the incoming branch. Naming this explicitly prevents inverted decisions during conflict resolution.
  Date/Author: 2026-04-20 / Codex.

- Decision: Keep data-migration as the base for market-data source behavior.
  Rationale: The current branch intentionally defaults daily and batch replay to parquet, preserves text as explicit compatibility via `--data-source text`, adds parquet history/replay providers, guards missing Symbols files, and records `DataSource` in reports. Reverting these behaviors would undo the migration branch's purpose.
  Date/Author: 2026-04-20 / Codex with user approval.

- Decision: Keep `strategy-vwap-touch` as the base for strategy and execution behavior.
  Rationale: The incoming branch owns short-mode compatibility, SignalAShort, SignalDayHigh, DayHigh overnight carry, side-aware execution/reporting, expanded cost model behavior, and related tests. Reverting these behaviors would lose the strategy work being merged.
  Date/Author: 2026-04-20 / Codex with user approval.

- Decision: Use the canonical repository plan path `docs/exec-plans/active/` rather than creating `docs/exec-plan/active/`.
  Rationale: `AGENTS.md`, `docs/index.md`, and `docs/references/exec-plan-standard.md` identify `docs/exec-plans/active/` as the active plan location. Creating a singular parallel directory would reduce discoverability and violate the repository's documentation conventions.
  Date/Author: 2026-04-20 / Codex.


## Outcomes & Retrospective

Merge completed with an integrated resolution set that preserves:

- Parquet/text replay source selection and default behavior from `data-migration/market-data-parquet`.
- Strategy-vwap-touch execution and reporting features, including short mode and DayHigh behavior.
- Data source provenance and report-compatibility columns in batch/daily replay outputs.

Validation executed:

- `uv run pytest tests/unit/test_replay_session.py -q` (11 passed).
- `uv run pytest tests/unit/test_report_output.py -q` (9 passed).
- `uv run pytest tests/unit/test_parquet_replay_provider.py tests/unit/test_parquet_history_loader.py -q` (passed).
- `uv run pytest tests/unit/test_day_high_replay.py tests/unit/test_replay_short_mode.py tests/unit/test_signal_day_high.py -q` (passed).
- `uv run pytest tests -q` (377 passed, 3 skipped).
- `uv run ruff check src tests` (passed).
- `uv run mypy src` (passed).

Residual risks: no residual functional blocker observed in this pass. The next verification is environment-dependent:
- local replay smoke check for both `--data-source parquet` and `--data-source text`.


## Context and Orientation

This repository's active implementation is the Python replay engine in `src/tw_signal_engine/`. The daily CLI entry point is `src/tw_signal_engine/cli/run_daily_replay.py`. The batch CLI entry point is `src/tw_signal_engine/cli/run_batch_replay.py`. Both call `run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py`, which loads config, reference data, history windows, creates a market-data provider, processes ticks in chronological order, runs screening and signal evaluation, manages open positions, writes order logs, and generates reports.

A market-data provider is any object implementing `MarketDataProvider` from `src/tw_signal_engine/market_data/providers.py`. It yields `MarketTick` objects. The data-migration branch has two replay providers. `FileReplayProvider` reads legacy text files named `TSEQuote.YYYYMMDD` and `OTCQuote.YYYYMMDD`. `ParquetReplayProvider` reads parquet files under `TWSE/YYYYMMDD.parquet` and `TPEX/YYYYMMDD.parquet`. In the merged code, CLI users choose the source with `--data-source text` or `--data-source parquet`, and parquet remains the default.

A history window is the prior-session volume and trading-value data used by the strong-group and strong-single screeners. The text path uses `load_history_window()` from `src/tw_signal_engine/market_data/load_history_window.py`. The parquet path uses `load_parquet_history_window()` from `src/tw_signal_engine/market_data/parquet_history_loader.py`. Batch replay uses rolling history providers for repeated dates. In the merged code, batch replay must keep data-source-specific history providers.

The market gate is the logic in `src/tw_signal_engine/replay/apply_market_gate.py` that tracks the ETF symbol `0050` and can disable trading under broad-market conditions. The parquet tick feed omits `00*` symbols including `0050`, so data-migration adds a 0050 sidecar/proxy/backfill path in `replay_session.py`. This must survive the merge because otherwise parquet replay can silently lose market-gate semantics.

A strategy signal is a rule that can trigger an entry trade. The base engine already has Signal A and Signal B. `strategy-vwap-touch` adds or changes short Signal A compatibility, explicit SignalAShort, and SignalDayHigh behavior. It also adds `policy_for_signal()` in `src/tw_signal_engine/execution/signal_policy.py` so execution behavior can vary by signal. In the merged code, these strategy changes must operate regardless of whether the market-data source is text, parquet, live provider, or a test provider.

An overnight holding is a DayHigh position carried from one trading day to the next when a limit-up lock prevents normal exit. `strategy-vwap-touch` represents this with `OvernightHolding` in `src/tw_signal_engine/records/overnight_records.py` and passes an `overnight_holdings` dictionary through batch replay into `run_daily_replay()`. In the merged code, this dictionary must be preserved in batch mode and must not conflict with data-migration's `data_source` argument.

`write_outputs` is a data-migration argument to `run_daily_replay()`. When false, replay still computes trades and returns them but does not write order logs or reports. This is useful for diagnostics and tests. The merged code must keep this option and update its no-op order writer to match the side-aware order log signature from `strategy-vwap-touch`.

A report row is written by `src/tw_signal_engine/reporting/build_trade_report_rows.py`. Data-migration adds a `DataSource` column. `strategy-vwap-touch` adds `Side`, `ExitTradeDate`, and `IsOvernight`. The merged report must contain all of these fields. Tests should assert all of them so a future change cannot accidentally drop either branch's report contract.


## Plan of Work

Start from the current branch `data-migration/market-data-parquet`. Before merging, run `git status --short --branch` and inspect uncommitted changes. This plan was authored while `docs/exec-plans/active/index.md` and `docs/exec-plans/active/readfilemerged-low-risk-wins.md` already had uncommitted changes. Treat them as user work unless you authored them in the current execution. Do not revert them. If additional unexpected changes appear in unrelated files, stop and ask the user how to proceed.

Create a merge branch or perform the merge directly on `data-migration/market-data-parquet` according to the user's preference. The safest implementation path is a temporary integration branch created from the current branch:

    git switch data-migration/market-data-parquet
    git switch -c integration/merge-strategy-vwap-touch

If the user explicitly wants the merge commit on `data-migration/market-data-parquet`, skip the temporary branch. In either case, run the merge without committing automatically:

    git merge --no-commit --no-ff strategy-vwap-touch

Git should report content conflicts in the 12 files listed in `Progress`. If the conflict list differs, update this plan's `Surprises & Discoveries` before resolving anything, because a changed conflict set means one of the branches moved after this plan was written.

Resolve documentation conflicts first because they are lower risk and clarify intent. In `README.md`, keep both sections: the parquet history cache/source-separation instructions from data-migration and the charts-only CLI instructions from `strategy-vwap-touch`. In `docs/design-docs/live-data-architecture.md`, keep data-migration's provider ordering and describe `ParquetReplayProvider` as the default daily and batch replay provider. Keep `FileReplayProvider` as explicit `--data-source text` compatibility. Do not restore strategy's stale wording that text replay is the normal batch path. In `docs/design-docs/runtime-architecture.md`, combine the two branches: keep data-migration's parquet/text input model and source-separation note, and add strategy's environment/default path resolution details for `--files-dir`, `--group-file`, and legacy fallbacks.

In `docs/exec-plans/active/index.md`, preserve all existing uncommitted entries. Keep the active parquet migration and 0050 sidecar plans. Do not keep Redis live remediation as active if the merge brings the completed copy from strategy and the plan itself says completed; move that index entry to completed only if you are intentionally cleaning the index as part of this merge and the file location also matches. Do not replace the whole active index with strategy's "No active plans" text because this branch has active data-migration plans. If there is uncertainty, choose the least destructive option: keep all current active entries and add only this merge plan or any newly active strategy plan that truly remains active.

In `docs/references/index.md`, keep strategy's cleaned-up parity wording and add data-migration's `parquet-vs-text-data-source-findings.md` reference. In `docs/references/runtime-conventions.md`, keep data-migration's parquet default conventions, preferred parquet layout, and text compatibility section. Also add strategy's environment-based default path resolution order. The final document should tell users that daily and batch replay default to parquet, while CLI flags and environment variables can override data, files, and group locations.

Resolve CLI code next. In `src/tw_signal_engine/cli/run_batch_replay.py`, use data-migration as the structural base because it already knows how to discover parquet dates, split dates by missing Symbols files, create `ParquetRollingHistoryProvider`, create `RollingHistoryProvider`, and pass `data_source` into `run_daily_replay()`. Preserve strategy's import of `tw_signal_engine.cli.default_paths` and use its helpers for `--files-dir` and `--group-file`. For `--data-dir`, keep data-migration's source-sensitive behavior: the parser should accept `default=None`, and after parsing it should resolve to `TW_SIGNAL_PARQUET_DATA_DIR` or `./data/` when `data_source == "parquet"`, and to the text default when `data_source == "text"`. If you decide to use `default_paths.default_data_dir()` for text defaults, make sure it does not override the parquet-specific `TW_SIGNAL_PARQUET_DATA_DIR` behavior. Import `OvernightHolding` from `src/tw_signal_engine/records/overnight_records.py`, initialize `overnight_holdings: dict[str, OvernightHolding] = {}` before the date loop, and pass both `data_source=args.data_source` and `overnight_holdings=overnight_holdings` into `run_daily_replay()`.

In `src/tw_signal_engine/cli/run_daily_replay.py`, again use data-migration as the structural base because it exposes `--data-source` and source-sensitive `data_dir` resolution. Preserve strategy's shared default path helper imports for files and group path defaults. The final CLI must accept `--data-source {text,parquet}` with default `parquet`, must pass `data_source=args.data_source` to `run_daily_replay()`, and must keep `--no-cache`, `--no-charts`, and `--cost-model` behavior.

Resolve `src/tw_signal_engine/reporting/build_trade_report_rows.py` by combining report columns. The final function signature should accept `data_source: str = ""`. The header should include strategy's `Side`, `ExitTradeDate`, and `IsOvernight`, and data-migration's `DataSource`. Keep the rest of the existing columns in their current order as much as possible to minimize downstream report churn. A safe order at the end of the row is `TradeDate`, `ExitTradeDate`, `IsOvernight`, `DataSource`, `EntryHourBucket`. Each row should write `t.trade_date`, `t.exit_trade_date`, `1 if t.is_overnight else 0`, `data_source`, and `t.entry_hour_bucket` in the same order. The beginning of the row should include `t.symbol`, `t.side`, and `t.signal_type` if the merged `TradeRecord` has `side`, as it does on `strategy-vwap-touch`.

Resolve `src/tw_signal_engine/replay/replay_session.py` last because it has the most semantic coupling. Keep all imports needed by both branches: `os`, `Path`, `Iterator`, parquet history/provider helpers, parquet price conversion, 0050 sidecar helpers, `QuotePair`, `OvernightHolding`, `ReferenceSymbol`, `SignalAShortConfig`, `TradeMode`, `policy_for_signal`, `evaluate_signal_a_short`, `evaluate_signal_day_high`, and `SignalDayHighState`. Remove only imports that become truly unused after the integrated code is complete.

The integrated `run_daily_replay()` signature must include all three branch-specific parameters near the end:

    data_source: str = "text",
    write_outputs: bool = True,
    overnight_holdings: dict[str, OvernightHolding] | None = None,

Keep data-migration's validation that `data_source` is either `"text"` or `"parquet"`. Keep `report_data_source = "provider" if provider is not None else data_source`. Keep the missing-Symbols guard for parquet. Keep strategy's cost-model override behavior that updates `day_trade_tax_rate` and conditionally updates `overnight_tax_rate` when `tax` is overridden.

In the history-loading section, keep data-migration's data-source switch. When `history is None` and `data_source == "parquet"`, call `load_parquet_history_window()` for both markets. When `data_source == "text"`, call `load_history_window()`. When `history` is supplied, do not load either source. This preserves batch-mode prebuilt history and tests that inject custom history.

In the screening setup, keep strategy's trade-mode-aware `StrongGroupEvaluator` construction, `strong_group_short`, `signal_a_short_map`, `signal_day_high_map`, `compatibility_short_mode`, `legacy_short_signal_a_enabled`, and `strong_single_enabled_for_entry`. Also preserve data-migration's `ScreeningDetail` hook behavior. The integrated loop should call the simple `hooks.on_screening()` with the match type relevant to the active mode, and when `hooks.on_screening_detail` is present it should emit a `ScreeningDetail` populated from the evaluator that produced the relevant match. For long mode, use `strong_group` and `long_match_type`. For compatibility short mode or SignalAShort-only screening, use `strong_group_short` when it exists and `short_match_type`. Preserve fields such as `ahead_symbol`, `behind_symbol`, group rank, member rank, raw member rank, M1 symbol, volume ratio, and month trading value.

In the market-gate setup and event loop, keep data-migration's 0050 sidecar/proxy/day-bar backfill. The parquet path must initialize `proxy_0050_iter` and `proxy_0050_next` when possible, drain the proxy stream before each normal tick, and call the same market-disable finalization path when the gate disables trading. Integrate this with strategy's overnight behavior: if the market gate disables trading while there are pending overnight exits, finalize open intraday positions once, keep processing enough ticks to close carried overnight holdings, and generate reports only after pending overnight exits are resolved. If no overnight exits are pending, data-migration's helper `_finalize_for_market_disable()` can return immediately after optional report generation. Avoid double-closing `log_writer`.

In the provider setup, preserve data-migration's precedence rule: if the caller supplies `provider`, use it directly. If no provider is supplied and `data_source == "parquet"`, create `ParquetReplayProvider`; otherwise create `FileReplayProvider`. This rule is critical for live mode and tests that inject a fake provider.

In the exit and entry logic, preserve strategy's side-aware behavior. `on_tick_exit()` call sites should pass bid and ask prices in the order expected by the strategy branch. `write_leave()` calls must include `side`. `should_enter()` and `execute_entry()` calls must use the strategy branch's signatures, including `selected_trade_mode`, `selected_signal_type`, and `selected_group_eval`. Preserve SignalDayHigh priority above SignalA, SignalAShort, and SignalB. Preserve data-migration's MAE/MFE initialization and hooks. Preserve `write_outputs`: when false, use `_NullOrderLogWriter`, skip `_generate_reports()`, and do not create report files.

Update `_NullOrderLogWriter` and its protocols to match the side-aware order-log signature from `strategy-vwap-touch`. The no-op `write_entry()` should accept `side` between `cause` and `remaining_qty`. The no-op `write_leave()` should accept `side` between `cause` and `remaining_qty`. This is required because tests may run with `write_outputs=False` and still execute entry or exit paths.

Update `_generate_reports()` in `replay_session.py` so it accepts `data_source: str = ""` and passes that value into `write_trade_report()`. Every call to `_generate_reports()` in the integrated file must pass `report_data_source` where reports are generated from `run_daily_replay()`. Tests that monkeypatch `_generate_reports` with `lambda *args, **kwargs: None` should continue to work.

Resolve tests after code. In `tests/unit/test_replay_session.py`, keep both signature assertions: `write_outputs` and `overnight_holdings` should both be present in `inspect.signature(run_daily_replay).parameters`. Preserve data-migration's screening-detail test expectations and strategy's short-mode tests. If the integrated screening detail emits additional useful events because short and long screening both run, update the expected events only after confirming the behavior is intentional and stable.

In `tests/unit/test_report_output.py`, assert all merged columns. The header should contain `DataSource`, `Side`, `ExitTradeDate`, and `IsOvernight`. If row-value tests exist, update them to verify that parquet reports write the selected data source and overnight trades write the overnight metadata.

After all conflict markers are removed, run `rg '<<<<<<<|=======|>>>>>>>'` from the repository root. It must return no conflict markers. Then run focused tests before the full suite. Useful focused commands are:

    uv run pytest tests/unit/test_replay_session.py -q
    uv run pytest tests/unit/test_report_output.py -q
    uv run pytest tests/unit/test_parquet_replay_provider.py tests/unit/test_parquet_history_loader.py -q
    uv run pytest tests/unit/test_day_high_replay.py tests/unit/test_replay_short_mode.py tests/unit/test_signal_day_high.py -q

Fix failures in the smallest scope possible. If failures reveal an unexpected behavior, update `Surprises & Discoveries` in this plan with the command and concise output.

When focused tests pass, run the full validation gate:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

If local data is available, run one smoke replay for parquet and one for text. Use dates and paths that exist on the machine. The expected result is that parquet replay uses `ParquetReplayProvider`, text replay uses `FileReplayProvider`, both write reports unless `--no-charts` only skips chart generation, and the parquet report includes `DataSource=parquet`.


## Concrete Steps

From the repository root `/home/r12944005/b07401012/Trading/signal`, confirm branch and status:

    git status --short --branch
    git branch --show-current

Expected branch before the merge:

    data-migration/market-data-parquet

Confirm the conflict set before starting the real merge:

    git merge-tree --name-only HEAD strategy-vwap-touch

Expected conflict filenames are the 12 files listed in `Progress`. If the output includes different files, update this plan before continuing.

Start the merge:

    git merge --no-commit --no-ff strategy-vwap-touch

Resolve conflicts file by file. After each file, run a syntax or targeted check where cheap. Use `git diff --check` periodically to catch whitespace errors. Use `git diff --name-only --diff-filter=U` to list remaining unresolved files.

When all conflicts are resolved:

    rg '<<<<<<<|=======|>>>>>>>'
    git diff --check
    git diff --name-only --diff-filter=U

Expected output for the conflict-marker search is empty. Expected output for unresolved files is empty. `git diff --check` should not report whitespace errors.

Run focused tests, then full validation:

    uv run pytest tests/unit/test_replay_session.py -q
    uv run pytest tests/unit/test_report_output.py -q
    uv run pytest tests/unit/test_parquet_replay_provider.py tests/unit/test_parquet_history_loader.py -q
    uv run pytest tests/unit/test_day_high_replay.py tests/unit/test_replay_short_mode.py tests/unit/test_signal_day_high.py -q
    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Inspect staged and unstaged changes before committing:

    git status --short
    git diff --stat

If the diff includes unrelated user changes, do not include them in the merge commit unless they are already part of the in-progress merge result and the user has approved. When ready, commit the merge:

    git commit

Use a merge commit message that names both branches and summarizes the integrated behavior, for example:

    Merge strategy-vwap-touch into data-migration parquet replay


## Validation and Acceptance

The merge is acceptable only when source behavior and strategy behavior both work in the same tree. Passing only parquet tests is insufficient. Passing only strategy tests is insufficient.

Required automated validation:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Required focused behavior validation:

    uv run pytest tests/unit/test_replay_session.py -q
    uv run pytest tests/unit/test_report_output.py -q
    uv run pytest tests/unit/test_parquet_replay_provider.py tests/unit/test_parquet_history_loader.py -q
    uv run pytest tests/unit/test_day_high_replay.py tests/unit/test_replay_short_mode.py tests/unit/test_signal_day_high.py -q

Required report-shape acceptance: `report_trades.csv` must include `Side`, `TradeDate`, `ExitTradeDate`, `IsOvernight`, `DataSource`, and `EntryHourBucket`. The exact order should be stable and covered by tests.

Required replay-session signature acceptance: `run_daily_replay()` must accept `data_source`, `write_outputs`, and `overnight_holdings`. A test should assert these parameters exist.

Required provider-selection acceptance: when `provider` is passed to `run_daily_replay()`, it must win over `data_source`. When no provider is passed and `data_source == "parquet"`, the function must create a `ParquetReplayProvider`. When no provider is passed and `data_source == "text"`, the function must create a `FileReplayProvider`.

Required no-output acceptance: when `write_outputs=False`, replay should be able to execute without creating order logs or reports, and the no-op writer should accept side-aware entry and leave calls.

Required overnight acceptance: batch replay should carry one `overnight_holdings` dictionary across all dates in the loop and pass it into every `run_daily_replay()` call.

Required documentation acceptance: README and runtime docs should not describe text replay as the default daily/batch path. They should say parquet is the default and text is explicit compatibility.


## Idempotence and Recovery

The pre-merge inspection commands are read-only and can be repeated. `git merge --no-commit --no-ff strategy-vwap-touch` is safe to run once from a clean merge state. If the merge is in progress and you need to abandon only the merge attempt, use `git merge --abort`. Do not use `git reset --hard` because this repository may contain unrelated user changes.

If a file resolution goes wrong, prefer restoring one file from a known side into a temporary path and reapplying the intended integration manually. For example:

    git show HEAD:src/tw_signal_engine/replay/replay_session.py > /tmp/replay_session.ours.py
    git show strategy-vwap-touch:src/tw_signal_engine/replay/replay_session.py > /tmp/replay_session.theirs.py

Then compare those temporary files to the conflicted working file. Do not check out either side over the working file unless you are certain it contains no unrelated manual resolution work.

If validation fails after conflict markers are gone, fix code rather than changing tests to match a regression. Test updates are appropriate only where the merged behavior intentionally contains both branches' contracts, such as expecting both `DataSource` and `IsOvernight` columns.

If local parquet/text market data is unavailable, skip manual replay smoke commands and record that limitation in `Outcomes & Retrospective`. Automated unit tests remain required.


## Artifacts and Notes

Conflict inventory captured before this plan was written:

    README.md
    docs/design-docs/live-data-architecture.md
    docs/design-docs/runtime-architecture.md
    docs/exec-plans/active/index.md
    docs/references/index.md
    docs/references/runtime-conventions.md
    src/tw_signal_engine/cli/run_batch_replay.py
    src/tw_signal_engine/cli/run_daily_replay.py
    src/tw_signal_engine/replay/replay_session.py
    src/tw_signal_engine/reporting/build_trade_report_rows.py
    tests/unit/test_replay_session.py
    tests/unit/test_report_output.py

Per-file branch-favoring summary:

    README.md: keep both branches.
    docs/design-docs/live-data-architecture.md: favor data-migration provider semantics.
    docs/design-docs/runtime-architecture.md: combine data-migration runtime model with strategy path defaults.
    docs/exec-plans/active/index.md: preserve current active migration entries; do not use strategy's empty-active index wholesale.
    docs/references/index.md: keep both parity wording cleanup and parquet findings link.
    docs/references/runtime-conventions.md: combine parquet default conventions with env path resolution.
    src/tw_signal_engine/cli/run_batch_replay.py: data-migration base plus strategy default paths and overnight holdings.
    src/tw_signal_engine/cli/run_daily_replay.py: data-migration base plus strategy default path helpers.
    src/tw_signal_engine/replay/replay_session.py: full integration; do not favor either side wholesale.
    src/tw_signal_engine/reporting/build_trade_report_rows.py: keep DataSource plus Side, ExitTradeDate, and IsOvernight.
    tests/unit/test_replay_session.py: keep both branches' assertions and tests.
    tests/unit/test_report_output.py: assert all merged report columns.

Known semantic dependency outside conflict markers:

    strategy-vwap-touch changes OrderLogWriter.write_entry() and write_leave() to include side.
    data-migration adds _NullOrderLogWriter for write_outputs=False.
    The integrated _NullOrderLogWriter must accept side too.


## Interfaces and Dependencies

At the end of the merge, `src/tw_signal_engine/replay/replay_session.py` must expose this integrated shape:

    def run_daily_replay(
        trade_date: str,
        config_path: str = "./cfg/parameter.cfg",
        data_dir: str = "./data/",
        files_dir: str = "./files/",
        group_file: str = "./files/group.csv",
        log_folder: str = "",
        use_cache: bool = True,
        history: HistoryWindow | None = None,
        no_charts: bool = False,
        cost_model_override: str = "",
        provider: MarketDataProvider | None = None,
        hooks: SessionHooks | None = None,
        on_dashboard_snapshot: Callable[[DashboardSnapshot], None] | None = None,
        data_source: str = "text",
        write_outputs: bool = True,
        overnight_holdings: dict[str, OvernightHolding] | None = None,
    ) -> list[TradeRecord]:

If the exact argument order changes during implementation, tests and call sites must still make all parameters available by name. Do not remove `provider`, because live mode and tests depend on injection. Do not remove `history`, because batch replay and tests depend on prebuilt history. Do not remove `data_source`, because parquet/text selection depends on it. Do not remove `write_outputs`, because diagnostic replay depends on it. Do not remove `overnight_holdings`, because DayHigh overnight carry depends on it.

`src/tw_signal_engine/reporting/build_trade_report_rows.py` must expose:

    def write_trade_report(
        completed_trades: list[TradeRecord],
        log_dir: str,
        market_open_chg_pct: float = 0.0,
        data_source: str = "",
    ) -> None:

`src/tw_signal_engine/cli/run_batch_replay.py` must pass both `data_source` and `overnight_holdings` into `run_daily_replay()`. `src/tw_signal_engine/cli/run_daily_replay.py` must pass `data_source` into `run_daily_replay()`.

The report writer must rely on `TradeRecord` fields from the merged model, including `side`, `trade_date`, `exit_trade_date`, `is_overnight`, and `entry_hour_bucket`. If any of these fields are missing after merge, the correct fix is to preserve the `strategy-vwap-touch` model changes, not to drop report columns.


## Change Log

- 2026-04-20: Initial plan created after conflict inventory and user approval of branch-favoring decisions. The plan is intentionally prescriptive about preserving data-migration's parquet/source behavior and `strategy-vwap-touch` strategy/report behavior because the highest-risk conflicts are additive semantic conflicts rather than simple text conflicts.
