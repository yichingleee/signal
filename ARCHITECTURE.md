# Architecture

`tw_signal_engine` is a single-process deterministic replay/backtest engine for Taiwan equities. It replays archived OTC and TSE tick files, applies strong-group and signal logic tick by tick, and writes CSV trade logs plus summary reports.

## Runtime Flow

1. Parse `exec/cfg/parameter.cfg` with the legacy INI loader and normalize it into typed config models.
2. Load symbol reference data from `Symbols_YYYYMMDD.csv`, derive previous-day limit-up flags, and load `group.csv`.
3. Build 20-session historical volume and trading-value caches from up to 21 replay sessions.
4. Initialize screening state, then build the replay universe from strong-group symbols, any enabled strong-single candidates, and `0050` for market gating.
5. Merge OTC and TSE replay files in `match_time_str` order.
6. For each trade tick: update market gate, update per-symbol intraday state, process exits first, then screening, signals, and entries.
7. Force-close any remaining positions at the end of the session, or before an early market-gate abort, then write `order_log_*.csv`, `report_trades.csv`, `report_summary.csv`, and `report_by_category.csv`.

## Domain Boundaries

- `config`: parse and normalize the legacy parameter file
- `reference_data` and `market_data`: static symbol/group inputs plus historical/replay file parsing
- `replay`: orchestration, stream merge, and session lifecycle
- `screening` and `signals`: symbol/group qualification and entry signal generation
- `execution`: position sizing and exit mechanics
- `reporting`: persisted outputs
- `state` and `records`: runtime state carriers and immutable records

## Live Data Integration

The engine supports three data source modes via the `MarketDataProvider` abstraction:

1. **File replay** (`FileReplayProvider`): reads archived OTC/TSE tick files. Default for batch backtesting.
2. **Redis live** (`RedisLiveProvider`): consumes real-time ticks from Redis Pub/Sub via a background listener thread and a thread-safe queue bridge. The main loop stays single-threaded.
3. **Backfill-then-live** (`BackfillThenLiveProvider`): replays archived files up to the current time, then switches to Redis live for mid-session startup.

An optional `PacedReplayProvider` wrapper adds wall-clock delays to simulate live timing at configurable speed.

`SessionHooks` (optional callbacks) allow external consumers — the web server, Parquet snapshot writers — to observe engine events without modifying the core loop.

## Dashboard

A FastAPI web server (`src/tw_signal_engine/server/`) serves engine state via REST API and Socket.IO WebSocket. A React SPA (`dashboard/`) provides the monitoring UI.

The API uses a **dual-mode pattern**: every endpoint transparently returns data from either `LiveState` (thread-safe, updated by engine hooks) or `ReplayManager` (Parquet-backed, supports time-travel). The frontend is mode-agnostic.

## Detailed Docs

- Detailed runtime architecture: [docs/design-docs/runtime-architecture.md](docs/design-docs/runtime-architecture.md)
- Live data architecture: [docs/design-docs/live-data-architecture.md](docs/design-docs/live-data-architecture.md)
- Dashboard architecture: [docs/design-docs/dashboard-architecture.md](docs/design-docs/dashboard-architecture.md)
- Namespace review and move plan: [docs/design-docs/python-module-namespaces.md](docs/design-docs/python-module-namespaces.md)
- Current committed strategy behavior: [docs/product-specs/current-strategy-spec.md](docs/product-specs/current-strategy-spec.md)
- Input/output conventions and CLI usage: [docs/references/runtime-conventions.md](docs/references/runtime-conventions.md)
- Archived parity status: [docs/references/parity-status.md](docs/references/parity-status.md)
