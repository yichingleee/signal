# Make Strong-Group Average Change Incremental

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Reference this repository-relative path in plan docs: `docs/references/exec-plan-standard.md`.

## Purpose / Big Picture

The replay engine is already past the low-risk wins in `docs/exec-plans/active/readfilemerged-low-risk-wins.md`, but the same core hot path still dominates runtime: strong-group screening recomputes each group's average percentage change by scanning all members on nearly every candidate tick. After this plan ships, a contributor can run the same daily parquet replay for `20260326` and observe a lower `[TIMING] readFileMerged` time without changing trade outputs, because the engine will update each group's average percentage change incrementally when a member tick arrives instead of rescanning the whole group.

The user-visible effect is indirect but measurable. The strategy should produce the same `report_trades.csv` and the same replay decisions on the same input data, while the replay completes faster. This plan is intentionally narrow: it optimizes strong-group average maintenance only. It does not redesign ranking semantics, it does not change thresholds, and it does not change the replay provider contract.

## Progress

- [x] (2026-04-21 11:10Z) Reviewed the current profiling evidence, `StrongGroupEvaluator` implementation, and ExecPlan standard before authoring this plan.
- [x] (2026-04-21 11:25Z) Authored this execution plan based on the current code under `src/tw_signal_engine/`.
- [x] (2026-04-21 20:17Z) Implement incremental strong-group average state inside `src/tw_signal_engine/screening/evaluate_strong_group.py`.
- [x] (2026-04-21 20:17Z) Update dashboard and snapshot code paths to read cached group averages instead of rescanning members.
- [x] (2026-04-21 20:24Z) Add parity-focused unit tests for long, short, weighted, and unweighted strong-group modes.
- [x] (2026-04-21 20:34Z) Re-run replay timings, profile captures, and parity checks to confirm `_group_percentage_chg()` is no longer a top replay hotspot.
- [x] (2026-04-21 20:37Z) Record benchmark evidence, final decisions, and retrospective notes in this file after implementation.

## Surprises & Discoveries

- Observation: the low-risk-wins plan reduced total replay time, but strong-group CPU is still the main replay bottleneck.
  Evidence: On 2026-04-21, running `uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260326 --data-source parquet ... --no-charts` on the current tree produced `[TIMING] readFileMerged: 32305 ms` and `[TIMING] TOTAL: 57740 ms`, with `readFileMerged` still larger than any other stage.

- Observation: `StrongGroupEvaluator.on_tick()` is still the dominant hot function in the current profile.
  Evidence: A current `cProfile` run on `20260326` with `write_outputs=False` reported `StrongGroupEvaluator.on_tick()` at `59.740s` cumulative and `_group_percentage_chg()` at `27.576s` cumulative, versus `ParquetReplayProvider.iterate_ticks()` at `13.570s`.

- Observation: the expensive average computation is used outside `on_tick()` as well.
  Evidence: `src/tw_signal_engine/screening/evaluate_strong_group.py` still calls `_group_percentage_chg()` from both `on_tick()` and `to_snapshot()`, so an incremental refactor must update both paths.

- Observation: current config does not use weighted averages, but the codebase still supports them.
  Evidence: `exec/cfg/parameter.cfg` sets `StrongGroup.is_weighted_avg=false`, while `StrongGroupConfig` in `src/tw_signal_engine/config/strategy_config.py` and `_group_percentage_chg()` in `src/tw_signal_engine/screening/evaluate_strong_group.py` still implement both weighted and unweighted behavior.

- Observation: `group_rank` currently preserves some stale behavior, and this plan must not silently "fix" it.
  Evidence: `on_tick()` only inserts or updates `self.group_rank` when `_eval_group_validity()` passes; it does not erase a group when the group later fails validity checks. That may be a behavior bug or parity quirk, but it is existing behavior and out of scope for this optimization plan.

- Observation: before/after replay validation confirms the incremental refactor is behavior-preserving on the two required dates.
  Evidence: `report_trades.csv` bytes match exactly for `20260320` and `20260326` between pre-change (`HEAD^`) and working-tree runs.

## Decision Log

- Decision: optimize both weighted and unweighted average maintenance, even though the committed config currently uses only unweighted averages.
  Rationale: the weighted path is part of the public strategy configuration. Restricting the optimization to unweighted mode would either leave a correctness fork in the class or require a permanent slow fallback that future users could accidentally ship.
  Date/Author: 2026-04-21 / Codex

