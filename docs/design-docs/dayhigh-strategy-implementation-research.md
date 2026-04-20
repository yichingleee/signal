# Day High Breakout Implementation Research

## Purpose

This note evaluates how to implement the draft Day High Breakout strategy from
`docs/references/legacy/strategy-drafts/dayhigh-strategy-spec-draft.md` in the current Python replay
engine under `src/tw_signal_engine/`.

The strategy is compatible with the repository's current architecture, but it is
not config-only. The existing engine already has most of the shared replay,
strong-group, entry-fill, sizing, cost, and reporting infrastructure. The missing
parts are a dedicated day-high signal state machine, signal-specific execution
policy, overnight carry state across batch days, and a few screening/market-data
corrections.

## Strategy Requirements From The Draft

Day High Breakout is a long-only intraday momentum strategy:

- Universe: Taiwan listed plus OTC equities, excluding `00xx` ETFs and disposition stocks.
- Screening: only strong groups, top group rank `G1-G10`, group liquidity, group momentum, group value ratio, and group member rank `M1`.
- Candidate: group member with VWAP percent-change rank 1, and raw rank 1.
- Signal: after an established intraday high, wait for a pullback of at least `1%`, then enter when price breaks above that established high.
- Entry window: `09:05:00` through before `10:00:00`.
- Entry price: long-side best ask, fallback to match price.
- Entry size: fixed `10,000,000` notional per trade, no scale-down by nth entry.
- Entry level: price increase from previous close must be at least `6%`.
- Upper bound: screening-level VWAP percent-change upper bound around `9.5%`.
- Group limit-up filter: do not enter when the group already has `2+` limit-up members.
- Per-symbol firing: at most once per symbol per day.
- Stop-loss: VWAP stop at `entry_vwap * 0.990`, long exit at bid fallback match.
- Time exit: exit at `13:20:00` at bid fallback match.
- Overnight: if `13:20` sees a locked limit-up DayHigh position, do not close; sell the next replay day on the first trade.
- Take profit, trailing stop, and bailout are disabled for this strategy.
- Cost: commission, tax, and slippage must support day-trade and overnight tax differences.

## Current Runtime Fit

The current replay loop in `src/tw_signal_engine/replay/replay_session.py` is a
good fit for adding this strategy because it already follows this per-tick order:

1. Load config, references, group membership, and 20-day history.
2. Build `StrongGroupEvaluator` and optional strong-single evaluator.
3. Build replay universe from valid screening candidates plus `0050`.
4. Merge OTC/TSE ticks in `match_time_str` order.
5. Update `IndexCalc` for VWAP, day high, and day low.
6. Process exits before entries.
7. Evaluate screening.
8. Evaluate signals.
9. Apply entry filters.
10. Execute entry and write order logs.
11. Force close remaining positions at end of day.

This ordering is compatible with DayHigh's semantics with two caveats:

- DayHigh tracking must update even before the final breakout tick; relying only on the existing Signal A pattern of resetting when `match_type == "None"` may lose relevant day-high context.
- End-of-day force-close currently closes everything; DayHigh locked-limit-up holdings need to survive into the next batch replay day.

## Compatibility Matrix

