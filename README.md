# tw_signal_engine

Python is the primary interface for this repository. The production-facing code lives in `src/tw_signal_engine/`. The old replay implementation is archived under `legacy/cpp/` for parity and historical reference.

## Quick Start

```bash
uv sync

# Run one trading day from repo root
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date 20260129 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

If you want the original working-directory behavior, run from `exec/` and rely on the default relative paths:

```bash
cd exec
uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260129
```

To override default input paths for all CLI entrypoints, set environment variables:

```bash
export TW_SIGNAL_DATA_DIR=/absolute/path/to/tick-data
export TW_SIGNAL_FILES_DIR=/absolute/path/to/symbols
export TW_SIGNAL_GROUP_FILE=/absolute/path/to/group.csv
```

For project-local defaults with direnv:

```bash
cat > .envrc <<'EOF'
export TW_SIGNAL_DATA_DIR=/absolute/path/to/tick-data
export TW_SIGNAL_FILES_DIR=/absolute/path/to/symbols
export TW_SIGNAL_GROUP_FILE=/absolute/path/to/group.csv
EOF
direnv allow
```

Batch replay is also available:

```bash
uv run python -m tw_signal_engine.cli.run_batch_replay \
  --start 20260127 \
  --end 20260225 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

Regenerate charts from existing report CSVs without rerunning replay:

```bash
# Daily + batch charts from an existing batch log folder
uv run python -m tw_signal_engine.cli.run_charts_only \
  --log-dir log/0418_1541

# Also rebuild per-symbol intraday timeline charts (requires replay data files)
uv run python -m tw_signal_engine.cli.run_charts_only \
  --log-dir log/0418_1541 \
  --with-trade-day \
  --data-dir /path/to/tick-data
```

For live/server workflows, install live runtime dependencies:

```bash
uv sync --extra live
```

## Signal Direction Modes

- Default strategy mode is `Strategy.trade_mode=long`.
- The default short-side signal path is `SignalAShort.enabled=true` (runs alongside `SignalA`/`SignalB` during the same replay).
- `Strategy.trade_mode=short` is a legacy compatibility mode that remains supported. Use it only when you need historical short-only behavior from older runs.

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