- Decision: keep a slow reference implementation of group-average calculation during implementation, at least until parity tests are complete.
  Rationale: incremental math is easy to get subtly wrong for weighted averages and multi-group symbols. A slow reference helper makes exactness tests straightforward and reduces risk while refactoring.
  Date/Author: 2026-04-21 / Codex

- Decision: preserve all existing ranking and `last_match_info` semantics, including any stale-group behavior.
  Rationale: this plan is performance-only. It must not mix in ranking cleanup or behavior corrections, because that would make parity analysis ambiguous.
  Date/Author: 2026-04-21 / Codex

- Decision: treat `to_snapshot()` as part of the optimization surface.
  Rationale: snapshot generation is not the biggest cost in the profiled replay path, but `to_snapshot()` still calls the same expensive group-average scan and must stay consistent with the incremental state.
  Date/Author: 2026-04-21 / Codex

- Decision: update `group_trading_value_cumu` before `Symbol` average-state refresh in `on_tick()`.
  Rationale: this preserves the same after-tick semantics used by the previous implementation when `_group_percentage_chg()` read group totals, and the helper can safely use old per-symbol trading value for weighted numerator deltas.
  Date/Author: 2026-04-21 / Codex

## Outcomes & Retrospective

Milestone 1, 2, and 3 are complete. Runtime validation confirms milestone 4 outcomes:

- Report parity is identical for both dates tested:
  - `20260320` pre-change vs post-change `report_trades.csv` hash match: `08acedaa5441981e88c3a5d4703951d8`.
  - `20260326` pre-change vs post-change `report_trades.csv` hash match: `1ccf08f8e4cc3ae0083f0b004f30d80e`.
- On `20260326`, readFileMerged improved from `~51,062 ms` (pre-change) to `24,268 ms` (post-change), and TOTAL elapsed improved from `~74,223 ms` to `48,162 ms` in matching environment.
- Hotspot profile shifted: pre-change top cumulative in `evaluate_strong_group.py` included `_group_percentage_chg` (~36.1 s cumulative); post-change top profile shows no `_group_percentage_chg` consumer, with `StrongGroupEvaluator.on_tick` dominant and incremental update helpers (`_update_group_average_state`) as the key evaluator-time entries.
- Residual bottleneck in post-change profile is now around `evaluate_strong_group.py:157(_update_group_average_state)` (~4.3 s cumulative), with remaining provider/parquet cache setup costs behind other execution phases.
- Full test and quality gates are clean (`uv run pytest tests -q`, `uv run ruff check src tests`, `uv run mypy src`).

## Context and Orientation

The active replay engine lives in `src/tw_signal_engine/`. The daily replay entrypoint is `src/tw_signal_engine/replay/replay_session.py`. Inside `run_daily_replay()`, the replay loop pulls `MarketTick` records from either `ParquetReplayProvider` or `FileReplayProvider`, computes per-symbol intraday indicators with `IndexCalc`, then sends each candidate trade tick through strong-group screening, signals, entry logic, and exit logic.

The class this plan changes is `StrongGroupEvaluator` in `src/tw_signal_engine/screening/evaluate_strong_group.py`. This class is instantiated at least twice in a normal long-plus-short replay: once for long screening and once for short screening. It owns the following pieces of state that matter here:

- `symbol_is_valid`, which marks symbols allowed to participate in strong-group evaluation.
- `group_trading_value_cumu`, which accumulates intraday trading value per group.
- `price_last`, which stores the last traded price per symbol.
- `vol_cumu`, `group_rank`, `group_member_vwap_rank`, and `group_member_raw_vwap_rank`, which drive later filters and reporting.
- `last_match_info`, which stores the last reporting metadata for each symbol.

Today, `on_tick()` updates cumulative state and then calls `_group_percentage_chg(group, weighted_avg)` for every group the symbol belongs to. `_group_percentage_chg()` loops through every member in `self.group_members[group]`, pulls the member's latest price change from `self.price_last`, and computes either:

- an unweighted average: each valid member contributes `1 / group_member_count[group]`; or
- a weighted average: each member contributes `trading_value_cumu[symbol] / group_trading_value_cumu[group]`.

