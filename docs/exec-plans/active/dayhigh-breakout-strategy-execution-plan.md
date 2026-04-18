# Day High Breakout Strategy Execution Plan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document follows the repository execution-plan standard in `docs/exec-plans/PLAN.md`. If implementation discovers new facts, update this file first or in the same patch as the code change so that a future contributor can restart from this plan alone.

## Purpose / Big Picture

After this change, the Python replay engine can run a first-class long-only `SignalDayHigh` strategy. The strategy buys Taiwan listed and OTC equities in strong groups when a stock establishes an intraday high, pulls back by at least 1%, and then breaks back above the established high between 09:05:00 and before 10:00:00. It exits with a VWAP-based stop, a 13:20 time exit, or an overnight first-trade exit when a Day High position is locked limit-up at 13:20.

The observable outcome is a DayHigh-only replay configuration that produces `SignalDayHigh` rows in `report_trades.csv`, uses fixed 10,000,000 notional entry sizing, stages no take-profit orders, applies the DayHigh VWAP stop at `entry_vwap * 0.990`, carries locked-limit-up positions across batch replay dates, and taxes overnight exits at the overnight tax rate.

## Progress

- [x] (2026-04-18 18:34 CST) Read `docs/design-docs/dayhigh-strategy-implementation-research.md` and captured user-approved default decisions in this plan.
- [x] (2026-04-18 18:34 CST) Inspected the current config, replay, screening, execution, records, reporting, parser, and batch replay modules that this plan will touch.
- [x] (2026-04-18 19:19 CST) Added `SignalDayHigh` and DayHigh execution config models, INI normalization, DayHigh sample config, and config coverage in `tests/unit/test_config.py`.
- [x] (2026-04-18 19:19 CST) Added `SignalDayHighState` and `evaluate_signal_day_high(...)` with dedicated unit coverage in `tests/unit/test_signal_day_high.py`.
- [x] (2026-04-18 19:19 CST) Made strong-group VWAP upper bound configurable for ranking while preserving legacy 8.5% behavior when unset; added regression coverage in `tests/unit/test_short_group_screening.py`.
- [x] (2026-04-18 19:19 CST) Integrated DayHigh signal flow in replay with continuous state tracking, breakout-time strong-group requirement, deterministic signal priority (`SignalDayHigh` first), and group limit-up entry blocking.
- [x] (2026-04-18 19:19 CST) Added signal-specific execution policy so DayHigh uses ask entry, bid-side exits, no staged take-profit orders, no bailout, and VWAP stop-loss policy (`0.990`).
- [x] (2026-04-18 19:19 CST) Populated limit-up lock state from parsed depth queues and reference-data enrichment; added parser/lock tests.
- [x] (2026-04-18 19:19 CST) Implemented overnight carry transfer and next-day first-trade exits in batch replay via `overnight_holdings`.
- [x] (2026-04-18 19:19 CST) Extended trade records, tax calculation, and trade reports with `IsOvernight` and `ExitTradeDate`, including day-trade vs overnight tax behavior.
- [x] (2026-04-18 19:19 CST) Added focused DayHigh execution/replay/overnight tests and ran required validation commands (with noted external failures for missing golden baselines and local doc-root plan file).

## Surprises & Discoveries

- Observation: The current strong-group evaluator still removes long candidates at a hard-coded 8.5% VWAP change before configurable entry limits are checked.
  Evidence: `src/tw_signal_engine/screening/evaluate_strong_group.py` uses `raw_vwap_pct < 0.085` for raw ranking and erases long ranked members when `vwap_pct >= 0.085`.

- Observation: The replay contract returns only completed trades and force-closes remaining positions at the end of every single-day run.
  Evidence: `src/tw_signal_engine/replay/replay_session.py` returns `list[TradeRecord]`, calls `_finalize_open_positions(...)` after tick iteration, and `src/tw_signal_engine/cli/run_batch_replay.py` creates no cross-day position store today.

- Observation: `MarketTick` already has `is_limit_up_locked`, `total_bid_qty`, and `total_ask_qty`, but the Format6 parser currently fills only the best bid and ask prices from depth rows.
  Evidence: `src/tw_signal_engine/records/market_event_records.py` defines the fields, while `src/tw_signal_engine/market_data/parse_format6_replay_rows.py` only sets `tick.bid[0].price`, `tick.ask[0].price`, and `trade_at` from depth.

