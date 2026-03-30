# Live Data Architecture

This document describes the as-built architecture for live market data integration. It covers the provider abstraction, all provider implementations, session hooks, and how to test each component.

**Related docs**:
- Pre-implementation research: [live-data-integration-research.md](live-data-integration-research.md)
- Execution plan: [../exec-plans/completed/live-data-integration-execution-plan.md](../exec-plans/completed/live-data-integration-execution-plan.md)
- Dashboard (the main consumer of live state): [dashboard-architecture.md](dashboard-architecture.md)

---

## 1. Core Idea: The Provider Abstraction

The single most important design decision is that the main event loop in `replay_session.py` consumes an `Iterator[MarketTick]` and does not care where ticks come from. All data source differences are encapsulated behind `MarketDataProvider`:

```
src/tw_signal_engine/market_data/providers.py

class MarketDataProvider(ABC):
    @abstractmethod
    def iterate_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects in chronological order."""
```

This means screening, signals, execution, and exits are **identical** regardless of whether ticks come from archived files, a paced simulation, or a live Redis stream. There is exactly one event loop, one set of state machines, and one code path.

### Provider Dependency Injection

`run_daily_replay()` accepts an optional `provider` parameter:

```python
def run_daily_replay(
    trade_date: str,
    ...
    provider: MarketDataProvider | None = None,
) -> list[TradeRecord]:
```

- If `provider is None` → constructs `FileReplayProvider` (backward compatible with batch replay)
- If a provider is passed → uses it directly (live, paced, backfill, or any future source)

This is a pure dependency-injection pattern — the caller decides the data source, the session logic is unchanged.

---

## 2. Provider Implementations

### 2.1 FileReplayProvider

**File**: `src/tw_signal_engine/market_data/file_replay_provider.py`

Wraps the existing `merge_market_streams()` function. Reads OTC + TSE archive files (`OTCQuote.YYYYMMDD`, `TSEQuote.YYYYMMDD`), merges them by `match_time_str`, and yields `MarketTick` objects. No timing delays — runs as fast as the CPU allows.

**When to use**: Batch backtesting, golden parity tests, generating Parquet snapshots for replay mode.

### 2.2 PacedReplayProvider

**File**: `src/tw_signal_engine/market_data/paced_replay_provider.py`

Wraps any provider with wall-clock delays to simulate live timing. A decorator/wrapper pattern:

```python
class PacedReplayProvider(MarketDataProvider):
    def __init__(self, inner: FileReplayProvider, speed: float = 1.0): ...
```

**Timing formula**:
```
target_delay = (data_time_sec - start_data_sec) / speed
sleep_needed = target_delay - (wall_time - start_wall)
```

- `speed=1.0` → real-time (4.5 hours for a full trading day)
- `speed=60.0` → 60× faster (~4.5 minutes for a full day)
- `speed=2.0` → useful for dashboard development

**When to use**: Dashboard development/testing without waiting for a full trading day. Activated via CLI flags `--paced --speed 2.0`.

### 2.3 RedisLiveProvider

**File**: `src/tw_signal_engine/market_data/redis_live_provider.py`

Consumes live market data from Redis Pub/Sub and produces `MarketTick` objects.

**Architecture: Thread-Safe Queue Bridge**

```
Redis Pub/Sub listener thread (daemon)
    │  subscribe to channels = stock symbols (e.g. "2330", "2317")
    │  on_message → parse → queue.put(MarketTick)
    ▼
queue.Queue[MarketTick | None]      ← thread-safe bridge
    │
    ▼
RedisLiveProvider.iterate_ticks()   ← main thread, single-threaded
    │  queue.get(timeout=1.0) → optional reorder buffer → yield
    ▼
replay_session.py main loop         ← unchanged from batch replay
```

**Key implementation ideas**:

1. **Same parser, same format**: Redis messages use the identical CSV format as archived quote files (`Trade,{symbol},{time},{func_code},{price},{volume},...`). The provider reuses `parse_trade_line()` from `parse_format6_replay_rows.py` — zero parser duplication.

2. **Trade/Depth pairing**: Redis publishes Trade and Depth lines as separate messages on the same per-symbol channel. The provider buffers the last Trade line per symbol in `_pending_trade` and pairs it with the next Depth line. If a new Trade arrives before Depth, the previous Trade is flushed without depth data. This mirrors the pairing logic in `iterate_market_file.py`.

3. **Main thread stays single-threaded**: The `queue.Queue` is the only synchronization point. The main event loop never touches Redis directly — it just pulls `MarketTick` objects from the queue, same as it pulls from file iterators.

4. **Reorder buffer**: Optional 100ms window (configurable via `reorder_buffer_ms`) that collects ticks and sorts by `match_time_str` before yielding. Handles rare out-of-order Pub/Sub delivery.

5. **Auto-reconnect**: On `ConnectionError`, waits `reconnect_delay` seconds (default 5.0) and retries. Does not crash. Logs warnings.

6. **Enrichment**: Each tick is enriched with `prev_limit_up` (from previous-day reference data) and `volatility_pause` (via `NumTracker` — True if ≤3 trades in same second), identical to file replay enrichment.