That full-member scan is the current bottleneck. On the profiled replay, `_group_percentage_chg()` was called 2,447,616 times and consumed 27.576 cumulative seconds. Because group averages change only when a member in the group receives a new tick, the engine can replace these repeated full rescans with incremental updates to cached per-group aggregates.

The same evaluator also exposes `to_snapshot()` for dashboard and snapshot reporting. `to_snapshot()` currently calls `_group_percentage_chg()` again when building each `GroupSnapshot`. Any optimization that changes how group averages are maintained must keep `to_snapshot()` consistent with the values used inside `on_tick()`.

The relevant files for this plan are:

- `src/tw_signal_engine/screening/evaluate_strong_group.py`: the main implementation to refactor.
- `src/tw_signal_engine/state/group_state.py`: ranking helper used heavily by `StrongGroupEvaluator`.
- `src/tw_signal_engine/replay/replay_session.py`: caller that exercises `StrongGroupEvaluator` in replay and uses `to_snapshot()`.
- `src/tw_signal_engine/server/dashboard_snapshot.py`: snapshot record types that surface group average percentage change.
- `tests/unit/test_evaluate_strong_group_optimizations.py`: current optimization-focused tests.
- `tests/unit/test_short_group_screening.py`: short-side strong-group coverage that must keep passing.

## Plan of Work

### Milestone 1: Add explicit incremental group-average state

At the end of this milestone, `StrongGroupEvaluator` will own enough cached state to answer "what is this group's current average percentage change?" without scanning all group members.

Edit `src/tw_signal_engine/screening/evaluate_strong_group.py` and add new private runtime fields for cached percentage-change state. Use explicit names and keep them private to the evaluator. The minimum state needed is:

- per symbol: last computed percentage change based on the symbol's latest trade price;
- per symbol: last cumulative trading value used by the weighted-average formula;
- per group: cached unweighted sum of member percentage changes;
- per group: cached weighted numerator `sum(member_trading_value * member_pct_change)`;
- per group: cached current average percentage change, or enough numerator/denominator state to derive it in O(1).

Initialize these caches in `__init__()` and make their starting values represent the current pre-open replay state: no member has traded yet, so every group's average percentage change is zero.

Do not remove the existing full-scan formula immediately. Instead, keep a slow reference helper, either by preserving `_group_percentage_chg()` as a scan-based implementation under a new name such as `_group_percentage_chg_slow()` or by introducing a dedicated debug helper with the same formula. This slow helper is needed for parity tests and for safe refactoring of the live fast path.

Add one new fast helper with a stable name such as `_update_group_average_state(symbol: str, new_price: int, delta_trading_value: int) -> None`. This helper should:

1. read the symbol's old percentage change and old cumulative trading value from cached state;
2. compute the symbol's new percentage change from `new_price`;
3. compute the symbol's new cumulative trading value after the current tick;
4. for every group in `self.symbol_to_groups[symbol]`, update the group's cached unweighted and weighted aggregates using only the old symbol contribution and the new symbol contribution;
5. store the symbol's new cached percentage change and cumulative trading value.

For unweighted averages, the update rule is exact and simple. Let `old_pct` be the symbol's prior percentage change and `new_pct` be the new percentage change. For each group, add `new_pct - old_pct` to that group's cached unweighted sum. The current unweighted average is then `group_pct_sum / group_member_count[group]` when the member count is positive.

For weighted averages, preserve the exact formula already in `_group_percentage_chg()`. Let `old_tv` and `new_tv` be the symbol's cumulative trading value before and after the tick. Let `old_pct` and `new_pct` be the symbol's prior and new percentage changes. Update each group's weighted numerator by adding `(new_tv * new_pct) - (old_tv * old_pct)`. The weighted average is then `weighted_numerator / group_trading_value_cumu[group]` when the denominator is positive. This must use the same `group_trading_value_cumu` that the evaluator already maintains today.

Keep the update order behaviorally safe. In the current code, `group_trading_value_cumu[group]` is incremented before `_group_percentage_chg()` runs. The new incremental update helper must preserve the same "after this tick" semantics, so either:

- update `group_trading_value_cumu` first and pass the old symbol trading value into the helper; or
- have the helper own both the group and symbol cumulative-value updates in one place.

