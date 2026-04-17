# Short Signal-A Weak-Group Execution Plan

**Date**: 2026-04-16  
**Status**: Completed  
**Owner**: `tw_signal_engine` maintainers

## 1) Scope and Locked Decisions

This plan adds a short-side strategy path by mirroring the current long Signal A flow with explicit side contracts.

Locked choices from requirement clarification:

1. Strategy side is selected per run via config switch: `trade_mode=long|short`.
2. Position quantity is **signed**:
   - long position: `qty > 0`
   - short position: `qty < 0`
   - flat: `qty == 0`
3. Short path uses true short accounting and position state (not signal-only simulation).
4. Short screening path replaces strongest selection with weakest selection:
   - weakest group
   - weakest member
5. In short mode, `StrongSingle` is disabled for entry decisions.
6. Short Signal A uses mirrored near-VWAP and follow-through logic:
   - near condition: `price / vwap >= short_vwap_near_ratio` (default `0.993`)
   - trigger condition: rejection/down move from local high after near
7. Exit stack order remains unchanged for both sides:
   - stop-loss
   - time exit
   - take-profit
   - bailout
8. Side-aware execution pricing is explicitly locked by rule matrix (section 5.5).

## 2) Goals

1. Preserve current long-mode behavior as default and backward compatible.
2. Add a production-grade short-mode path that is symmetric enough to reason about and test.
3. Keep replay, reporting, and dashboard outputs consistent with side-aware behavior.

## 3) Non-Goals

1. No redesign of live transport/provider architecture.
2. No major frontend redesign.
3. No unrelated strategy tuning beyond required mirror behavior.
4. No margin-borrow/fee model expansion beyond existing cost model fields.

## 4) Current Baseline (Code Anchors)

Primary baseline paths:

- Replay orchestration: `src/tw_signal_engine/replay/replay_session.py`
- Strong-group screening: `src/tw_signal_engine/screening/evaluate_strong_group.py`
- Strong-single screening: `src/tw_signal_engine/screening/evaluate_strong_single.py`
- Signal A evaluation: `src/tw_signal_engine/signals/evaluate_signal_a.py`
- Entry filters and trade creation: `src/tw_signal_engine/execution/create_entry_trade.py`
- Exit stack ordering: `src/tw_signal_engine/execution/trade_ledger.py`
- Exit modules:
  - `src/tw_signal_engine/execution/apply_stop_loss_exit.py`
  - `src/tw_signal_engine/execution/apply_time_exit.py`
  - `src/tw_signal_engine/execution/apply_take_profit_plan.py`
  - `src/tw_signal_engine/execution/apply_bailout_exit.py`
- Mutable signal/position state:
  - `src/tw_signal_engine/state/signal_state.py`
  - `src/tw_signal_engine/state/position_state.py`
- Record/report schema:
  - `src/tw_signal_engine/records/trade_records.py`
  - `src/tw_signal_engine/records/market_event_records.py`
  - `src/tw_signal_engine/reporting/*`
- Config models and parsing:
  - `src/tw_signal_engine/config/strategy_config.py`
  - `src/tw_signal_engine/config/normalize_strategy_config.py`
  - `exec/cfg/parameter.cfg`

## 5) Design Overview

### 5.1 Strategy mode contract

Add `trade_mode` under `[Strategy]` with accepted values:

- `long` (default)
- `short`

Behavior:

- `long`: existing flow unchanged.
- `short`: weak-group + weak-member + mirrored Signal A + side-aware signed-qty execution.

### 5.2 Position and side contract (signed qty)

Core invariants:

1. `pos.stocks[symbol]` is signed quantity.
2. Open-position checks use `abs(qty) > 0` (not `qty > 0`).
3. One-open-position-per-symbol invariant is unchanged.
4. Trade side is derived from entry quantity sign and also persisted explicitly in records:
   - `side="long"` when entry qty positive
   - `side="short"` when entry qty negative
5. `symbol_cash` and `baseline` semantics stay consistent:
   - cashflow sign follows transaction direction
   - PnL remains `symbol_cash - baseline` and is positive for profitable trades on both sides.

### 5.3 Short screening contract

In short mode:

1. Rank groups by weakest performance (ascending pct-change semantics).
2. Rank members by weakest VWAP-relative gain.
3. Mirror raw-rank gate semantics:
   - if `require_raw_m1=true`, the symbol must be raw weakest rank `1`.
4. Mirror directional inequalities for threshold gates (`<`/`>` swapped as required by side intent).
5. Disable strong-single path for entry:
   - do not use `StrongSingle` qualification to form `match_type`.
   - `match_type` is `StrongGroup` or `None` only in short mode.

### 5.4 Mirrored Signal A contract

Long mode keeps current behavior.

Short mode state machine:

1. Must be within entry window.
2. Must pass mirrored precondition:
   - long currently forbids when price is too weak vs VWAP.
   - short forbids when price is too strong vs VWAP using a mirrored ratio threshold.