- Observation: Take-profit cannot be disabled globally by setting `take_profit_splits=0`.
  Evidence: `validate_execution_split_invariants()` in `src/tw_signal_engine/config/strategy_config.py` rejects `take_profit_splits <= 0`, and `execute_entry()` in `src/tw_signal_engine/execution/create_entry_trade.py` always creates `pos.orders[tick.symbol]` after entry.

- Observation: The full `uv run pytest tests -q` command still fails in this workspace for reasons outside the DayHigh implementation: missing golden parity artifacts and a local root-level `docs/exec-plans/PLAN.md` that violates the docs partition test.
  Evidence: `tests/golden/test_replay_parity.py` reports missing `artifacts/baseline/cpp/.../report_trades.csv`; `tests/unit/test_docs_knowledge_base.py::test_exec_plan_docs_are_partitioned` fails on `docs/exec-plans/PLAN.md`.

## Decision Log

- Decision: Implement the full faithful strategy, including overnight batch carry, lock detection, tax/reporting changes, and tests.
  Rationale: The user accepted defaults after reviewing the implementation-decision questions, and the research document identifies overnight carry and tax treatment as required for strategy correctness rather than optional polish.
  Date/Author: 2026-04-18 / Codex

- Decision: Track DayHigh established-high and pullback state continuously for symbols in the replay universe, then require strong-group eligibility only at the breakout tick.
  Rationale: This preserves a valid high/pullback pattern even when the symbol was not ranked M1 earlier in the day. The strategy requirement is that the entry occurs inside a strong-group setup; it does not require all earlier pattern state to be observed only while already eligible.
  Date/Author: 2026-04-18 / Codex

- Decision: Treat the `9.5%` upper bound as a VWAP screening upper bound only. The final signal price filter requires current trade price to be at least `+6%` from previous close but does not impose a separate `+9.5%` trade-price cap.
  Rationale: The research document describes the upper bound as screening-layer VWAP percent-change. `StrongGroupConfig.entry_max_vwap_pct_chg` is the natural existing field for that behavior, while a trade-price cap would add a stricter rule not clearly required by the draft.
  Date/Author: 2026-04-18 / Codex

- Decision: Use entry-time VWAP as the DayHigh stop-loss anchor.
  Rationale: The existing stop-loss contract passes entry-time `IndexData` into `on_tick_exit()`. Reusing that contract is lower risk and keeps DayHigh consistent with Signal A stop behavior. A rolling-current VWAP stop would require a larger exit API change and different tests.
  Date/Author: 2026-04-18 / Codex

- Decision: Ship and validate DayHigh with a DayHigh-only configuration initially.
  Rationale: DayHigh has distinct exit and overnight semantics. Disabling Signal A, Signal A Short, and Signal B in the DayHigh config avoids ambiguous same-tick priority while the strategy is first introduced. Replay code may still use deterministic priority with DayHigh first once enabled, but acceptance is based on the dedicated config.
  Date/Author: 2026-04-18 / Codex

- Decision: Use signal-specific execution policy rather than global zero take-profit splits.
  Rationale: Existing Signal A and Signal A Short rely on take-profit split invariants. A per-signal policy lets `SignalDayHigh` skip take-profit and bailout without weakening current strategy behavior or config validation.
  Date/Author: 2026-04-18 / Codex

## Outcomes & Retrospective

Shipped:

- DayHigh configuration, state machine, replay integration, execution policy, lock enrichment, overnight carry transfer/exit, and reporting/tax extensions are implemented in the Python engine.
- A DayHigh-only config artifact was added at `exec/cfg/parameter_dayhigh.cfg`.
- Product documentation was added at `docs/product-specs/dayhigh-breakout-strategy-spec.md` and linked from `docs/product-specs/index.md`.

Validation:

- Focused suites pass:
  - `uv run pytest tests/unit/test_config.py tests/unit/test_signal_day_high.py tests/unit/test_short_group_screening.py -q`
  - `uv run pytest tests/unit/test_replay_session.py tests/unit/test_day_high_execution.py tests/unit/test_day_high_replay.py -q`
  - `uv run pytest tests/unit/test_providers.py tests/unit/test_day_high_overnight.py -q`
  - `uv run pytest tests/unit/test_cost_model.py tests/unit/test_report_output.py tests/unit/test_batch_reports.py -q`