Pick one order, record it in the `Decision Log`, and use it consistently.

### Milestone 2: Switch `on_tick()` and `to_snapshot()` to cached averages

At the end of this milestone, the strong-group hot path should no longer rescan all group members to obtain average percentage change.

Still in `src/tw_signal_engine/screening/evaluate_strong_group.py`, refactor `on_tick()` so it updates the cached group-average state once per tick and then reads the current group average from O(1) cached state inside the per-group loop. A practical sequence is:

1. preserve the early return for invalid symbols exactly as it works today;
2. preserve raw-VWAP ranking behavior exactly as it works today;
3. update `trading_value_cumu`, `group_trading_value_cumu`, `price_last`, and `vol_cumu`;
4. call the new incremental average-state helper once;
5. replace `g_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)` with a read from the cached average for that group.

The cached-average read should use a dedicated helper such as `_current_group_avg_pct(group: str) -> float`. That helper must return the same value the old scan-based formula would have returned after the current tick. Keeping this read logic centralized makes later tests and future optimizations easier.

Update `to_snapshot()` in the same file to call `_current_group_avg_pct(group_name)` instead of rescanning members with `_group_percentage_chg()`. This is required both for performance and for consistency between replay decisions and dashboard snapshots.

Do not change any other strong-group behavior in this milestone. In particular:

- do not modify `GroupRank` behavior;
- do not erase groups from `group_rank` when validity fails;
- do not change `last_match_info` update ordering;
- do not combine this with the separate ranking-state optimization work.

If the incremental caches are correct, `on_tick()` and `to_snapshot()` should both be able to stop calling the slow reference helper entirely in production code. The slow helper should remain available for tests.

### Milestone 3: Add exactness tests against the slow formula

At the end of this milestone, the new incremental logic will be guarded by tests that prove it matches the old formula on real evaluator state transitions.

Extend `tests/unit/test_evaluate_strong_group_optimizations.py` so it stops checking only call counts and starts checking numerical parity. Add deterministic tests that build a minimal evaluator fixture and then feed it a sequence of ticks while comparing the incremental result against the slow reference helper after each step.

At minimum, add the following test scenarios:

1. unweighted long mode with one symbol in one group;
2. unweighted long mode with multiple valid members in one group, where each member trades at different times;
3. weighted long mode with multiple members and different cumulative trading values;
4. one symbol that belongs to multiple groups, proving that each affected group cache is updated correctly;
5. short mode, proving the cached average is sign-consistent with existing behavior;
6. `to_snapshot()` parity, proving that `GroupSnapshot.avg_pct_chg` matches the slow reference helper after several ticks.

Use plain floating-point comparisons with a small tolerance, for example `abs(fast - slow) < 1e-12`, rather than string equality. The current implementation uses Python floats already, so exact bit-for-bit identity is not required as long as the numerical value is equivalent for strategy decisions.

Preserve the existing optimization regression tests that assert `_group_percentage_chg()` is not redundantly called and that unnecessary monthly volume queries are still gated. If the helper is renamed, update the tests to target the new public hot-path behavior rather than a no-longer-used internal method name.

Add or extend tests in `tests/unit/test_short_group_screening.py` if needed so the short-side evaluator still behaves identically after the refactor.

### Milestone 4: Validate replay parity and measure the new bottleneck

At the end of this milestone, the contributor will have proof that the optimization is real and behavior-preserving.

Run replay A/B validation on the same machine and input roots used for the current profile. The implementation is accepted only if:

- `report_trades.csv` matches before and after on at least `20260320` and `20260326`;
- `[TIMING] readFileMerged` is lower after the change on `20260326`;
- the top of the `cProfile` output no longer shows `_group_percentage_chg()` as a major cumulative-time consumer.

Do not stop at stage timings alone. Re-run the same `cProfile` shape used during research and record the top functions in this plan, because this optimization is meant to expose the next bottleneck after strong-group average scans are removed.

## Concrete Steps

Run all commands from the repository root:

    cd /home/r12944005/b07401012/Trading/signal

Capture the current baseline replay timing on the existing tree:

    rtk /usr/bin/time -v uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder timing-before-incremental-avg \
      --no-charts