| Requirement | Current Support | Gap |
|---|---:|---|
| TSE/OTC quote replay | Yes | None for current raw files. |
| Exclude `00xx` ETF entries | Mostly | Replay loop skips `00xx` after market-gate handling; `0050` remains available for market gate. |
| Reference previous close and limit-up price | Yes | Already in `ReferenceSymbol`. |
| Disposition stock metadata | Partial | `StrongGroupEvaluator` checks `ref.security == "RR"`; `should_enter()` uses `disposition_stocks_enabled` for early-trade `volatility_pause`, not disposition metadata. |
| Strong-group liquidity and momentum | Yes | Parameters exist. |
| Top `G1-G10` groups | Yes | Use `group_valid_top_n=10`; current config uses `20`. |
| VWAP rank `M1` and raw `M1` | Yes | Existing `top_group_max_select=1`, `normal_group_max_select=1`, and `require_raw_m1=true` cover this. |
| VWAP upper bound `9.5%` | No, not config-only | Strong group has hard-coded `8.5%` rank exclusions before the configurable entry max. |
| Entry level `price >= prev_close * 1.06` | Partial | Signal A checks a max extension only; DayHigh needs a separate min price increase filter. |
| Day-high pullback-breakout signal | No | Needs new state and evaluator. |
| Single-fire per symbol per day | Yes pattern | Existing signal states use `triggered`; DayHigh should do the same. |
| Ask entry / bid exit | Yes | `execute_entry()` long path uses ask fallback match; exit helpers use bid fallback match. |
| Fixed 10M sizing | Yes | `ExecutionConfig.position_cash` and `position_scale_nth=1.0`. |
| No duplicate holding | Yes | `should_enter()` checks `already_holding`. |
| Group limit-up count `< 2` | Partial | `get_group_limit_up_count()` exists but is currently reporting-only. Need a pre-entry block. |
| VWAP stop at `0.990` | Partial | Stop-loss policy can map DayHigh to VWAP, but needs a config ratio separate from Signal A or an explicit signal family mapping. |
| Take profit disabled | No, not cleanly | Existing split validation assumes at least one take-profit split and `execute_entry()` always stages orders. |
| Bailout disabled | Partial | Existing bailout only fires after profit-taking; if TP disabled it is effectively off, but should be explicit. |
| Time exit at `13:20` | Yes | Existing `exit_time_limit` supports `13:20`. |
| Locked limit-up hold overnight | No | Existing `lockedLimitUp` path closes reserve shares at limit-up; it does not carry positions into the next day. |
| Next-day first-trade exit | No | Batch replay currently creates a fresh `PositionState` per date and only accumulates completed trades. |
| Overnight tax `0.3%` vs day tax `0.15%` | No | Current cost model has a single `tax_rate`. |
| File replay limit-up lock detection | Weak | `MarketTick.is_limit_up_locked` exists but the file parser does not populate it. |
| Basic CSV reports | Mostly | Generic `TradeRecord.signal_type` will carry `SignalDayHigh`, but specialized columns may be needed. |
| Dashboard visibility | Partial | Existing dashboard Signal A monitor filters to `SignalA` and `SignalAShort`; DayHigh would not appear in that page without UI changes. |

## Existing Modules To Reuse

### Config

Relevant files:

- `src/tw_signal_engine/config/strategy_config.py`
- `src/tw_signal_engine/config/normalize_strategy_config.py`
- `cfg/parameter.cfg`

The repo already normalizes legacy INI sections into typed Pydantic models. Add a
new `SignalDayHighConfig` model and a `signal_day_high` field on
`NormalizedStrategyConfig`.

Recommended config model:

```python
class SignalDayHighConfig(BaseModel):
    enabled: bool = False
    entry_start_time: int = 90500000000
    entry_end_time: int = 100000000000
    min_increase_ratio: float = 0.06
    max_increase_ratio: float = 0.095
    pullback_ratio: float = 0.01
    max_entries_per_symbol: int = 1
    max_group_limit_up_count: int = 2
```

Execution config also needs either signal-specific fields or policy fields:

```python
stop_loss_ratio_day_high: float = 0.990
stop_loss_mode_day_high: Literal["vwap"] = "vwap"
hold_overnight_on_limit_up: bool = False
day_trade_tax_rate: float = 0.0015
overnight_tax_rate: float = 0.003
```

Current `ExecutionConfig.tax_rate` is still useful as a backwards-compatible
single-rate default. If `day_trade_tax_rate` is omitted, it can default to
`tax_rate`.

### Screening

Relevant file:

- `src/tw_signal_engine/screening/evaluate_strong_group.py`

Reusable behavior:

- Monthly member trading-value floor.
- Monthly group trading-value floor.
- Group average percent-change threshold.
- Group current-value ratio threshold.
- Group rank via `GroupRank`.
- Member VWAP rank.
- Raw member VWAP rank.
- `require_raw_m1`.
- `block_disposition_entry` using `ReferenceSymbol.security == "RR"`.
- `get_group_limit_up_count(group)`.

Important incompatibility:

`StrongGroupEvaluator.on_tick()` has hard-coded `0.085` bounds in two places:

- raw rank update allows long raw ranking only when `raw_vwap_pct < 0.085`
- member rank erases long symbols when `vwap_pct >= 0.085`

