# PR #10 Review Comments Remediation Plan

**PR**: `#10` (`feat: add short-mode Signal A and env-based CLI default paths`)  
**Date**: 2026-04-18  
**Status**: Completed  
**Owner**: `tw_signal_engine` maintainers

## 1) Source Review Comments (Complete Coverage)

Reviewed all PR comments and threads:

- Inline review thread (unresolved): `discussion_r3101488108`
- Issue comment: `4269533257`
- Issue comment: `4269534096`
- Issue comment: `4269534106`
- Review summary comment: `pullrequestreview-4130127705` (informational, no actionable defect)

Actionable items deduplicate into 3 root issues:

1. `SignalAShort` can bypass stop-loss.
2. `trade_mode=short` routes `SignalB` as short even though evaluator logic is long-oriented.
3. Potential divide-by-zero in short entry take-profit split sizing.

## 2) Root-Cause Analysis

### 2.1 Stop-loss bypass for `SignalAShort`

Symptoms:

- Entry can be recorded with `signal_type="SignalAShort"`.
- Stop-loss branch in `check_stop_loss()` only handles `SignalA` and `SignalB`.

Root cause:

- Exit policy is coupled to raw signal string matching with no shared signal-family contract.
- `SignalA` variants are treated as separate string identities at entry time but not normalized for risk handling.

### 2.2 `SignalB` directional mismatch under compatibility short mode

Symptoms:

- Replay selection can set `selected_trade_mode="short"` for `SignalB` when `Strategy.trade_mode=short`.
- `evaluate_signal_b.py` remains long-oriented (preconditions, zone logic, trigger direction).

Root cause:

- Missing signal-direction capability contract (long-only vs short-capable) at orchestration layer.
- Replay selector infers side from global compatibility mode instead of validating signal-direction compatibility.

### 2.3 Divide-by-zero in TP split sizing

Symptoms:

- `execute_entry()` computes `q = abs(signed_qty) / actual_splits`.
- In short mode `actual_splits = take_profit_splits`; if zero, runtime crash.

Root cause:

- Missing invariant validation on execution configuration (`take_profit_splits` and related split math).
- Runtime path assumes validated configuration but normalization/model layer does not enforce the invariant.

## 3) Remediation Strategy

Fix root causes by introducing explicit contracts and validation boundaries, not one-off branch patches:

1. Introduce signal-policy mapping for stop-loss families.
2. Enforce signal-direction compatibility in replay selection.
3. Enforce TP split invariants at config load time plus runtime fail-fast guards.

## 4) Detailed Execution Plan

### Phase A - Signal Policy Contract for Stop-Loss (P0)

Target files:

- `src/tw_signal_engine/execution/apply_stop_loss_exit.py`
- `src/tw_signal_engine/execution/trade_ledger.py`
- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/records/trade_records.py` (type tightening if needed)

Tasks:

- [x] Create a signal stop-loss policy mapping so `SignalA` and `SignalAShort` share the same stop-loss family.
- [x] Replace fragile string-only branching with policy lookup + explicit unknown-signal handling.
- [x] Ensure stop-loss uses entry-side from open trade (`ot.side`) as authoritative where available.
- [x] Keep existing `SignalB` stop-loss behavior intact for long mode.
- [x] Add one defensive branch:
  - unknown signal type => no silent pass; emit explicit warning/exception per chosen safety mode.

Acceptance criteria:

- `SignalAShort` positions always evaluate stop-loss in both independent-short and compatibility flows.
- No regression for `SignalA` and `SignalB` existing stop-loss behavior in long mode.

### Phase B - Directional Safety Contract for `SignalB` in `trade_mode=short` (P0)

Target files:

- `src/tw_signal_engine/replay/replay_session.py`
- `src/tw_signal_engine/signals/evaluate_signal_b.py` (contract annotation/docs)
- `src/tw_signal_engine/config/strategy_config.py` (optional explicit capability flag/type)
- product docs under `docs/product-specs/` and architecture notes where signal behavior is described

Tasks:

- [x] Add explicit rule: current `SignalB` evaluator is long-only.
- [x] In compatibility short mode, prevent `SignalB` from being executed as short unless a mirrored short evaluator exists.
- [x] Implement deterministic safe behavior for now:
  - skip/disable `SignalB` in compatibility short mode with one-time runtime warning.
- [x] Add guardrails so future changes cannot silently re-enable directional mismatch.

Acceptance criteria:

- In `trade_mode=short`, `SignalB` no longer opens short trades with long-oriented trigger logic.
- Long-mode `SignalB` behavior remains unchanged.
- Runtime logs/docs clearly describe the compatibility-mode restriction.

### Phase C - TP Split Invariant Validation + Runtime Guard (P1)

Target files:

- `src/tw_signal_engine/config/strategy_config.py`
- `src/tw_signal_engine/config/normalize_strategy_config.py`
- `src/tw_signal_engine/execution/create_entry_trade.py`

Tasks:

- [x] Add config invariants for split sizing:
  - `take_profit_splits > 0`
  - `reserve_limit_up_splits >= 0`
  - long-path denominator safety (`take_profit_splits + reserve_limit_up_splits > 0`)
- [x] Add runtime fail-fast guard in `execute_entry()` before denominator use, with clear error context (`symbol`, `trade_mode`, split values).
- [x] Keep behavior deterministic when config is invalid:
  - fail early with explicit message instead of runtime divide-by-zero.

Acceptance criteria:

- Invalid split config is rejected during config normalization and also blocked at execution boundary.
- No divide-by-zero possible in entry TP sizing path.

### Phase D - Test Matrix and Regression Coverage (P0)

Target tests to add/update:

- `tests/unit/test_short_execution.py`
- `tests/unit/test_replay_session.py`
- `tests/unit/test_config.py`
- new focused tests if needed:
  - `tests/unit/test_stop_loss_policy.py`
  - `tests/unit/test_signal_b_direction_contract.py`

Tasks:

- [x] Add failing-then-passing test for `SignalAShort` stop-loss dispatch.
- [x] Add replay test proving `SignalB` cannot execute short in compatibility mode.
- [x] Add config validation tests for split invariants (`take_profit_splits=0`, negative reserve, etc.).
- [x] Add runtime guard test for `execute_entry()` invalid denominator.
- [x] Add regression tests for unchanged long-mode behavior.

Acceptance criteria:

- Each of the three reported defects is captured by at least one deterministic unit test.
- Existing long-mode strategy tests remain green.

### Phase E - Documentation and PR Thread Closure (P1)

Target files:

- `ARCHITECTURE.md`
- `docs/product-specs/*` relevant signal behavior docs
- `docs/references/*` if runtime contracts are documented there

Tasks:

- [x] Document stop-loss signal-family contract (`SignalAShort` shares Signal A stop-loss policy).
- [x] Document `SignalB` direction limitation in compatibility short mode.
- [x] Document split invariant requirements for Order/Execution config.
- [x] Post resolution notes in PR #10 referencing test evidence per comment ID.

Acceptance criteria:

- Behavior contracts are discoverable in docs and aligned with code/tests.
- Each actionable PR comment has a linked fix + test reference.

## 5) Verification Checklist

Implementation must pass:

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```

Focused local checks during development:

```bash
uv run pytest tests/unit/test_replay_session.py -q
uv run pytest tests/unit/test_short_execution.py -q
uv run pytest tests/unit/test_config.py -q
```

## 6) Risk and Rollout

Primary risks:

- Behavior drift in legacy `trade_mode=short` workflows.
- Accidental long-mode regressions when tightening signal contracts.

Mitigations:

- Keep changes contract-driven and localized by phase.
- Require explicit regression tests for long-mode and compatibility short-mode.
- Merge in small commits with clear scope.

Suggested commit slicing:

1. `refactor: introduce stop-loss signal policy contract`
2. `fix: block long-oriented SignalB from short compatibility execution`
3. `fix: validate take-profit split invariants and guard entry sizing`
4. `test: add regression coverage for PR10 review defects`
5. `docs: document signal-direction and stop-loss contracts`

## 7) Definition of Done

Done when all are true:

- All 3 actionable PR defects are fixed at root-cause level.
- New tests fail before fix and pass after fix.
- Full validation suite passes.
- Docs reflect the new contracts.
- PR #10 comments are replied to with concrete fix and test references.