Expected timing shape on the current tree before implementation:

    [TIMING] getTickData OTC: about 4.5 s
    [TIMING] getTickData TSE: about 16.6 s
    [TIMING] readFileMerged: about 32.3 s
    [TIMING] TOTAL: about 57.7 s
    Total ticks processed: 1141712

Capture a current profile before the code change:

    rtk uv run python - <<'PY'
    import cProfile
    from tw_signal_engine.replay.replay_session import run_daily_replay

    prof = cProfile.Profile()
    prof.enable()
    run_daily_replay(
        trade_date="20260326",
        config_path="exec/cfg/parameter.cfg",
        data_dir="/mnt/d/tmp/market-data/tick-data-parquet",
        files_dir="/mnt/d/tmp/market-data/symbols",
        group_file="/mnt/d/tmp/market-data/symbols/group-ver20260408.csv",
        log_folder="timing-profile-before-incremental-avg",
        use_cache=True,
        no_charts=True,
        data_source="parquet",
        write_outputs=False,
    )
    prof.disable()
    prof.dump_stats("/tmp/replay_before_incremental_avg.pstats")
    PY

Inspect the top cumulative functions:

    rtk uv run python - <<'PY'
    import pstats
    stats = pstats.Stats("/tmp/replay_before_incremental_avg.pstats")
    stats.sort_stats("cumtime").print_stats(25)
    PY

Expected pre-change evidence includes lines similar to:

    ... evaluate_strong_group.py:166(on_tick) ... about 59 s cumulative
    ... evaluate_strong_group.py:130(_group_percentage_chg) ... about 27 s cumulative

Implement Milestone 1 and Milestone 2 in:

    src/tw_signal_engine/screening/evaluate_strong_group.py

Update or add tests in:

    tests/unit/test_evaluate_strong_group_optimizations.py
    tests/unit/test_short_group_screening.py

Run focused tests after the evaluator refactor:

    rtk uv run pytest tests/unit/test_evaluate_strong_group_optimizations.py tests/unit/test_short_group_screening.py -q

Run the broader replay-facing tests that touch replay setup and strong-group behavior:

    rtk uv run pytest tests/unit/test_replay_session.py tests/unit/test_day_high_replay.py tests/unit/test_day_high_overnight.py -q

Run repo quality gates:

    rtk uv run ruff check src tests
    rtk uv run mypy src

Run the post-change replay timing:

    rtk /usr/bin/time -v uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260326 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder timing-after-incremental-avg \
      --no-charts

Re-run the profile with the same command shape and compare:

    rtk uv run python - <<'PY'
    import cProfile
    from tw_signal_engine.replay.replay_session import run_daily_replay

    prof = cProfile.Profile()
    prof.enable()
    run_daily_replay(
        trade_date="20260326",
        config_path="exec/cfg/parameter.cfg",
        data_dir="/mnt/d/tmp/market-data/tick-data-parquet",
        files_dir="/mnt/d/tmp/market-data/symbols",
        group_file="/mnt/d/tmp/market-data/symbols/group-ver20260408.csv",
        log_folder="timing-profile-after-incremental-avg",
        use_cache=True,
        no_charts=True,
        data_source="parquet",
        write_outputs=False,
    )
    prof.disable()
    prof.dump_stats("/tmp/replay_after_incremental_avg.pstats")
    PY

    rtk uv run python - <<'PY'
    import pstats
    stats = pstats.Stats("/tmp/replay_after_incremental_avg.pstats")
    stats.sort_stats("cumtime").print_stats(25)
    PY

Run output-parity checks on at least two dates:

    rtk uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260320 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder parity-before-incremental-avg-20260320 \
      --no-charts

    rtk uv run python -m tw_signal_engine.cli.run_daily_replay \
      --date 20260320 \
      --data-source parquet \
      --data-dir /mnt/d/tmp/market-data/tick-data-parquet \
      --files-dir /mnt/d/tmp/market-data/symbols \
      --group-file /mnt/d/tmp/market-data/symbols/group-ver20260408.csv \
      --config exec/cfg/parameter.cfg \
      --log-folder parity-after-incremental-avg-20260320 \
      --no-charts

    rtk diff -u \
      log/parity-before-incremental-avg-20260320/20260320/report_trades.csv \
      log/parity-after-incremental-avg-20260320/20260320/report_trades.csv

Repeat the same parity flow for `20260326`.

## Validation and Acceptance