The DayHigh draft's config reference says `max_increase_ratio=0.095` and describes
the upper bound as a screening-layer VWAP upper limit. With the current code,
setting `entry_max_vwap_pct_chg=0.095` is not enough because the symbol is removed
from the ranking before the configurable entry max is evaluated.

Recommended fix:

- Replace the hard-coded `0.085` long-side rank bound with a config-derived rank bound.
- For long mode, use `config.entry_max_vwap_pct_chg` when it is positive, otherwise preserve `0.085` for backwards compatibility.
- For short mode, mirror the same behavior with negative bounds.
- Add focused tests proving that a symbol with VWAP change between `8.5%` and `9.5%` can remain ranked when configured for DayHigh.

The draft's `GLU < 2` filter should not be embedded in the generic strong-group
ranker unless it is meant to affect all strategies. Prefer keeping it in
DayHigh-specific entry blocking, using `get_group_limit_up_count()` and the
selected group's `MatchInfo`.

### Symbol State

Relevant files:

- `src/tw_signal_engine/state/symbol_state.py`
- `src/tw_signal_engine/state/signal_state.py`

`IndexCalc` already calculates VWAP and day high. VWAP is reusable for stop-loss
and reporting.

Do not implement DayHigh breakout by reading only `idx.day_high` on the breakout
tick. `IndexCalc.calc()` runs before signals, so on a new high tick `idx.day_high`
already equals the current price. DayHigh needs its own `established_high` state
that represents the high before a confirmed pullback.

Recommended state:

```python
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
```

The `entries` field can be omitted if `triggered` is enough. Keep it if
`max_entries_per_symbol` may later become greater than 1.

### Signal Evaluation

Relevant existing signal files:

- `src/tw_signal_engine/signals/evaluate_signal_a.py`
- `src/tw_signal_engine/signals/evaluate_signal_a_short.py`
- `src/tw_signal_engine/signals/evaluate_signal_b.py`

Recommended new file:

- `src/tw_signal_engine/signals/evaluate_signal_day_high.py`

Recommended evaluator behavior:

1. Return false if disabled or `state.triggered` is true.
2. Keep tracking `established_high` from trade prices for replay-universe symbols.
3. If no `established_high`, initialize it to the current price and return false.
4. If pullback is not confirmed:
   - if `price > established_high`, update `established_high` and reset pullback fields.
   - if `price <= established_high * (1 - pullback_ratio)`, set `pullback_confirmed` and `pullback_low`.
   - return false.
5. If pullback is confirmed:
   - update `pullback_low` on lower prices.
   - if `price > established_high`, evaluate final entry filters.
6. Final signal-level filters should include:
   - `match_type != "None"`
   - `entry_start_time <= match_time_str < entry_end_time`
   - `prev_close > 0`
   - `(price - prev_close) / prev_close >= min_increase_ratio`
   - `(price - prev_close) / prev_close < max_increase_ratio` if the max is intended to apply to price as well as VWAP
7. On trigger, set `state.triggered = True`, increment `entries`, and return `(True, match_type)`.

Open design choice:

The draft says the strategy finds stocks inside strong groups, but the day-high
state itself is an intraday price pattern. The most faithful implementation is to
track `established_high` and pullback continuously for symbols in the replay
universe, then require strong-group eligibility only at the breakout tick. This
avoids losing a valid high/pullback sequence just because the symbol was not M1
earlier in the day. The more conservative implementation is to track only while
`match_type != "None"`, matching Signal A's current pattern, but that can change
the strategy's economics.

### Replay Loop Integration

Relevant file:

- `src/tw_signal_engine/replay/replay_session.py`

Required changes:

- Import the DayHigh config, state, and evaluator.
- Print `signalDayHigh_enabled` with the other switches.
- Create `signal_day_high_map: dict[str, SignalDayHighState] = {}`.
- Evaluate DayHigh after strong-group screening.
- Add DayHigh to deterministic signal priority.
- Pass `selected_signal_type="SignalDayHigh"` to `should_enter()` and `execute_entry()`.
- Apply DayHigh group limit-up blocking before execution.

Recommended priority:

```text
SignalDayHigh > SignalA > SignalAShort > SignalB
```

Rationale: DayHigh is explicitly a high-momentum breakout strategy with a narrow
entry window. If both DayHigh and Signal A trigger on the same symbol and tick,
DayHigh's exit and overnight semantics must win, because entering as Signal A
would stage take-profits and lose the overnight behavior.