- Style/types pass:
  - `uv run ruff check src tests`
  - `uv run mypy src`
- Full `uv run pytest tests -q` currently fails for external repo-workspace reasons noted in `Surprises & Discoveries` (golden baselines absent, root-level plan doc partition test).

## Context and Orientation

The active implementation is the Python replay engine under `src/tw_signal_engine/`. The archived C++ under `legacy/cpp/` is a parity reference only and is not the source of truth for new work.

The replay engine reads legacy INI config files, loads symbol reference data and group membership, builds a candidate replay universe, merges market ticks, updates per-symbol index values, runs exit checks, evaluates screening, evaluates signals, executes entries, and writes CSV reports. Prices in market ticks are integer values scaled by 10,000, so a displayed price of 50.25 is represented as `502500`.

Important terms for this plan:

DayHigh or `SignalDayHigh` means the new long-only signal family described here. It is separate from `SignalA`, `SignalAShort`, and `SignalB`.

Established high means the highest trade price observed before a confirmed pullback. Because `IndexCalc.calc()` updates `idx.day_high` before signal evaluation on each tick, DayHigh must keep its own `established_high` instead of relying on `idx.day_high` on the breakout tick.

Pullback means the current trade price falls to or below `established_high * (1 - pullback_ratio)`. The initial `pullback_ratio` is `0.01`, meaning 1%.

Breakout means that after a pullback is confirmed, the current trade price becomes greater than the stored `established_high`.

Replay universe means the set of symbols whose ticks are read during replay. It is built from valid strong-group symbols, valid strong-single symbols, and `0050` for the market gate. DayHigh state should be tracked for symbols that pass through this universe and are not ETF symbols skipped by the replay loop.

Strong group means the existing screening subsystem in `src/tw_signal_engine/screening/evaluate_strong_group.py`. For DayHigh, the symbol must be in a top `G1-G10` group, be the top member by VWAP percent-change rank, be raw rank 1 when `require_raw_m1=true`, and pass liquidity, momentum, value-ratio, disposition, and VWAP upper-bound filters.

Locked limit-up means a stock is trading at its reference limit-up price and the depth indicates no sell-side ask queue while a bid queue exists. The weaker fallback of price at limit-up alone is not sufficient for overnight carry unless depth information is unavailable and the behavior is explicitly documented by tests.

Overnight holding means a DayHigh position that is intentionally removed from same-day `PositionState` at 13:20 because it is locked limit-up, stored in a batch-level mapping, included in the next day's tick filter, and closed on the first next-day trade.

Key current code paths:

- `src/tw_signal_engine/config/strategy_config.py` defines typed Pydantic config models such as `SignalAConfig`, `StrongGroupConfig`, `ExecutionConfig`, and `NormalizedStrategyConfig`.
- `src/tw_signal_engine/config/normalize_strategy_config.py` converts legacy INI sections into `NormalizedStrategyConfig`.
- `src/tw_signal_engine/state/signal_state.py` stores mutable per-symbol signal state.
- `src/tw_signal_engine/signals/evaluate_signal_a.py`, `src/tw_signal_engine/signals/evaluate_signal_a_short.py`, and `src/tw_signal_engine/signals/evaluate_signal_b.py` are the existing signal evaluators.
- `src/tw_signal_engine/replay/replay_session.py` owns `run_daily_replay()`, `_finalize_open_positions()`, and the main tick loop.
- `src/tw_signal_engine/screening/evaluate_strong_group.py` owns strong-group ranking and match information, including `get_group_limit_up_count(group)`.
- `src/tw_signal_engine/execution/create_entry_trade.py` owns `should_enter()` and `execute_entry()`.
- `src/tw_signal_engine/execution/trade_ledger.py` owns `on_tick_exit()` and completed trade creation.
- `src/tw_signal_engine/execution/apply_stop_loss_exit.py`, `src/tw_signal_engine/execution/apply_time_exit.py`, `src/tw_signal_engine/execution/apply_take_profit_plan.py`, and `src/tw_signal_engine/execution/apply_bailout_exit.py` implement exit rules.
- `src/tw_signal_engine/records/market_event_records.py` defines `MarketTick` and `TradeRecord`.
- `src/tw_signal_engine/records/trade_records.py` defines `EntryTrade`.
- `src/tw_signal_engine/market_data/parse_format6_replay_rows.py` parses replay trade/depth lines.
- `src/tw_signal_engine/cli/run_batch_replay.py` loops over dates and currently accumulates only completed same-day trades.
- `src/tw_signal_engine/reporting/build_trade_report_rows.py` writes `report_trades.csv`.

