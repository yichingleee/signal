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
  --start 20260319 \
  --end 20260326 \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --files-dir /Users/liyijing/Projects/Trading/market-data/symbols \
  --group-file /Users/liyijing/Projects/Trading/market-data/group/group-ver20260329.csv \
  --config exec/cfg/parameter.cfg
```

Parquet history caches are supported for faster repeated runs. Build caches once:

```bash
uv run python -m tw_signal_engine.cli.build_parquet_history_cache \
  --start 20260301 \
  --end 20260331 \
  --data-dir /Users/liyijing/Projects/Trading/market-data/tick-data \
  --jobs 4
```

By default, cache files are written under a sibling `parquet-history-cache/`
directory next to `--data-dir`. Override with
`TW_SIGNAL_PARQUET_HISTORY_CACHE_DIR` or `--cache-dir`. Daily and batch replay
use these caches automatically unless `--no-cache` is set.

Parquet and text are separate data sources with separate truth contracts. Use `scripts/compare_text_vs_parquet.py` for diagnostics; strict text-vs-parquet `report_trades.csv` equality is not a release gate.

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
- Archived parity notes: [docs/references/parity-status.md](docs/references/parity-status.md)

## Verification

```bash
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```

The archived C++ code can still be built separately:

```bash
cd legacy/cpp
make
```