3. Must pass mirrored extreme-move guard:
   - long blocks extreme up moves above `trade_zone_max_increase_ratio`.
   - short blocks extreme down moves below `-trade_zone_max_increase_ratio`.
4. Arm near phase when `pv_ratio >= short_vwap_near_ratio` (default `0.993`).
5. Track `high_since_near` while armed.
6. Trigger when `(high_since_near - price) / high_since_near >= bounce_ratio`.
7. Keep timeout semantics and single-fire-per-symbol-per-day semantics.
8. Keep `match_type == "None"` reset behavior side-correct.

### 5.5 Execution price-source matrix (locked)

`fallback` means use match price when the primary quote is missing/non-positive.

| Action | Long mode | Short mode |
|---|---|---|
| Entry fill | buy at `ask1` (fallback: match) | short-sell at `bid1` (fallback: match) |
| Stop-loss close | sell at `bid1` (fallback: match) | buy-to-cover at `ask1` (fallback: match) |
| Time-exit close | sell at `bid1` (fallback: match) | buy-to-cover at `ask1` (fallback: match) |
| Take-profit trigger | `price >= tp_level` | `price <= tp_level` |
| Take-profit fill price | order level price | order level price |
| Bailout close | sell at `bid1` (fallback: match) | buy-to-cover at `ask1` (fallback: match) |
| End-of-day forced close | sell at `bid1` (fallback: last match) | buy-to-cover at `ask1` (fallback: last match) |

### 5.6 Take-profit reserve and lock behavior

1. Existing long reserve/limit-up behavior stays unchanged.
2. Short mode does not reuse long `limit_up` reserve semantics.
3. If short reserve-like behavior is needed later (e.g., limit-down lock handling), it is a separate plan item and out of current scope.

## 6) Implementation Plan

### Phase A - Config and mode plumbing [COMPLETED]

Files:

- `src/tw_signal_engine/config/strategy_config.py`
- `src/tw_signal_engine/config/normalize_strategy_config.py`
- `exec/cfg/parameter.cfg`
- strategy docs under `docs/product-specs/` and `docs/design-docs/`

Tasks:

- [x] Add `trade_mode` to `StrategyGlobalConfig`.
- [x] Parse and validate `trade_mode` from INI; default `long`.
- [x] Add short Signal A config knobs required by locked behavior:
   - `short_vwap_near_ratio` (default `0.993`)
   - mirrored precondition ratio (explicit or derived default)
- [x] Thread `trade_mode` through replay session call graph.
- [x] Update docs for runtime behavior and configuration.

Deliverable:

- Mode switch exists, defaults to current behavior, and short-specific config is explicit.

### Phase B - Weakest-group/member screening path [COMPLETED]

Files:

- `src/tw_signal_engine/screening/evaluate_strong_group.py`
- `src/tw_signal_engine/state/group_state.py` (if ranking helper needs directional support)
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/screening/evaluate_strong_single.py` (short-mode disable gating only)

Tasks:

- [x] Add directional ranking path controlled by `trade_mode`.
- [x] Implement weakest group selection in short mode.
- [x] Implement weakest member selection in short mode.
- [x] Mirror rank-based gate checks (`require_raw_m1` weakest-side semantics).
- [x] Disable strong-single contribution to entry in short mode.
- [x] Keep `long` path behavior unchanged and explicitly regression-tested.

Deliverable:

- Screening output produces short candidates from weakest-group/member path only.

### Phase C - Signal A mirror for short mode [COMPLETED]

Files:

- `src/tw_signal_engine/signals/evaluate_signal_a.py`
- `src/tw_signal_engine/state/signal_state.py`

Tasks:

- [x] Extend Signal A state to support mirrored tracked extremum (`high_since_near`).
- [x] Add short-mode near condition (`pv_ratio >= short_vwap_near_ratio`).
- [x] Add mirrored precondition and extreme-move guard logic for short.
- [x] Add short-mode rejection trigger from `high_since_near`.
- [x] Keep timeout and single-fire semantics consistent across sides.
- [x] Ensure `match_type == "None"` reset logic remains correct for both extrema fields.

Deliverable:

- Short Signal A triggers deterministically on mirrored setup with fully defined guards.

### Phase D - Signed-qty ledger and entry model [COMPLETED]

Files:

- `src/tw_signal_engine/execution/create_entry_trade.py`
- `src/tw_signal_engine/state/position_state.py`
- `src/tw_signal_engine/records/trade_records.py`
- `src/tw_signal_engine/records/market_event_records.py`
- `src/tw_signal_engine/replay/replay_session.py`

Tasks:

- [x] Implement signed quantity entry:
   - long entry qty positive
   - short entry qty negative
- [x] Apply entry price matrix (section 5.5) by side.
- [x] Update open-position checks to use signed invariant (`abs(qty) > 0`).
- [x] Preserve one-open-position-per-symbol invariant.
- [x] Ensure baseline and symbol cash accounting are correct for both sides.
- [x] Add explicit `side` field in open/completed trade records and append side metadata in logs where needed.

Deliverable:

- Ledger state supports long/short with signed qty and no sign inconsistencies.

### Phase E - Mirrored short exits (full stack) [COMPLETED]

Files:

- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/execution/apply_stop_loss_exit.py`
- `src/tw_signal_engine/execution/apply_time_exit.py`
- `src/tw_signal_engine/execution/apply_take_profit_plan.py`
- `src/tw_signal_engine/execution/apply_bailout_exit.py`