## Plan of Work

Milestone 1 adds configuration and state. In `src/tw_signal_engine/config/strategy_config.py`, define `SignalDayHighConfig` with defaults `enabled=False`, `entry_start_time=90500000000`, `entry_end_time=100000000000`, `min_increase_ratio=0.06`, `max_increase_ratio=0.095`, `pullback_ratio=0.01`, `max_entries_per_symbol=1`, and `max_group_limit_up_count=2`. Add `signal_day_high: SignalDayHighConfig` to `NormalizedStrategyConfig`. In `ExecutionConfig`, add `stop_loss_ratio_day_high=0.990`, `stop_loss_mode_day_high="vwap"`, `hold_overnight_on_limit_up=False`, `day_trade_tax_rate=0.0`, and `overnight_tax_rate=0.0`. Preserve `tax_rate` compatibility by normalizing omitted day/overnight fields to `tax_rate` when `tax_rate` is set and the new field is omitted. Do not allow zero take-profit splits globally; DayHigh disables take-profit through execution policy. In `normalize_strategy_config.py`, parse `[SignalDayHigh]` and the new `[Order]` fields. Add config tests in `tests/unit/test_config.py`.

Milestone 2 adds DayHigh signal state and evaluator. In `src/tw_signal_engine/state/signal_state.py`, add a dataclass named `SignalDayHighState` with fields `symbol`, `triggered`, `established_high`, `established_high_time`, `pullback_confirmed`, `pullback_low`, `pullback_time`, and `entries`. Create `src/tw_signal_engine/signals/evaluate_signal_day_high.py`. The evaluator should return `(triggered: bool, trigger_match_type: str)`. It must always update price-pattern state for replay-universe symbols with valid trade prices, but it may only trigger when `match_type != "None"`, time is within `[entry_start_time, entry_end_time)`, previous close is positive, the current trade price is at least `+6%` from previous close, and `state.triggered` is false. It must not apply a current-price `+9.5%` cap because the accepted decision puts the upper bound in VWAP screening. Add `tests/unit/test_signal_day_high.py` for initial high tracking, new-high reset before pullback, pullback confirmation, lower pullback low updates, breakout trigger, entry window, min-increase filter, no trigger on `match_type="None"`, and single-fire behavior.

The intended evaluator signature is:

    def evaluate_signal_day_high(
        state: SignalDayHighState,
        config: SignalDayHighConfig,
        price: int,
        match_time_str: int,
        match_time_us: int,
        match_type: str,
        ref: ReferenceSymbol | None,
    ) -> tuple[bool, str]:
        ...

Milestone 3 fixes strong-group compatibility for the `9.5%` VWAP upper bound. In `src/tw_signal_engine/screening/evaluate_strong_group.py`, replace the hard-coded long `0.085` rank exclusion with a helper that returns `config.entry_max_vwap_pct_chg` when it is positive and otherwise returns `0.085`. For short mode, mirror this behavior with the negative bound. Use that helper in both raw VWAP ranking and member VWAP ranking erasure. Preserve existing behavior when `entry_max_vwap_pct_chg` is left at `0.0`. Add focused tests proving that with `entry_max_vwap_pct_chg=0.095`, a long symbol between `8.5%` and `9.5%` remains ranked and can qualify if other DayHigh strong-group conditions pass. Also add a regression test that default config still excludes the same symbol at the legacy 8.5% bound.

Milestone 4 integrates DayHigh into the replay loop. In `src/tw_signal_engine/replay/replay_session.py`, import `SignalDayHighState` and `evaluate_signal_day_high`, print `signalDayHigh_enabled` with the other switches, allocate `signal_day_high_map: dict[str, SignalDayHighState] = {}`, and evaluate DayHigh after strong-group screening. DayHigh should use `long_match_type`, should not run in compatibility short mode, and should be evaluated even when the current symbol is not strongly qualified so that high/pullback state remains continuous. On a trigger, select `selected_signal_type="SignalDayHigh"`, `selected_trade_mode="long"`, and the normal long `strong_group` evaluator. When several signals are enabled anyway, deterministic priority should be `SignalDayHigh`, then `SignalA`, then `SignalAShort`, then `SignalB`; however, the DayHigh acceptance config disables the other entry signals. Before `should_enter()` and `execute_entry()`, block DayHigh if `strong_group.get_group_limit_up_count(group_name) >= config.signal_day_high.max_group_limit_up_count`, recording a funnel block reason such as `day_high_group_limit_up_count`. Add replay-session tests with an injected provider that prove DayHigh can track the pattern before strong-group eligibility, triggers only when the breakout tick is strong-group eligible, and is blocked by group limit-up count.

