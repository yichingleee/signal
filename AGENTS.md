# AGENTS

This repository's active implementation is the Python replay engine in `src/tw_signal_engine/`. The archived C++ code under `legacy/cpp/` is kept as a parity reference, not as the current source of truth.

## Start Here

- Setup, replay commands, and validation: [README.md](README.md)
- Top-level architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Knowledge base home: [docs/index.md](docs/index.md)

## Code Map

- `src/tw_signal_engine/cli/`: daily and batch replay entrypoints
- `src/tw_signal_engine/config/`: legacy INI parsing and normalized config models
- `src/tw_signal_engine/reference_data/`: `Symbols_YYYYMMDD.csv` and `group.csv` loaders
- `src/tw_signal_engine/market_data/`: history-window loaders, replay row parsing, and data providers (file, paced, Redis live, backfill)
- `src/tw_signal_engine/replay/`: market gating, stream merge, session hooks, and the main replay session
- `src/tw_signal_engine/server/`: FastAPI web server, replay manager, and live state holder
- `src/tw_signal_engine/screening/`: strong-group and strong-single qualification
- `src/tw_signal_engine/signals/`: Signal A and Signal B evaluation
- `src/tw_signal_engine/execution/`: entry sizing plus stop-loss, take-profit, bailout, and time exits
- `src/tw_signal_engine/reporting/`: CSV order logs and end-of-day reports
- `src/tw_signal_engine/state/` and `src/tw_signal_engine/records/`: mutable runtime state and immutable records
- `tests/unit/`: unit coverage for config, state, reference loaders, filters, and utility rules
- `tests/golden/`: archived C++ parity comparisons

## Docs Map

- Design docs: [docs/design-docs/index.md](docs/design-docs/index.md)
- Current strategy behavior: [docs/product-specs/index.md](docs/product-specs/index.md)
- Runtime conventions, parity, and historical references: [docs/references/index.md](docs/references/index.md)
- Active and completed execution plans: [docs/exec-plans/active/index.md](docs/exec-plans/active/index.md), [docs/exec-plans/completed/index.md](docs/exec-plans/completed/index.md)

## Validation

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```
