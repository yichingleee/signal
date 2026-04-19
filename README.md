# tw_signal_engine

Python is the primary interface for this repository. The production-facing code lives in `src/tw_signal_engine/`. The old replay implementation is archived under `legacy/cpp/` for parity and historical reference. Daily and batch replay default to the parquet market-data source; legacy text replay remains available with `--data-source text`.

## Quick Start

```bash
uv sync

# Run one trading day from repo root with the default parquet source
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date 20260326 \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
  --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
  --config exec/cfg/parameter.cfg
```

You can also set `TW_SIGNAL_PARQUET_DATA_DIR` and omit `--data-dir` for parquet replay.

If you want the original text working-directory behavior, run from `exec/` and request the text source:

```bash
cd exec
uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260129 --data-source text
```

Batch replay is also available:

```bash
uv run python -m tw_signal_engine.cli.run_batch_replay \
  --start 20260319 \
  --end 20260326 \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
  --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
  --config exec/cfg/parameter.cfg
```

Parquet and text are separate data sources with separate truth contracts. Use `scripts/compare_text_vs_parquet.py` for diagnostics; strict text-vs-parquet `report_trades.csv` equality is not a release gate.

For live/server workflows, install live runtime dependencies:

```bash
uv sync --extra live
```

## Repository Guide

- Repo map for agents and contributors: [AGENTS.md](AGENTS.md)
- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Knowledge base home: [docs/index.md](docs/index.md)
- Current runtime architecture: [docs/design-docs/runtime-architecture.md](docs/design-docs/runtime-architecture.md)
- Current committed strategy behavior: [docs/product-specs/current-strategy-spec.md](docs/product-specs/current-strategy-spec.md)
- Runtime conventions and file layout: [docs/references/runtime-conventions.md](docs/references/runtime-conventions.md)
- Golden parity status: [docs/references/parity-status.md](docs/references/parity-status.md)

## Verification

```bash
uv run pytest tests -q
uv run pytest tests/golden -m golden -q
uv run ruff check src tests
uv run mypy src
```

The archived C++ code can still be built separately:

```bash
cd legacy/cpp
make
```