Milestone 5 adds signal-specific execution policy. Create a small helper module such as `src/tw_signal_engine/execution/signal_policy.py` with a frozen dataclass `ExecutionPolicy` containing `enable_take_profit`, `enable_bailout`, and `hold_overnight_on_limit_up`. Provide a function such as `policy_for_signal(signal_type: str, config: ExecutionConfig) -> ExecutionPolicy` that returns disabled take-profit and bailout for `SignalDayHigh`, and existing behavior for current signals. In `execute_entry()`, skip take-profit order creation when `enable_take_profit` is false, set `pos.orders[tick.symbol] = []`, `pos.reserve_stocks[tick.symbol] = 0`, and `pos.limit_up_prices[tick.symbol]` to the symbol's limit-up int for later lock reference. Preserve ask-side long entry pricing. In `apply_stop_loss_exit.py`, add `SignalDayHigh` to `_STOP_LOSS_POLICY_MAP` with `ratio_attr="stop_loss_ratio_day_high"` and `anchor_attr="vwap"`. In `trade_ledger.py`, skip take-profit and bailout checks when policy disables them. Add unit tests in `tests/unit/test_day_high_execution.py` for ask entry, fixed notional sizing, no staged orders, VWAP stop at `entry_vwap * 0.990`, bid-side time exit, and explicit bailout suppression.

The intended helper shape is:

    @dataclass(frozen=True)
    class ExecutionPolicy:
        enable_take_profit: bool = True
        enable_bailout: bool = True
        hold_overnight_on_limit_up: bool = False

    def policy_for_signal(signal_type: str, config: ExecutionConfig) -> ExecutionPolicy:
        if signal_type == "SignalDayHigh":
            return ExecutionPolicy(
                enable_take_profit=False,
                enable_bailout=False,
                hold_overnight_on_limit_up=config.hold_overnight_on_limit_up,
            )
        return ExecutionPolicy()

Milestone 6 enriches limit-up lock detection. Add parser support in `src/tw_signal_engine/market_data/parse_format6_replay_rows.py` to parse bid and ask counts and total quantities from depth lines when available, filling `MarketTick.total_bid_qty` and `MarketTick.total_ask_qty`. If parsing all depth levels is too invasive, at minimum parse the depth count after `BID:` and `ASK:` and set totals from available first-level quantities; document the limitation in tests. In `replay_session.py`, after reference data is available and before exit logic uses lock status, enrich each tick by computing the reference limit-up int and setting `tick.is_limit_up_locked = True` only when `tick.match.price >= limit_up_int`, `tick.ask[0].price <= 0`, and either `tick.bid[0].price > 0` or `tick.total_bid_qty > 0`. Do not use price-at-limit-up alone as the normal lock definition. Add parser/enrichment tests that cover locked limit-up, price-at-limit-up with an ask still present, and non-limit-up trades.

Milestone 7 implements overnight carry. Add a new dataclass in a suitable module, preferably `src/tw_signal_engine/records/overnight_records.py`, named `OvernightHolding`. It should contain the `EntryTrade`, quantity, entry `IndexData`, entry signal type, carry-from date, and limit-up price. Thread an optional `overnight_holdings: dict[str, OvernightHolding] | None = None` parameter through `run_daily_replay()`. When omitted, standalone daily replay keeps current force-close behavior and should warn or report that overnight carry requires a provided mapping. In batch replay, create one mapping before the date loop and pass it into every `run_daily_replay()` call. Include overnight symbols in the tick filter even if they are not today's strong-group candidates. At the start of normal per-tick processing, if the tick's symbol is in `overnight_holdings`, close it on that first trade at long-side bid fallback match, create a `TradeRecord` with `final_leave_cause="overnightExit"`, `trade_date` equal to the entry date or carry-from date, `exit_trade_date` equal to the current replay date, and `is_overnight=True`, then remove the holding from the map and continue with normal logic only if no position remains. At `exit_time_limit`, for `SignalDayHigh` positions only, if policy says to hold overnight and the tick is locked limit-up, remove the open trade and related position state from `PositionState`, store an `OvernightHolding`, and do not append a completed trade that day. At finalization, do not force-close holdings that were intentionally moved to `overnight_holdings`. Add tests in `tests/unit/test_day_high_overnight.py` for hold transfer at 13:20, no duplicate close after transfer, inclusion of overnight symbols in the next day's tick filter, next-day first-tick exit, and behavior when standalone daily replay has no carry map.

