# AGENTS

The active implementation is the Python replay engine in
`src/tw_signal_engine/`. The C++ code under `legacy/cpp/` is archived for
parity and historical reference only.

## Start Here

- Setup, replay commands, and validation: [README.md](README.md)
- Top-level architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Documentation home: [docs/index.md](docs/index.md)

## Knowledge Base Map

- Design docs: [docs/design-docs/index.md](docs/design-docs/index.md)
- Product specs: [docs/product-specs/index.md](docs/product-specs/index.md)
- Runtime conventions and historical references: [docs/references/index.md](docs/references/index.md)
- Dashboard runtime notes: [docs/references/dashboard-operations.md](docs/references/dashboard-operations.md)
- Active plans: [docs/exec-plans/active/index.md](docs/exec-plans/active/index.md)
- Completed plans: [docs/exec-plans/completed/index.md](docs/exec-plans/completed/index.md)
- Open follow-ups: [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md)

For CLI path defaults and environment-variable behavior, use
[docs/references/runtime-conventions.md](docs/references/runtime-conventions.md).
Gotcha: Build `dashboard/dist` before expecting FastAPI to serve the UI at `/`.
Gotcha: Replay dashboard mode requires snapshot data generated with `--snapshots`.
Gotcha: If `Symbols_YYYYMMDD.csv` is missing for a parquet replay date, create `Symbols_<target>.csv` from the nearest available symbol CSV before running the replay.

## Validation

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```