7. **Graceful shutdown**: `stop()` sets a `threading.Event` and pushes `None` sentinel to unblock the queue. CLI registers `SIGINT`/`SIGTERM` handlers.

**Configuration** (`LiveConfig` in `config/strategy_config.py`):

| Field | Default | Purpose |
|---|---|---|
| `enabled` | `False` | Master switch |
| `redis_host` | `192.168.100.130` | Redis server address |
| `redis_port` | `6379` | Redis port |
| `redis_db` | `0` | Redis database index |
| `socket_timeout` | `5` | Connection timeout (seconds) |
| `reconnect_delay` | `5.0` | Backoff between reconnect attempts |
| `reorder_buffer_ms` | `100` | Out-of-order tolerance window |

### 2.4 BackfillThenLiveProvider

**File**: `src/tw_signal_engine/market_data/backfill_provider.py`

Composite provider for **mid-session startup**. Solves the problem: "the engine starts at 10:30 AM but needs state from 09:00 AM."

**Two-phase approach**:

1. **Phase 1 (Backfill)**: Replays archived file ticks from market open up to a cutover point (current wall-clock time minus 30-second overlap)
2. **Phase 2 (Live)**: Switches to Redis live stream, deduplicating ticks by `(symbol, match_time_str)` tuple during the overlap window

```python
class BackfillThenLiveProvider(MarketDataProvider):
    def __init__(
        self,
        file_provider: FileReplayProvider,
        redis_provider: RedisLiveProvider,
        cutover_time_str: int,  # match_time_str at switch point
    ): ...
```

**Why the 30-second overlap**: Prevents gaps at the cutover boundary. During the overlap, both file and live ticks may produce the same events — the dedup set ensures each `(symbol, time)` pair is yielded exactly once.

**When to use**: Starting the live engine after market open. Activated via `--backfill` flag in `run_live.py`.

---

## 3. Session Hooks

**File**: `src/tw_signal_engine/replay/session_hooks.py`

Hooks allow external consumers (web API, snapshot writers, logging) to observe engine events without modifying the core loop.

```python
@dataclass
class SessionHooks:
    on_tick: Callable[[MarketTick, IndexData], None] | None = None
    on_screening: Callable[[str, str, bool], None] | None = None
    on_signal: Callable[[str, str, bool], None] | None = None
    on_entry: Callable[[str, EntryTrade], None] | None = None
    on_exit: Callable[[str, str, TradeRecord], None] | None = None
    on_minute: Callable[[int], None] | None = None
    on_dashboard_snapshot: Callable[..., None] | None = None
```

**Design principles**:
- All callbacks are optional (default `None`)
- Null-checked at each call site → zero overhead when hooks not set
- Callbacks run synchronously in the main loop (no async, no threads)
- The web server's `LiveState` class uses hooks to capture state from the engine thread

**Hook invocation points in `replay_session.py`**:

| Hook | Fires when |
|---|---|
| `on_tick` | After index calc for each tick |
| `on_screening` | After group/single screening evaluation |
| `on_signal` | After Signal A/B evaluation |
| `on_entry` | After a position is opened |
| `on_exit` | After a position is closed |
| `on_minute` | When `match_time_str` crosses a minute boundary |
| `on_dashboard_snapshot` | When a dashboard snapshot is built (at minute boundaries) |

---

## 4. Data Flow Diagrams

### Batch Replay (existing)

```
TSEQuote + OTCQuote files
    → FileReplayProvider.iterate_ticks()
    → replay_session.py main loop
    → CSV reports (order_log, report_trades, report_summary)
```

### Paced Replay (dashboard dev)

```
TSEQuote + OTCQuote files
    → FileReplayProvider
    → PacedReplayProvider (adds wall-clock delays)
    → replay_session.py main loop
    → SessionHooks → LiveState → FastAPI/WebSocket → Dashboard
```

### Live Mode (production)

```
Redis Pub/Sub (192.168.100.130:6379)
    → RedisLiveProvider (listener thread → queue → main thread)
    → replay_session.py main loop
    → SessionHooks → LiveState → FastAPI/WebSocket → Dashboard
    → CSV reports
```

### Mid-Session Startup

```
TSEQuote + OTCQuote files (backfill phase)
    → FileReplayProvider (up to cutover point)
    ──then──
Redis Pub/Sub (live phase, with dedup)
    → RedisLiveProvider
    → replay_session.py main loop (continuous, no restart)
```

---

## 5. CLI Entry Points

### `run_daily_replay` — Batch Replay

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date 20260129 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

Optional flags:
- `--paced` — enable wall-clock pacing
- `--speed 2.0` — replay speed multiplier (requires `--paced`)
- `--snapshots` — generate Parquet snapshots for replay mode

### `run_live` — Live Trading Session

```bash
uv run python -m tw_signal_engine.cli.run_live \
  --date 20260324 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

Optional flags:
- `--redis-host` / `--redis-port` — override config file Redis settings
- `--backfill` — enable mid-session backfill from files before switching to live

### `run_server` — Web Server with Engine

```bash
uv run python -m tw_signal_engine.cli.run_server \
  --date 20260324 \
  --mode live \
  --host 0.0.0.0 \
  --port 8000