The intended overnight record shape is:

    @dataclass(slots=True)
    class OvernightHolding:
        entry_trade: EntryTrade
        qty: float
        entry_idx: IndexData
        entry_signal_type: str
        carry_from_date: str
        limit_up_price: int

Milestone 8 updates cost model and reporting. In `src/tw_signal_engine/records/market_event_records.py`, add `is_overnight: bool = False` and `exit_trade_date: str = ""` to `TradeRecord`. If DayHigh-specific signal path fields are available at entry, also add `established_high_at_entry`, `pullback_low_at_entry`, and `pullback_depth_pct`; otherwise defer those fields until the signal evaluator exposes them cleanly. In `trade_ledger.py`, calculate tax with `overnight_tax_rate` when `TradeRecord.is_overnight` is true or the leave cause is `overnightExit`; otherwise use `day_trade_tax_rate` when set, falling back to `tax_rate`. Preserve existing `tax_rate` behavior for older configs. In `src/tw_signal_engine/reporting/build_trade_report_rows.py`, add columns `IsOvernight` and `ExitTradeDate` near `TradeDate`. Batch-level reports should continue to group by entry `trade_date` unless this plan later records a decision to group by exit date. Add tests in `tests/unit/test_cost_model.py` and `tests/unit/test_report_output.py` for day-trade tax, overnight tax, `ExitTradeDate`, and backwards-compatible `tax_rate`.

Milestone 9 adds the DayHigh config and documentation hooks. Add a DayHigh-only config file or update the project sample config in the location used by this repository, preserving existing default behavior when DayHigh is disabled. The DayHigh config must set `[SignalA] enabled=false`, `[SignalAShort] enabled=false`, `[SignalB] enabled=false`, `[SignalDayHigh] enabled=true`, `[StrongGroup] group_valid_top_n=10`, `[StrongGroup] top_group_max_select=1`, `[StrongGroup] normal_group_max_select=1`, `[StrongGroup] require_raw_m1=true`, `[StrongGroup] entry_max_vwap_pct_chg=0.095`, `[StrongGroup] block_disposition_entry=true`, `[Order] position_cash=10000000`, `[Order] position_scale_nth=1.0`, `[Order] stop_loss_ratio_day_high=0.990`, `[Order] hold_overnight_on_limit_up=true`, `[Order] exit_time_limit=132000000000`, `[Order] day_trade_tax_rate=0.0015`, and `[Order] overnight_tax_rate=0.003`. Update product docs only after the behavior is implemented and verified. The active behavior should be documented in a product spec under `docs/product-specs/` rather than only in this execution plan.

Milestone 10 validates end to end. Run the focused tests after each milestone and the full validation suite at the end. A full batch replay with real data is data-dependent, so the minimum deterministic acceptance is unit and synthetic-provider replay coverage. If local data is available, run a small batch replay with the DayHigh config over two adjacent trading dates and verify that an overnight holding created on the first date exits on the first trade of the second date.

## Concrete Steps

Work from the repository root:

    cd /home/r12944005/b07401012/Trading/signal-dayhigh-breakthrough-strategy

Before editing, check the worktree to avoid overwriting unrelated user changes:

    git status --short

Add config and state first, then run:

    uv run pytest tests/unit/test_config.py tests/unit/test_signal_day_high.py -q

After strong-group compatibility changes, run the focused screening tests:

    uv run pytest tests/unit/test_group_state.py -q

If the strong-group tests live in a different file after implementation, replace `tests/unit/test_group_state.py` with the file that contains the new `entry_max_vwap_pct_chg=0.095` coverage.

After replay integration and execution policy changes, run:

    uv run pytest tests/unit/test_replay_session.py tests/unit/test_day_high_execution.py -q

