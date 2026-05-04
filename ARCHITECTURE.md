# Architecture

`tw_signal_engine` is a single-process deterministic replay/backtest engine for Taiwan equities. It replays archived OTC and TSE tick files, applies strong-group and signal logic tick by tick, and writes CSV trade logs plus summary reports. The default replay source is parquet; legacy text replay remains available as an explicit compatibility source.

## Runtime Flow

1. Parse `exec/cfg/parameter.cfg` with the legacy INI loader and normalize it into typed config models.
2. Load symbol reference data from `Symbols_YYYYMMDD.csv`, derive previous-day limit-up flags, and load `group.csv`.
3. Build 20-session historical volume and trading-value windows from the selected source (`parquet` by default, `text` when requested).
4. Initialize screening state, then build the replay universe from strong-group symbols, any enabled strong-single candidates, and `0050` for market gating.
5. Construct the selected replay provider: `ParquetReplayProvider` reads `TWSE`/`TPEX` parquet files, while `FileReplayProvider` reads legacy `TSEQuote`/`OTCQuote` text files.
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

## Signal Direction Contract

- Preferred/default operation: keep `Strategy.trade_mode=long` and enable `SignalAShort` for short-side setups in the same replay session.
- Legacy compatibility: `Strategy.trade_mode=short` is still supported for historical short-only behavior and parity checks.
- `SignalB` is currently long-only; in `trade_mode=short` compatibility mode it is explicitly disabled with a runtime warning.

## Live Data Integration

The engine supports three data source modes via the `MarketDataProvider` abstraction:

1. **Parquet replay** (`ParquetReplayProvider`): reads archived `TWSE/YYYYMMDD.parquet` and `TPEX/YYYYMMDD.parquet` files. Default for daily and batch replay.
2. **File replay** (`FileReplayProvider`): reads legacy `TSEQuote.YYYYMMDD` and `OTCQuote.YYYYMMDD` text files when `--data-source text`.
3. **Redis live** (`RedisLiveProvider`): consumes real-time ticks from Redis Pub/Sub via a background listener thread and a thread-safe queue bridge. The main loop stays single-threaded.
4. **Backfill-then-live** (`BackfillThenLiveProvider`): replays archived files up to the current time, then switches to Redis live for mid-session startup.

An optional `PacedReplayProvider` wrapper adds wall-clock delays to simulate live timing at configurable speed.

Parquet and text are separate truth sources. Cross-source comparisons are diagnostic, not strict release gates, and `report_trades.csv` includes `DataSource` provenance.

`SessionHooks` (optional callbacks) allow external consumers, including the web server and Parquet snapshot writers, to observe engine events without modifying the core loop.

## Dashboard

A FastAPI web server under `src/tw_signal_engine/server/` serves dashboard data and, when available, mounts the built React SPA from `dashboard/dist/` at `/`.

The dashboard contract is split across three layers:
- `app.py`: REST endpoints, replay control endpoints, Socket.IO push loop, and static SPA mounting
- `live_state.py`: thread-safe bridge between the engine thread and API consumers in live mode
- `dashboard_snapshot.py`: canonical snapshot schema mirrored by `dashboard/src/types/dashboard.ts`

The implemented UI is a small React + TypeScript SPA under `dashboard/` with these routes:
- `/`: market overview
- `/signal-a`: Signal A lifecycle monitor
- `/signal-a-short`: SignalAShort lifecycle monitor
- `/day-high`: SignalDayHigh monitor

Signal B is exposed on the overview page rather than a dedicated route.

### Dashboard runtime modes

The backend exposes the same dashboard endpoints in two modes:
- `live`: read current state from `LiveState` and push `dashboard:snapshot` events over Socket.IO, with REST polling as browser fallback
- `replay`: read stored snapshots from `ReplayManager` and jump through time via `POST /api/replay/jump`

This keeps the page components mostly transport-agnostic while allowing replay-specific controls such as the time slider.

### Dashboard operational constraints

- The UI at `/` exists only when `dashboard/dist/` has been built.
- Replay dashboard workflows require snapshot artifacts generated with `--snapshots`.
- Replay payloads may use stored `dashboard_*` field names, and the frontend normalizes them into the live snapshot shape before rendering.

## Detailed Docs

- Detailed runtime architecture: [docs/design-docs/runtime-architecture.md](docs/design-docs/runtime-architecture.md)
- Live data architecture: [docs/design-docs/live-data-architecture.md](docs/design-docs/live-data-architecture.md)
- Dashboard architecture: [docs/design-docs/dashboard-architecture.md](docs/design-docs/dashboard-architecture.md)
- Dashboard operations: [docs/references/dashboard-operations.md](docs/references/dashboard-operations.md)
- Namespace review and move plan: [docs/design-docs/python-module-namespaces.md](docs/design-docs/python-module-namespaces.md)
- Current committed strategy behavior: [docs/product-specs/current-strategy-spec.md](docs/product-specs/current-strategy-spec.md)
- Input/output conventions and CLI usage: [docs/references/runtime-conventions.md](docs/references/runtime-conventions.md)
- Archived parity status: [docs/references/parity-status.md](docs/references/parity-status.md)