Alternative priority:

```text
SignalA > SignalAShort > SignalB > SignalDayHigh
```

This preserves current behavior for existing configs if DayHigh is enabled
experimentally alongside Signal A. If backward compatibility is more important
than strategy semantics, use this priority and document that DayHigh should run in
a dedicated config with Signal A disabled.

### Entry Execution

Relevant files:

- `src/tw_signal_engine/execution/create_entry_trade.py`
- `src/tw_signal_engine/execution/position_sizing.py`

Reusable behavior:

- Long entry fill already uses `ask[0].price` fallback `match.price`.
- Fixed notional sizing already uses `position_cash`.
- `position_scale_nth=1.0` already disables nth-trade scale-down.
- `already_holding` is already blocked by `should_enter()`.

Required changes:

- Prevent take-profit order staging for `SignalDayHigh`.
- Keep `pos.reserve_stocks[symbol] = 0` for DayHigh unless a new overnight reserve model is introduced.
- Persist enough metadata on `EntryTrade` to identify DayHigh at exit and report time.

The cleanest execution change is a signal policy helper, not scattered string
checks:

```python
@dataclass(frozen=True)
class ExecutionPolicy:
    enable_take_profit: bool
    enable_bailout: bool
    hold_overnight_on_limit_up: bool
```

A minimal first pass can branch on `signal_type == "SignalDayHigh"` inside
`execute_entry()` and skip `pos.orders[symbol]` creation, but that will not scale
as more strategies are added.

### Stop-Loss

Relevant file:

- `src/tw_signal_engine/execution/apply_stop_loss_exit.py`

The current stop-loss dispatcher maps signal types to ratio attributes and anchor
attributes. Add DayHigh to that policy map:

```python
"SignalDayHigh": _StopLossPolicy(
    ratio_attr="stop_loss_ratio_day_high",
    anchor_attr="vwap",
    family="SignalDayHigh",
)
```

This matches the draft's VWAP stop. Because `entry_idx_map[symbol] = idx` stores
the entry-time `IndexData`, the stop anchor will be entry-time VWAP, not a rolling
current VWAP. The draft says `VWAP x 0.990`; it does not explicitly say whether
that is entry VWAP or continuously updated VWAP. The current Signal A convention
uses entry-time VWAP. If the research strategy used live/current VWAP, this is a
semantic gap and `on_tick_exit()` must receive the current `idx` instead of only
`entry_idx` for DayHigh stops.

Recommended decision:

- Use entry-time VWAP for initial implementation to fit existing engine semantics.
- Document it in the product spec.
- If current VWAP is required, add a new stop-loss anchor mode and tests because
  it changes existing `on_tick_exit()` contracts.

### Time Exit And Overnight Carry

Relevant files:

- `src/tw_signal_engine/execution/apply_time_exit.py`
- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/cli/run_batch_replay.py`

Current behavior is not compatible with the draft:

- `check_time_exit()` closes long positions at `exit_time_limit`.
- If reserve shares exist and price is at limit-up, it records a completed
  `lockedLimitUp` trade by selling reserve shares at limit-up.
- End-of-day finalization also force-closes remaining positions through the same
  exit path.
- `run_batch_replay.py` creates a fresh `PositionState` per day; there is no
  cross-day position store.

Required concept:

```python
@dataclass
class OvernightHolding:
    entry_trade: EntryTrade
    qty: float
    entry_idx: IndexData
    entry_signal_type: str
    carry_from_date: str
    limit_up_price: int
```

Implementation outline:

1. Add an optional `overnight_holdings` mapping passed into `run_daily_replay()`.
2. At the start of a replay day, include overnight symbols in `tick_filter` even if they are not today's strong-group candidates.
3. Before normal exit/entry logic, if a tick belongs to an overnight holding, close it on that first trade at the appropriate sell price and create a `TradeRecord` with cause such as `overnightExit`.
4. At `exit_time_limit`, for `SignalDayHigh` positions only, if `hold_overnight_on_limit_up` is true and the symbol is locked limit-up, remove it from `PositionState` without recording a completed day trade, and store it in `overnight_holdings`.
5. At finalization, do not force-close holdings that were intentionally moved to `overnight_holdings`.
6. In batch mode, keep the same `overnight_holdings` object across dates.
7. In single-day replay mode, decide whether to force-close, emit an open-position report, or return an additional open-holdings object. The current `run_daily_replay()` return type only supports completed trades.

Recommended API shape:

```python
def run_daily_replay(...) -> ReplayResult:
    completed_trades: list[TradeRecord]
    overnight_holdings: dict[str, OvernightHolding]