After limit-up lock detection and overnight carry changes, run:

    uv run pytest tests/unit/test_providers.py tests/unit/test_day_high_overnight.py -q

After cost and reporting changes, run:

    uv run pytest tests/unit/test_cost_model.py tests/unit/test_report_output.py tests/unit/test_batch_reports.py -q

At the end, run the project validation commands:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

Expected success is zero failing tests, no ruff violations, and no mypy errors. If golden parity tests fail only because baseline artifacts are missing, record the exact failure in `Surprises & Discoveries` and run the relevant non-golden unit suite to prove the DayHigh behavior.

## Validation and Acceptance

The implementation is accepted when all of the following are true.

A config containing `[SignalDayHigh] enabled=true` and disabled Signal A, Signal A Short, and Signal B normalizes successfully. Printing the startup switches from `run_daily_replay()` includes `signalDayHigh_enabled: [True]`.

The new signal evaluator can be exercised by tests with a sequence of prices that establishes a high, pulls back by at least 1%, and breaks above the established high. It does not trigger before 09:05:00, at or after 10:00:00, below the `+6%` current-price threshold, with `match_type="None"` on the breakout tick, or more than once for the same symbol in one day.

Strong-group screening with `entry_max_vwap_pct_chg=0.095` allows a symbol whose VWAP percent-change is above 8.5% and below 9.5% to remain in rank consideration, while default config still preserves the previous 8.5% exclusion.

A synthetic replay test shows DayHigh state being tracked before strong-group eligibility, a breakout tick becoming eligible as `StrongGroup`, and a resulting `EntryTrade` with `signal_type="SignalDayHigh"`, `side="long"`, fixed notional sizing from `position_cash=10000000`, and no take-profit orders staged.

A DayHigh stop-loss test shows the position closes when current price is less than or equal to `entry_vwap * 0.990`, using bid fallback match pricing for the long exit. A DayHigh time-exit test shows normal 13:20 exits use bid fallback match pricing.

A group limit-up test shows DayHigh entry is blocked when the selected group already has at least two limit-up members and records the block reason.

A lock detection test shows `is_limit_up_locked=True` only when the tick is at limit-up and the depth indicates no ask queue with a bid queue present. A tick at limit-up with ask liquidity must not be treated as locked.

A batch overnight test shows a locked-limit-up DayHigh position at 13:20 is not recorded as a same-day completed trade, remains in `overnight_holdings`, is included in the next day's tick filter, exits on the first next-day trade with `final_leave_cause="overnightExit"`, and uses `overnight_tax_rate=0.003`.

`report_trades.csv` includes `SignalDayHigh` rows for completed trades, `IsOvernight`, and `ExitTradeDate`. For non-overnight DayHigh trades, `IsOvernight` is false and `ExitTradeDate` is either empty or the same as the trade date, according to the final reporting decision recorded in this plan.

The full validation suite passes:

    uv run pytest tests -q
    uv run ruff check src tests
    uv run mypy src

## Idempotence and Recovery

All steps are additive and can be repeated safely. Running normalization and unit tests multiple times should not mutate data outside generated logs and caches.

Do not run destructive git commands such as `git reset --hard` or `git checkout --` to recover from failures. If a patch creates failing tests, inspect the failing files and make a forward fix. If unrelated user changes exist in the worktree, leave them in place and avoid rewriting those files unless this plan explicitly requires them.

Generated replay logs under `log/` are disposable. If a test or manual replay writes logs, remove only logs you created and only if cleanup is needed for clarity. Do not delete data, files, or reference directories.

If the overnight carry implementation gets stuck because changing `run_daily_replay()` return type would touch too many call sites, use the accepted lower-impact API: keep returning `list[TradeRecord]` and add the optional mutable `overnight_holdings` parameter. Batch replay passes the mapping; single-day replay without the mapping keeps legacy force-close behavior.

If Format6 depth rows do not contain reliable total queue fields, implement best-effort depth-count parsing and document the limitation in `Surprises & Discoveries`. Do not silently fall back to price-at-limit-up-only lock detection for overnight carry without recording that behavior and adding a test that makes the limitation visible.

## Artifacts and Notes