Acceptance is both behavioral and performance-based.

Behavioral acceptance requires all of the following:

1. the new evaluator tests prove that cached group averages match the slow reference formula in long, short, weighted, and unweighted scenarios;
2. targeted replay-facing tests pass;
3. `report_trades.csv` shows no diff between before and after runs for `20260320` and `20260326`;
4. dashboard snapshot values remain internally consistent, meaning `GroupSnapshot.avg_pct_chg` matches the evaluator's current cached average for the same group after a sequence of ticks.

Performance acceptance requires all of the following:

1. `[TIMING] readFileMerged` on `20260326` is lower than the current baseline of about `32305 ms`;
2. the post-change `cProfile` output no longer shows `_group_percentage_chg()` as a top cumulative hotspot in the replay path;
3. if a new hotspot replaces it, record that hotspot in `Surprises & Discoveries` so the next optimization plan has hard evidence.

The change is not accepted if it merely moves the work into another full-group rescan helper with a different name. The implementation must update group-average state from delta information on each relevant symbol tick.

## Idempotence and Recovery

These edits are source-only and safe to repeat. Running the replay and profiling commands multiple times is expected and should only overwrite the named log folders or `/tmp/*.pstats` files used in this plan.

If parity fails after introducing incremental caches, keep the slow reference helper in place and compare cached values against the slow formula after each synthetic test tick until the first mismatch is isolated. That is the intended recovery path. Do not debug parity only from end-to-end replay output; isolate the first divergent evaluator state in a focused unit test first.

If the weighted-average path is the source of divergence, temporarily gate the new fast path behind `config.is_weighted_avg` while preserving the finished unweighted path, but only as a short-lived debugging step. Before considering the plan complete, either restore the weighted fast path with parity or document a deliberate fallback decision in the `Decision Log` and acceptance notes.

## Artifacts and Notes

Current measured evidence from the repository state on 2026-04-21:

    [TIMING] getTickData OTC: 4561 ms
    [TIMING] getTickData TSE: 16656 ms
    [TIMING] getGroup: 17 ms
    [TIMING] getGroupShort: 15 ms
    tickFilter: 347 symbols
    [TIMING] readFileMerged: 32305 ms
    [TIMING] TOTAL: 57740 ms
    Total ticks processed: 1141712

Current profile evidence from `/tmp/replay_current_20260326_write_outputs_false.pstats`:

    evaluate_strong_group.py:166(on_tick)            59.740 s cumulative
    evaluate_strong_group.py:130(_group_percentage_chg) 27.576 s cumulative
    parquet_replay_provider.py:92(iterate_ticks)     13.570 s cumulative
    group_state.py:29(on_tick)                        4.029 s cumulative
    group_state.py:57(is_top_n)                       2.957 s cumulative

The implementation should leave a similar artifact block here after completion with before/after timing lines and a short profile diff summary.

## Interfaces and Dependencies

Use only the existing project dependencies. Do not add new libraries.

At the end of implementation, `src/tw_signal_engine/screening/evaluate_strong_group.py` should still expose the public class `StrongGroupEvaluator` with the same constructor and the same public methods used elsewhere in the repo:

- `initialize_validity()`
- `on_tick(...)`
- `get_group_limit_up_count(group: str) -> int`
- `to_snapshot(idx_map: dict[str, IndexData]) -> list[GroupSnapshot]`
- `is_single_allowed(symbol: str, max_rank: int) -> bool`

Inside that class, the following internal interface should exist in some stable form:

- one slow, scan-based helper for exactness checks against the old formula;
- one incremental update helper that adjusts cached group-average state from a single symbol tick;
- one O(1) read helper that returns the current average percentage change for a group.

Prefer internal names that reveal purpose over cleverness. Examples that fit the existing code style are:

    _group_percentage_chg_slow(group: str, weighted_avg: bool) -> float
    _update_group_average_state(symbol: str, price: int, delta_trading_value: int) -> None
    _current_group_avg_pct(group: str) -> float

If the final implementation chooses different names, record them here and update the tests and prose accordingly.

Revision note: Created this plan on 2026-04-21 after re-profiling the current `20260326` parquet replay. The reason for this plan is that the completed low-risk-wins plan exposed strong-group average recomputation as the next dominant CPU bottleneck in the real codebase.