```

Modes:
- `--mode live` — starts engine with `RedisLiveProvider`, serves state via API
- `--mode replay` — loads Parquet snapshots, serves via `ReplayManager`

---

## 6. Key Design Decisions

### Why a queue bridge instead of async?

The engine is single-threaded and deterministic by design. Introducing `asyncio` would require rewriting the main loop and all state management. The `queue.Queue` bridge keeps the proven single-threaded model while cleanly separating the I/O concern (Redis listener) from the processing concern (main loop).

### Why pair Trade/Depth instead of processing separately?

The existing replay file format interleaves Trade and Depth lines for the same symbol at the same timestamp. The `MarketTick` dataclass carries both trade and depth data. Processing them as a pair maintains consistency with the file replay path and ensures the engine sees the same data shape regardless of source.

### Why integer prices (× 10,000)?

Floating-point arithmetic introduces drift that can cause signal threshold comparisons to produce different results across runs. Integer arithmetic is exact. Conversion to float happens only at the API boundary (JSON serialization for the dashboard).

### Why `match_time_str` as an integer?

Integers sort naturally, compare cheaply, and have no timezone ambiguity. The format `HMMSS000000` (e.g., `91500000000` for 09:15:00.000000) provides microsecond precision. `match_time_us` (microseconds since midnight) is derived from it for rolling-window calculations.

---

## 7. Testing and Verification

### Unit Tests

**File**: `tests/unit/test_providers.py`

| Test | What it verifies |
|---|---|
| `TestFileReplayProvider` | File-based replay produces correct `MarketTick` sequence |
| `TestPacedReplayProvider` | Timing delays are applied correctly at various speeds |
| `TestRedisLiveProvider::test_handle_trade_depth_pairing` | Trade + Depth lines are paired into a single `MarketTick` |
| `TestRedisLiveProvider::test_handle_trade_without_depth` | Pending Trade is flushed when next Trade arrives (no Depth) |
| `TestRedisLiveProvider::test_status_code_filter` | Non-normal trades (`func_code != '0'`) are filtered out |
| `TestBackfillThenLiveProvider::test_file_then_live` | Composite provider switches from file to live at cutover |
| `TestBackfillThenLiveProvider::test_dedup_overlap` | Duplicate ticks at cutover boundary are deduplicated |

**Run tests**:
```bash
uv run pytest tests/unit/test_providers.py -v
```

### Integration Testing with Real Redis

To verify against a live Redis server (requires access to `192.168.100.130`):

1. Start the engine in live mode during market hours:
   ```bash
   uv run python -m tw_signal_engine.cli.run_live --date $(date +%Y%m%d) ...
   ```
2. Observe tick count incrementing in logs
3. After session, compare trade outputs with batch replay of the same day's archived files

### Parity Testing

The gold standard for correctness: run the same day through both `FileReplayProvider` and `RedisLiveProvider` (by recording live ticks to a file), then diff the trade outputs. They must be identical.

```bash
# Step 1: Run batch replay
uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260324 ...

# Step 2: Run live session (during market hours), outputs go to separate dir

# Step 3: Diff outputs
diff exec/output/replay/order_log_20260324.csv exec/output/live/order_log_20260324.csv
```

### Edge Case Testing

| Scenario | How to test | Expected behavior |
|---|---|---|
| Redis connection lost | Kill Redis mid-session | Auto-reconnect after `reconnect_delay`, no crash |
| Empty tick filter | Start with no symbols in universe | Graceful termination with log message |
| Invalid Trade/Depth line | Publish malformed CSV to Redis | Line skipped silently, engine continues |
| Out-of-order messages | Publish ticks with decreasing timestamps | Reorder buffer sorts within 100ms window |
| Mid-session startup | Start engine at 10:30 with `--backfill` | Backfill from file, switch to live, no gaps |
| `Ctrl-C` during live | Send SIGINT | Graceful shutdown: close Redis, finalize positions, write reports |

### Linting and Type Checking

```bash
uv run ruff check src tests
uv run mypy src
```

---

## 8. File Map

| File | Purpose |
|---|---|
| `src/tw_signal_engine/market_data/providers.py` | `MarketDataProvider` ABC |
| `src/tw_signal_engine/market_data/file_replay_provider.py` | File-based replay provider |
| `src/tw_signal_engine/market_data/paced_replay_provider.py` | Wall-clock pacing wrapper |
| `src/tw_signal_engine/market_data/redis_live_provider.py` | Redis Pub/Sub live provider |
| `src/tw_signal_engine/market_data/backfill_provider.py` | Backfill-then-live composite |
| `src/tw_signal_engine/replay/session_hooks.py` | Event callback definitions |
| `src/tw_signal_engine/replay/replay_session.py` | Main event loop (accepts any provider) |
| `src/tw_signal_engine/config/strategy_config.py` | `LiveConfig` model |
| `src/tw_signal_engine/cli/run_live.py` | Live mode CLI entry point |
| `src/tw_signal_engine/cli/run_server.py` | Web server CLI entry point |
| `tests/unit/test_providers.py` | Provider unit tests |