The accepted initial DayHigh config shape is:

    [Strategy]
    trade_mode=long

    [SignalA]
    enabled=false

    [SignalAShort]
    enabled=false

    [SignalB]
    enabled=false

    [SignalDayHigh]
    enabled=true
    entry_start_time=90500000000
    entry_end_time=100000000000
    min_increase_ratio=0.06
    max_increase_ratio=0.095
    pullback_ratio=0.01
    max_entries_per_symbol=1
    max_group_limit_up_count=2

    [StrongGroup]
    enabled=true
    member_min_month_trading_val=200000000
    group_min_month_trading_val=3000000000
    group_min_avg_pct_chg=0.01
    group_min_val_ratio=1
    group_valid_top_n=10
    top_group_max_select=1
    normal_group_max_select=1
    require_raw_m1=true
    entry_max_vwap_pct_chg=0.095
    block_disposition_entry=true
    exclude_disposition_from_rank=true

    [StrongSignal]
    enabled=false

    [Order]
    position_cash=10000000
    position_scale_nth=1.0
    stop_loss_ratio_day_high=0.990
    stop_loss_mode_day_high=vwap
    hold_overnight_on_limit_up=true
    exit_time_limit=132000000000
    commission_rate=0.000171
    day_trade_tax_rate=0.0015
    overnight_tax_rate=0.003
    slippage_bps=5

Keep the existing `tax_rate` override compatible. If a user passes `--cost-model tax=0.0015`, it should continue to set the effective tax for day trades and, unless more specific overnight config is present, should be used as the default for overnight tax too.

## Interfaces and Dependencies

Add this config model in `src/tw_signal_engine/config/strategy_config.py`:

    class SignalDayHighConfig(BaseModel):
        enabled: bool = False
        entry_start_time: int = 90500000000
        entry_end_time: int = 100000000000
        min_increase_ratio: float = 0.06
        max_increase_ratio: float = 0.095
        pullback_ratio: float = 0.01
        max_entries_per_symbol: int = 1
        max_group_limit_up_count: int = 2

Extend `ExecutionConfig` with:

    stop_loss_ratio_day_high: float = 0.990
    stop_loss_mode_day_high: Literal["vwap"] = "vwap"
    hold_overnight_on_limit_up: bool = False
    day_trade_tax_rate: float = 0.0
    overnight_tax_rate: float = 0.0

Add this state model in `src/tw_signal_engine/state/signal_state.py`:

    @dataclass
    class SignalDayHighState:
        symbol: str = ""
        triggered: bool = False
        established_high: int = 0
        established_high_time: int = 0
        pullback_confirmed: bool = False
        pullback_low: int = 0
        pullback_time: int = 0
        entries: int = 0

Create `src/tw_signal_engine/signals/evaluate_signal_day_high.py` with:

    def evaluate_signal_day_high(
        state: SignalDayHighState,
        config: SignalDayHighConfig,
        price: int,
        match_time_str: int,
        match_time_us: int,
        match_type: str,
        ref: ReferenceSymbol | None,
    ) -> tuple[bool, str]:
        ...

Create `src/tw_signal_engine/execution/signal_policy.py` with:

    @dataclass(frozen=True)
    class ExecutionPolicy:
        enable_take_profit: bool = True
        enable_bailout: bool = True
        hold_overnight_on_limit_up: bool = False

    def policy_for_signal(signal_type: str, config: ExecutionConfig) -> ExecutionPolicy:
        ...

Add an overnight record, preferably in `src/tw_signal_engine/records/overnight_records.py`:

    @dataclass(slots=True)
    class OvernightHolding:
        entry_trade: EntryTrade
        qty: float
        entry_idx: IndexData
        entry_signal_type: str
        carry_from_date: str
        limit_up_price: int

Extend `run_daily_replay()` in `src/tw_signal_engine/replay/replay_session.py` without breaking existing callers:

    def run_daily_replay(
        ...,
        provider: MarketDataProvider | None = None,
        hooks: SessionHooks | None = None,
        on_dashboard_snapshot: Callable[[DashboardSnapshot], None] | None = None,
        overnight_holdings: dict[str, OvernightHolding] | None = None,
    ) -> list[TradeRecord]:
        ...

Do not add new third-party dependencies for this plan. Use the current Python standard library, Pydantic already used by config, dataclasses already used by records/state, and the existing pytest/ruff/mypy validation toolchain.

## Revision Notes

- 2026-04-18 / Codex: Created the initial self-contained execution plan from `docs/design-docs/dayhigh-strategy-implementation-research.md` and the user's accepted default decisions. No code implementation has started yet.