```

However, changing `run_daily_replay()` return type will touch many tests and call
sites. A lower-impact version is:

```python
def run_daily_replay(..., overnight_holdings: dict[str, OvernightHolding] | None = None) -> list[TradeRecord]:
```

When `overnight_holdings` is omitted, standalone daily replay can retain current
force-close behavior or log a warning that overnight carry requires batch mode.
For research correctness, batch mode should use the mapping.

### Limit-Up Lock Detection

Relevant files:

- `src/tw_signal_engine/records/market_event_records.py`
- `src/tw_signal_engine/market_data/parse_format6_replay_rows.py`
- `src/tw_signal_engine/market_data/redis_live_provider.py`
- `src/tw_signal_engine/replay/replay_session.py`

`MarketTick` already has `is_limit_up_locked`, `is_limit_down_locked`,
`total_bid_qty`, and `total_ask_qty`. The file parser currently fills only best
bid and best ask prices. It does not populate lock flags or total queue fields.
Redis live uses the same parser, so it has the same issue.

For DayHigh overnight correctness, a price equal to limit-up is not enough. The
draft says locked limit-up. Recommended lock logic:

- Parse depth counts and total bid/ask quantities from depth rows if available.
- After reference data is loaded, enrich ticks with:
  - `limit_up_int = int(ref.limit_up_price * 10000 + 0.5)`
  - `tick.is_limit_up_locked = tick.match.price >= limit_up_int and tick.ask[0].price == 0 and tick.bid[0].price > 0`
- Prefer parsed total ask quantity if reliable: locked if no ask queue and a bid queue exists at limit-up.

This enrichment can happen in `replay_session.py` after each tick is yielded, or
in provider wrappers if the provider receives `f1_map`. Keeping it in
`replay_session.py` avoids changing provider interfaces immediately.

### Take-Profit And Bailout Disabling

Relevant files:

- `src/tw_signal_engine/execution/create_entry_trade.py`
- `src/tw_signal_engine/execution/apply_take_profit_plan.py`
- `src/tw_signal_engine/execution/apply_bailout_exit.py`
- `src/tw_signal_engine/config/strategy_config.py`

The current engine assumes take-profit split invariants:

- `take_profit_splits > 0`
- `reserve_limit_up_splits >= 0`
- `take_profit_splits + reserve_limit_up_splits > 0`

This prevents disabling take-profit by simply setting `take_profit_splits=0`.
DayHigh needs no take-profit orders. Recommended options:

1. Add `ExecutionConfig.take_profit_enabled: bool = True`, then skip order staging and skip TP checks when false.
2. Add signal-specific execution policy and skip TP only for `SignalDayHigh`.
3. Loosen split validation to allow zero when `take_profit_enabled=false`.

Option 2 is safer because the repo currently runs Signal A and Signal A Short
with take-profit behavior. DayHigh can coexist without changing their behavior.

Bailout currently requires `pos.profit_taken[symbol] = True` before it can fire.
If DayHigh never stages take-profit orders, bailout is effectively disabled. Still,
add an explicit policy check to avoid relying on an incidental state condition.

### Cost Model

Relevant files:

- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/cli/run_batch_replay.py`

Current cost calculation uses:

```python
commission_val = (abs(entry_notional) + exit_notional) * config.commission_rate
tax_val = exit_notional * config.tax_rate
slippage_val = (abs(entry_notional) + exit_notional) * config.slippage_bps / 10000.0
```

This supports commission and slippage from the draft, but not different tax rates
for day trades versus overnight exits.

Recommended change:

- Add `TradeRecord.is_overnight: bool = False` or derive from `final_leave_cause == "overnightExit"`.
- Compute `tax_rate = config.overnight_tax_rate` for overnight exits, otherwise `config.day_trade_tax_rate` or `config.tax_rate`.
- Keep `tax_rate` override compatibility: if only `tax_rate` is set, use it for both day and overnight unless the new fields are explicitly configured.

### Reporting

Relevant files:

- `src/tw_signal_engine/reporting/build_trade_report_rows.py`
- `src/tw_signal_engine/reporting/write_order_log_csv.py`
- `src/tw_signal_engine/reporting/generate_batch_reports.py`
- `src/tw_signal_engine/reporting/build_trade_day_traces.py`

Basic reporting will work automatically if DayHigh exits produce normal
`TradeRecord` rows with `signal_type="SignalDayHigh"`. Useful additions:

- `EstablishedHigh` at entry.
- `PullbackLow` and pullback depth.
- `IsOvernight`.
- `CarryFromDate` / `ExitTradeDate` if entry and exit dates differ.
- `ExitPrice`, already present in `TradeRecord`.
- `GroupLimitUpCount` already exists and should be populated at entry.

Current `report_trades.csv` has one `TradeDate` field. For overnight trades,
this should either remain the entry date with a separate exit date added, or become
ambiguous. Add `ExitTradeDate` before relying on overnight batch reports.

### Dashboard

Relevant files:

- `src/tw_signal_engine/server/dashboard_snapshot.py`
- `src/tw_signal_engine/replay/replay_session.py`
- `dashboard/src/pages/SignalAMonitor.tsx`
- `dashboard/src/components/signal/*`

The current dashboard is centered on Signal A. `_build_dashboard_snapshot()` only
includes active and completed positions with `signal_type in {"SignalA", "SignalAShort"}`.
DayHigh trades will not show in that Signal A monitor unless this filter is
expanded or a new DayHigh monitor is added.

For initial replay research, dashboard support can be deferred. For live use or
paced replay monitoring, add either:

- a generic signal lifecycle snapshot keyed by `signal_type`, or
- a DayHigh-specific panel showing established high, pullback state, breakout price, and overnight status.

## Recommended Implementation Plan

### Phase 1 - Config And Signal State

- Add `SignalDayHighConfig` and `NormalizedStrategyConfig.signal_day_high`.
- Normalize `[SignalDayHigh]` from INI.
- Add `SignalDayHighState`.
- Add `evaluate_signal_day_high.py` with unit tests for:
  - initial high tracking
  - pullback confirmation
  - reset on new high before pullback
  - breakout after pullback
  - entry time window
  - min increase ratio
  - single-fire behavior
  - no trigger when screening match type is `None` at breakout

### Phase 2 - Screening Compatibility

- Make the strong-group `0.085` rank exclusion configurable/backwards-compatible.
- Add tests for `entry_max_vwap_pct_chg=0.095` retaining rank candidates above `8.5%`.
- Configure DayHigh strong-group settings:
  - `group_valid_top_n=10`
  - `top_group_max_select=1`
  - `normal_group_max_select=1`
  - `require_raw_m1=true`
  - `entry_min_vwap_pct_chg` aligned with research intent
  - `entry_max_vwap_pct_chg=0.095`
  - `block_disposition_entry=true`

### Phase 3 - Replay Entry Integration

- Add DayHigh state map to `run_daily_replay()`.
- Evaluate DayHigh after strong-group screening.
- Add signal priority decision.
- Add group limit-up blocking with reason such as `day_high_group_limit_up_count`.
- Ensure `entry_signal_type` and `entry_idx_map` are populated as today.
- Add replay-session tests with synthetic provider ticks.

### Phase 4 - Signal-Specific Execution Policies

- Add DayHigh stop-loss policy using `stop_loss_ratio_day_high` and `vwap` anchor.
- Skip take-profit order creation for `SignalDayHigh`.
- Explicitly skip bailout for `SignalDayHigh`.
- Preserve Signal A, Signal A Short, and Signal B behavior.
- Add unit tests for:
  - DayHigh ask-side entry
  - no staged take-profit orders
  - VWAP stop at `0.990`
  - time exit at bid
  - no bailout even when state would otherwise allow it

### Phase 5 - Limit-Up Lock Detection

- Populate `MarketTick.is_limit_up_locked` for file replay and Redis live paths.
- Prefer depth-aware lock detection; fallback to price-at-limit-up should be documented as weaker.
- Add parser/enrichment tests.

### Phase 6 - Overnight Batch Carry