Tasks:

- [x] Keep exit priority ordering unchanged.
- [x] Add side-aware close helper(s) implementing the locked price matrix.
- [x] Add short stop-loss mirror with buy-to-cover quote side.
- [x] Add short take-profit trigger/fill behavior (`price <= cover_level`).
- [x] Add short bailout mirror after first TP.
- [x] Ensure time exit and forced close cover short positions with correct quote source.
- [x] Keep long behavior unchanged.

Deliverable:

- Full side-aware exit stack passing long and short tests.

### Phase F - Replay/report/dashboard integration [COMPLETED]

Files:

- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/reporting/*`
- `src/tw_signal_engine/server/dashboard_snapshot.py`
- `src/tw_signal_engine/server/live_state.py`
- `src/tw_signal_engine/server/app.py`

Tasks:

- [x] Pass `trade_mode` through screening, signal, entry, and exit paths.
- [x] Ensure dashboard position/Signal A fields represent short trades correctly.
- [x] Ensure open-position serialization uses signed-qty invariant (`abs(qty) > 0`).
- [x] Add side-aware report columns/values with append-only schema strategy where possible.
- [x] Verify category/funnel summaries remain meaningful in short mode.

Deliverable:

- End-to-end replay output is side-correct for both modes and API payloads are unambiguous.

### Phase G - Test matrix and validation [COMPLETED]

Unit tests to add/update:

- [x] Config parsing/default tests:
   - `trade_mode` default and validation
   - short Signal A config defaults
- [x] Screening tests for weakest path selection in short mode.
- [x] Screening tests verifying `StrongSingle` does not drive short entries.
- [x] Signal A tests:
   - short near arm
   - short rejection trigger
   - short precondition/guard
   - timeout and no re-arm semantics
- [x] Entry/ledger tests for signed qty, side-aware cashflow, and baseline correctness.
- [x] Exit tests for short stop-loss/time-exit/TP/bailout using quote-side matrix.
- [x] Replay-session integration tests for mode-switched run behavior.
- [x] Reporting/API tests for side-aware output compatibility.
- [x] Long-regression tests:
   - existing unit suite
   - golden parity suite for long mode.

Validation commands:

```bash
uv run pytest tests -q
uv run pytest tests/golden -m golden -q
uv run ruff check src tests
uv run mypy src
```

Validation status:

- [x] `uv run pytest tests -q`
- [x] `uv run pytest tests/golden -m golden -q`
- [x] `uv run ruff check src tests`
- [x] `uv run mypy src`

## 7) Acceptance Criteria

1. `trade_mode=long` reproduces existing behavior:
   - existing unit tests pass
   - golden parity tests pass unchanged.
2. `trade_mode=short` executes:
   - weakest-group/member selection
   - `StrongSingle` not used for short entry
   - mirrored Signal A near+rejection with mirrored guards
   - signed-qty true short entry/exit accounting
   - full mirrored exit stack with locked execution price matrix.
3. `TradeRecord`/entry records/report rows include explicit side metadata.
4. CSV reports and dashboard snapshots are side-consistent and unambiguous.
5. Full checks pass (`pytest`, `pytest tests/golden -m golden`, `ruff`, `mypy`).

## 8) Risk Register and Mitigations

1. Risk: sign bugs in short cashflow and PnL.
   - Mitigation: centralize side-aware arithmetic and add primitive-level signed-qty tests.
2. Risk: directional ranking changes regress long mode.
   - Mitigation: mode-gated branching plus explicit long regression and golden tests.
3. Risk: quote-side execution drift across modules.
   - Mitigation: implement one shared price-source helper and assert module-level consistency in tests.
4. Risk: report/schema drift breaks downstream consumers.
   - Mitigation: append-only schema changes, explicit side column addition, and report/API fixture tests.
5. Risk: ambiguity between `run_server --mode` and strategy `trade_mode`.
   - Mitigation: document separately and keep distinct names (`server mode` vs `strategy trade_mode`).

## 9) Suggested Commit Sequence

1. `feat: add strategy trade_mode and short signal-a config plumbing`
2. `feat: add weakest group-member screening and short strong-single disable`
3. `feat: add mirrored signal a short guards near and rejection state machine`
4. `refactor: migrate ledger to signed qty with explicit trade side metadata`
5. `feat: add side-aware stop time tp bailout execution price matrix`
6. `feat: add short-mode replay reporting and dashboard side-aware payloads`
7. `test: add short mode screening signal and signed-qty execution coverage`
8. `docs: update short signal-a weak-group execution plan and strategy docs`
