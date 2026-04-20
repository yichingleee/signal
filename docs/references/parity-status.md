# Parity Notes (Archived)

## Current Status

The repository no longer ships an automated golden parity pytest suite.
The previous parity fixtures were archived for these replay dates:

- `20260127`
- `20260128`
- `20260129`
- `20260130`
- `20260211`
- `20260223`
- `20260224`
- `20260225`

The historical fixture layout was:

- `artifacts/baseline/cpp/YYYYMMDD/`
- `artifacts/baseline/python/YYYYMMDD/`

The former comparator validated trade identity fields, rank fields, and `PnL`
with a small tolerance.

## Confirmed Replay Delta Fixes

- `Symbols_YYYYMMDD.csv` decoding now supports real dataset encodings such as `cp950`, avoiding startup failures on production-style symbol files.

## Parity-Sensitive Behaviors Still Preserved

Some implementation details are kept because the archived baselines depend on them:

- `state/GroupRank` preserves the old score-collision overwrite behavior
- `StrongSingleEvaluator._eval_price_cond()` keeps the effective C++ behavior where only the day-high increase path matters
- the merged replay flow uses the exact exit ordering `stop-loss -> time exit -> take-profit -> bailout`

These are descriptions of the current parity lock, not endorsements of the design.

## Scope Note

These notes are historical reference only. The source of truth for current
behavior is the Python runtime plus unit/integration tests under `tests/`.