- Introduce an `OvernightHolding` record.
- Thread an `overnight_holdings` mapping through batch replay.
- Include overnight symbols in the next day's replay universe.
- Close overnight holdings on the first next-day trade.
- Prevent same-day finalization from force-closing intentional DayHigh overnight holdings.
- Add `overnightExit` reporting and overnight tax rate.
- Add tests for:
  - hold at locked limit-up at `13:20`
  - no duplicate close after hold transfer
  - next-day first tick exit
  - batch report includes the completed overnight trade
  - overnight tax uses `0.3%`

### Phase 7 - Reporting And Docs

- Add optional DayHigh-specific trade fields if needed.
- Add `ExitTradeDate` or an explicit overnight flag to `TradeRecord` output.
- Update `docs/product-specs/current-strategy-spec.md` only after the implementation is active in committed config.
- Add a dedicated product spec for DayHigh once behavior is implemented and verified.

## Testing Strategy

Minimum unit test additions:

- `tests/unit/test_signal_day_high.py`
- `tests/unit/test_day_high_execution.py`
- `tests/unit/test_day_high_overnight.py`
- Add config coverage to `tests/unit/test_config.py`.
- Add strong-group upper-bound coverage to `tests/unit/test_group_state.py` or a new strong-group test file.
- Add replay-session synthetic provider coverage to `tests/unit/test_replay_session.py`.

Recommended validation commands:

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```

Golden parity impact:

- If DayHigh is disabled by default, existing golden parity tests should remain stable.
- Strong-group hard-code changes must preserve current behavior when DayHigh config is not active. Use defaults that keep `0.085` unless `entry_max_vwap_pct_chg` is explicitly set higher.

## Main Risks

### 1. VWAP Upper Bound Is Currently Hard-Coded

This is the largest config compatibility problem. DayHigh cannot express its
`9.5%` upper band through existing config alone because candidates are erased at
`8.5%` before the configurable max is checked.

### 2. Overnight Carry Changes The Replay Contract

Current daily replay returns only completed trades and assumes no positions cross
day boundaries. Overnight holdings require either a new result type or a mutable
batch-level carry store. This is a real architecture change, not a local signal
change.

### 3. Locked Limit-Up Is Not Reliably Detected From File Replay

`MarketTick.is_limit_up_locked` exists but is not populated by the file parser.
Any overnight implementation that uses only `price >= limit_up` will overstate
locked-limit behavior.

### 4. Disposition Stock Semantics Are Split

`StrongGroupEvaluator` uses `security == "RR"` for ranking/entry disposition
checks. `should_enter()` uses `disposition_stocks_enabled` to block early
`volatility_pause` ticks, not reference-data disposition stocks. The DayHigh spec
mentions disposition blocking, so implementation should use the reference-data
path explicitly.

### 5. Stop VWAP Anchor Needs Confirmation

Existing stop-loss design uses entry-time `IndexData`. If the DayHigh research
assumed current cumulative VWAP at each tick, the existing stop policy would be
semantically different.

### 6. Take-Profit Disabling Needs A Policy, Not Zero Splits

The current split invariants prevent simply setting `take_profit_splits=0`. A
signal-specific execution policy is safer than weakening global invariants.

## Recommended Initial Config Shape

A DayHigh-only config should likely disable other entry signals until coexistence
priority is deliberately tested:

```ini
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
```

Open config question:

The draft says entry level `>= 6%` from previous close and also says the upper
bound is a screening-layer VWAP percent-change upper bound. The sample config
places `max_increase_ratio=0.095` in `[SignalDayHigh]`. Implementation should
clarify whether `max_increase_ratio` applies to trade price, VWAP percent change,
or both. The existing strong-group `entry_max_vwap_pct_chg` is the natural place
for the VWAP upper bound.

## Conclusion

Day High Breakout should be implemented as a first-class signal type,
`SignalDayHigh`, rather than as a parameterization of Signal A. The current engine
can reuse strong-group screening, entry fill, sizing, stop-loss dispatch, and CSV
reporting, but four areas require code changes before the strategy is faithful to
the draft:

1. Add a dedicated day-high pullback-breakout state machine.
2. Make strong-group rank upper bounds configurable beyond the current hard-coded `8.5%`.
3. Add signal-specific execution policy so DayHigh has no take-profit/bailout and uses a VWAP `0.990` stop.
4. Add real overnight carry support with reliable locked-limit-up detection and overnight tax treatment.
