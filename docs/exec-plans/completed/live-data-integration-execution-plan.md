# Live Data Integration — Execution Plan

**Branch**: `feat/live-data-integration`
**Based on**: [Research doc](../../references/legacy/research/live-data-integration-research.md)
**Date**: 2026-03-24

---

## Overview

Transform `tw_signal_engine` from a replay-only batch engine into a dual-mode engine that can also consume a live Redis market stream and serve real-time state via a web API. The core processing logic (screening → signals → execution → exits) stays identical regardless of data source.

**Guiding principle**: The main event loop in `replay_session.py:229` already consumes an `Iterator[MarketTick]`. All changes upstream of that iterator are about *where ticks come from*; everything downstream is unchanged.

---

## Phase 1: MarketDataProvider Abstraction **[COMPLETED]**

**Goal**: Extract the tick source from the main loop behind a clean interface, so file replay, paced replay, and Redis live can all plug in.

### 1.1 Define the provider protocol

**New file**: `src/tw_signal_engine/market_data/providers.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator
from tw_signal_engine.records.market_event_records import MarketTick

class MarketDataProvider(ABC):
    """Abstract source of MarketTick events."""

    @abstractmethod
    def iterate_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects in chronological order."""
```

This is intentionally minimal. The provider is responsible for:
- Producing `MarketTick` objects (same dataclass already used everywhere)
- Chronological ordering
- Applying `prev_limit_up` and `volatility_pause` enrichment

### 1.2 Wrap existing file replay as `FileReplayProvider`

**New file**: `src/tw_signal_engine/market_data/file_replay_provider.py`

Extract the current `merge_market_streams()` call site into a provider:

```python
class FileReplayProvider(MarketDataProvider):
    def __init__(
        self,
        otc_date: str,
        tse_date: str,
        data_dir: str,
        tick_filter: set[str] | None,
        prev_day_limit_up: dict[str, bool] | None,
        num_tracker: NumTracker | None = None,
    ) -> None: ...

    def iterate_ticks(self) -> Iterator[MarketTick]:
        yield from merge_market_streams(
            "OTC", self.otc_date, "TSE", self.tse_date,
            data_dir=self.data_dir,
            tick_filter=self.tick_filter,
            prev_day_limit_up=self.prev_day_limit_up,
            num_tracker=self.num_tracker,
        )
```

This is a pure refactor — zero behavior change. The existing `merge_market_streams` and `iterate_market_file` stay as-is.

### 1.3 Refactor `replay_session.py` to accept a provider

**Modify**: `src/tw_signal_engine/replay/replay_session.py`

Change the main loop from:

```python
for tick in merge_market_streams("OTC", trade_date, "TSE", trade_date, ...):
```

to:

```python
for tick in provider.iterate_ticks():
```

Where `provider` is either passed in or defaulted to `FileReplayProvider`. The function signature becomes:

```python
def run_daily_replay(
    trade_date: str,
    ...
    provider: MarketDataProvider | None = None,  # NEW
) -> list[TradeRecord]:
```

If `provider is None`, construct `FileReplayProvider` from the existing args (backward compatible).

### 1.4 Verification

- `uv run pytest tests -q` — all existing tests pass unchanged
- Run a daily replay and diff the output against a known-good run — results must be bit-identical

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/market_data/providers.py` | **New** — ABC definition |
| `src/tw_signal_engine/market_data/file_replay_provider.py` | **New** — wraps `merge_market_streams` |
| `src/tw_signal_engine/replay/replay_session.py` | **Edit** — accept provider, use it in loop |
| `src/tw_signal_engine/market_data/__init__.py` | **Edit** — export new classes |

---

## Phase 2: Paced Replay Provider **[COMPLETED]**

**Goal**: Add wall-clock pacing to file replay so the engine can simulate live timing for dashboard development and testing.

### 2.1 Implement `PacedReplayProvider`

**New file**: `src/tw_signal_engine/market_data/paced_replay_provider.py`

```python
class PacedReplayProvider(MarketDataProvider):
    """Wraps FileReplayProvider with wall-clock delays to simulate live pacing."""

    def __init__(
        self,
        inner: FileReplayProvider,
        speed: float = 1.0,  # 1.0 = real-time, 2.0 = 2x faster
    ) -> None: ...

    def iterate_ticks(self) -> Iterator[MarketTick]:
        start_wall = None
        start_data = None
        for tick in self.inner.iterate_ticks():
            data_time_sec = tick.match_time_us / 1_000_000
            if start_wall is None:
                start_wall = time.time()
                start_data = data_time_sec
            else:
                target_delay = (data_time_sec - start_data) / self.speed
                actual_delay = time.time() - start_wall
                sleep_needed = target_delay - actual_delay
                if sleep_needed > 0:
                    time.sleep(sleep_needed)
            yield tick
```

Pattern copied from SS's `FileReplayDataProvider` (research doc §3.1). Uses the same time-difference/speed-ratio approach.

### 2.2 Wire into CLI

**Modify**: `src/tw_signal_engine/cli/run_daily_replay.py`

Add optional flags:

```
--paced          Enable wall-clock pacing (simulates live timing)
--speed 2.0      Replay speed multiplier (default 1.0)
```

When `--paced` is set, wrap the `FileReplayProvider` with `PacedReplayProvider` before passing to `run_daily_replay`.

### 2.3 Verification

- Run with `--paced --speed 60.0` — a full day should complete in ~2-3 minutes
- Signal/trade outputs must match non-paced run exactly (same ticks, same order)

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/market_data/paced_replay_provider.py` | **New** |
| `src/tw_signal_engine/cli/run_daily_replay.py` | **Edit** — add `--paced`, `--speed` flags |

---

## Phase 3: Redis Live Provider **[COMPLETED]**

**Goal**: Consume live market data from Redis Pub/Sub and produce `MarketTick` objects for the engine.

### 3.1 Add `redis` dependency

```bash
uv add redis
```

### 3.2 Extend config for live mode

**Modify**: `src/tw_signal_engine/config/strategy_config.py`

Add a new config model:

```python
class LiveConfig(BaseModel):
    enabled: bool = False
    redis_host: str = "192.168.100.130"
    redis_port: int = 6379
    redis_db: int = 0
    socket_timeout: int = 5
    reconnect_delay: float = 5.0
    reorder_buffer_ms: int = 100  # out-of-order tolerance
```

Add to `NormalizedStrategyConfig`:

```python
class NormalizedStrategyConfig(BaseModel):
    ...
    live: LiveConfig = LiveConfig()
```

### 3.3 Implement `RedisLiveProvider`

**New file**: `src/tw_signal_engine/market_data/redis_live_provider.py`

Architecture (threaded queue model from research doc §7.2, option a):

```
Redis Pub/Sub listener thread
    │  subscribe to channels in tick_filter
    │  on_message → parse_trade_line() → queue.put(MarketTick)
    ▼
queue.Queue(maxsize=10000)
    │
    ▼
RedisLiveProvider.iterate_ticks()
    │  queue.get(timeout=1.0) in main thread
    │  optional reorder buffer (50-100ms window)
    ▼
MarketTick to main loop
```

Key implementation details:

```python
class RedisLiveProvider(MarketDataProvider):
    def __init__(
        self,
        config: LiveConfig,
        tick_filter: set[str],
        prev_day_limit_up: dict[str, bool] | None = None,
    ) -> None:
        self._config = config
        self._tick_filter = tick_filter
        self._prev_day_limit_up = prev_day_limit_up or {}
        self._queue: queue.Queue[MarketTick | None] = queue.Queue(maxsize=10000)
        self._stop_event = threading.Event()
        self._num_tracker = NumTracker()

    def iterate_ticks(self) -> Iterator[MarketTick]:
        listener = threading.Thread(target=self._listen, daemon=True)
        listener.start()
        try:
            while not self._stop_event.is_set():
                try:
                    tick = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                if tick is None:  # poison pill
                    break
                yield tick
        finally:
            self._stop_event.set()

    def _listen(self) -> None:
        """Background thread: subscribe to Redis and push ticks to queue."""
        # Auto-reconnect loop with backoff (from SS pattern)
        while not self._stop_event.is_set():
            try:
                r = redis.Redis(
                    host=self._config.redis_host,
                    port=self._config.redis_port,
                    db=self._config.redis_db,
                    socket_timeout=self._config.socket_timeout,
                )
                pubsub = r.pubsub()
                pubsub.subscribe(*self._tick_filter)
                for message in pubsub.listen():
                    if self._stop_event.is_set():
                        break
                    if message["type"] != "message":
                        continue
                    line = message["data"].decode("utf-8")
                    self._handle_line(line, channel=message["channel"])
            except redis.ConnectionError:
                if not self._stop_event.is_set():
                    time.sleep(self._config.reconnect_delay)

    def _handle_line(self, line: str, channel: bytes) -> None:
        """Parse a single Trade or Depth line from Redis."""
        # Redis sends Trade and Depth lines on the same channel
        # Buffer current Trade, pair with next Depth if available
        # Use the same parse_trade_line() from parse_format6_replay_rows.py
        ...
```

**Critical design decisions**:

1. **Same parser**: Reuse `parse_trade_line()` from `parse_format6_replay_rows.py` — the Redis messages use the identical CSV format (research doc §2.3, §9).

2. **Trade/Depth pairing**: Redis sends Trade and Depth as separate messages on the same channel. Buffer the last Trade line per symbol and pair it with the next Depth line, mirroring `iterate_market_file.py`'s pairing logic.

3. **Main thread stays single-threaded**: The `queue.Queue` acts as the bridge. The main loop in `replay_session.py` is unchanged — it still iterates `MarketTick` objects one at a time.

4. **Enrichment**: Apply `prev_limit_up` and `volatility_pause` (via `NumTracker`) the same way `merge_market_streams` does.

5. **Reorder buffer**: Optional 100ms buffer to handle out-of-order Pub/Sub messages. Collects ticks, sorts by `match_time_str`, yields when the buffer window expires.

### 3.4 Add `run_live` CLI entry point

**New file**: `src/tw_signal_engine/cli/run_live.py`

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Run live trading session")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--config", default="./cfg/parameter.cfg")
    parser.add_argument("--data-dir", default="./data/")
    parser.add_argument("--files-dir", default="./files/")
    parser.add_argument("--group-file", default="./files/group.csv")
    parser.add_argument("--redis-host", default=None)
    parser.add_argument("--redis-port", type=int, default=None)
    args = parser.parse_args()

    # Load config, reference data, history (same as replay)
    # Build tick_filter (same as replay)
    # Create RedisLiveProvider with tick_filter
    # Call run_daily_replay(..., provider=redis_provider)
```

### 3.5 Graceful shutdown

- `Ctrl-C` sets `stop_event`, which drains the queue and closes positions via `_finalize_open_positions`.
- Register `signal.SIGINT` / `signal.SIGTERM` handlers in the CLI.

### 3.6 Verification

- Unit test: mock Redis with `fakeredis`, publish known Trade/Depth lines, verify `MarketTick` output matches `parse_trade_line` directly.
- Integration test: run `RedisLiveProvider` against a real Redis server, verify ticks appear with correct fields.
- Parity test: record a live session's ticks to a file, replay with `FileReplayProvider`, verify identical processing results.

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/market_data/redis_live_provider.py` | **New** |
| `src/tw_signal_engine/cli/run_live.py` | **New** |
| `src/tw_signal_engine/config/strategy_config.py` | **Edit** — add `LiveConfig` |
| `src/tw_signal_engine/config/normalize_strategy_config.py` | **Edit** — parse `[Live]` section |
| `pyproject.toml` | **Edit** — add `redis` dependency |

---

## Phase 4: Event Hooks for Live State Observation **[COMPLETED]**

**Goal**: Allow external consumers (web API, Parquet snapshots) to observe engine state without modifying the core loop.

### 4.1 Define event callbacks

**New file**: `src/tw_signal_engine/replay/session_hooks.py`

```python
@dataclass
class SessionHooks:
    """Optional callbacks invoked by the replay/live session at key points."""

    on_tick: Callable[[MarketTick, IndexData], None] | None = None
    on_screening: Callable[[str, str, bool], None] | None = None  # symbol, match_type, qualified
    on_signal: Callable[[str, str, bool], None] | None = None     # symbol, signal_type, triggered
    on_entry: Callable[[str, EntryTrade], None] | None = None     # symbol, entry
    on_exit: Callable[[str, str, TradeRecord], None] | None = None  # symbol, cause, trade
    on_minute: Callable[[int], None] | None = None                # match_time_str at minute boundary
```

### 4.2 Wire hooks into `replay_session.py`

**Modify**: `src/tw_signal_engine/replay/replay_session.py`

Add `hooks: SessionHooks | None = None` parameter to `run_daily_replay`. Insert callback invocations at the corresponding points in the main loop:

```python
# After index calc
if hooks and hooks.on_tick:
    hooks.on_tick(tick, idx)

# After entry execution
if hooks and hooks.on_entry:
    hooks.on_entry(symbol, pos.open_trades[symbol])

# After exit
if hooks and hooks.on_exit and cause:
    hooks.on_exit(symbol, cause, completed_trades[-1])

# At minute boundaries (detect when match_time_str crosses a minute)
if hooks and hooks.on_minute and _crossed_minute(prev_time, tick.match_time_str):
    hooks.on_minute(tick.match_time_str)
```

The hooks are null-checked, so existing replay mode has zero overhead.

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/replay/session_hooks.py` | **New** |
| `src/tw_signal_engine/replay/replay_session.py` | **Edit** — add hooks parameter + invocations |

---

## Phase 5: Parquet Snapshot Generation **[COMPLETED]**

**Goal**: Serialize per-minute engine state to Parquet for time-travel replay.

### 5.1 Implement snapshot serializer

**New file**: `src/tw_signal_engine/reporting/snapshot_writer.py`

Uses `SessionHooks.on_minute` to capture state at each minute boundary:

```python
class SnapshotWriter:
    """Captures per-minute state snapshots and writes to Parquet."""

    def __init__(self, date: str, output_dir: str = "./cache/replay/") -> None:
        self.date = date
        self.output_dir = output_dir
        self._rows: list[dict] = []

    def on_minute(
        self,
        match_time_str: int,
        strong_group: StrongGroupEvaluator,
        signal_a_map: dict[str, SignalAState],
        signal_b_map: dict[str, SignalBState],
        pos: PositionState,
        market_gate: MarketGate,
    ) -> None:
        """Capture current state as a snapshot row."""
        minutes = _time_str_to_minutes(match_time_str)
        self._rows.append({
            "timestamp": minutes,
            "time_str": _minutes_to_hhmm(minutes),
            "market_time": _time_str_to_hhmmss(match_time_str),
            "strong_groups": json.dumps(self._serialize_groups(strong_group)),
            "signals": json.dumps(self._serialize_signals(signal_a_map, signal_b_map)),
            "positions": json.dumps(self._serialize_positions(pos)),
            "market_disabled": market_gate.market_disabled,
        })

    def finalize(self) -> Path:
        """Write all snapshots to Parquet."""
        df = pd.DataFrame(self._rows)
        path = Path(self.output_dir) / f"ReplayData_{self.date}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        return path
```

### 5.2 Schema

Follow SS's schema (research doc §5) but extended with SE-specific fields:

| Column | Type | Description |
|---|---|---|
| `timestamp` | int | Minutes since midnight (540 = 09:00) |
| `time_str` | str | `"HH:MM"` |
| `market_time` | str | `"HH:MM:SS"` |
| `strong_groups` | str (JSON) | Group screening state: ranked groups + member details |
| `signals` | str (JSON) | Active Signal A/B states per symbol |
| `positions` | str (JSON) | Open positions + PnL |
| `market_disabled` | bool | Market gate status |
| `completed_trades` | str (JSON) | Trades completed since last snapshot |

### 5.3 Signal records Parquet

**New file**: `src/tw_signal_engine/reporting/signal_snapshot_writer.py`

Uses `SessionHooks.on_signal` and `on_entry` to accumulate signal records:

```python
class SignalSnapshotWriter:
    def on_entry(self, symbol: str, trade: EntryTrade) -> None: ...
    def on_exit(self, symbol: str, cause: str, record: TradeRecord) -> None: ...
    def finalize(self) -> Path:
        # Write ReplaySignals_{date}.parquet
```

### 5.4 Wire into replay via CLI flag

**Modify**: `src/tw_signal_engine/cli/run_daily_replay.py`

```
--snapshots       Enable per-minute Parquet snapshot generation
--snapshot-dir    Output directory (default: ./cache/replay/)
```

When `--snapshots` is set, create `SnapshotWriter` + `SignalSnapshotWriter`, wire them into `SessionHooks`, pass hooks to `run_daily_replay`.

### 5.5 Verification

- Run replay with `--snapshots` on a known date
- Load the Parquet, verify timestamp coverage (09:00–13:30)
- Verify group/signal JSON can be round-tripped

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/reporting/snapshot_writer.py` | **New** |
| `src/tw_signal_engine/reporting/signal_snapshot_writer.py` | **New** |
| `src/tw_signal_engine/cli/run_daily_replay.py` | **Edit** — add `--snapshots` flag |

### Dependencies

- `pyarrow` (for Parquet writing) — `uv add pyarrow`
- `pandas` — `uv add pandas`

---

## Phase 6: FastAPI Web Server **[COMPLETED]**

**Goal**: Serve engine state via HTTP API and WebSocket for dashboard consumption.

### 6.1 Add dependencies

```bash
uv add fastapi uvicorn python-socketio
```

### 6.2 Implement server

**New file**: `src/tw_signal_engine/server/app.py`

```python
from fastapi import FastAPI
import socketio

app = FastAPI(title="tw_signal_engine API")
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)
```

### 6.3 API endpoints

**New file**: `src/tw_signal_engine/server/routes.py`

Following SS's dual-mode pattern (research doc §4.2):

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/status` | GET | Engine mode (live/replay), market gate, tick count |
| `GET /api/screened-groups` | GET | Current strong-group screening results |
| `GET /api/signals` | GET | Active + expired signal states |
| `GET /api/positions` | GET | Open positions with current P&L |
| `GET /api/config` | GET | Current config (sanitized) |
| `POST /api/replay/jump` | POST | Time-travel to minute (replay mode, Parquet) |
| `GET /api/replay/status` | GET | Replay readiness, time range |

All endpoints return from the same state regardless of live/replay mode.

### 6.4 WebSocket signal push

Using `SessionHooks`:

```python
def on_signal(symbol: str, signal_type: str, triggered: bool) -> None:
    if triggered:
        asyncio.run_coroutine_threadsafe(
            sio.emit("new_signal", {"symbol": symbol, "type": signal_type}),
            loop,
        )
```

Same pattern as SS (research doc §4.3).

### 6.5 Replay manager (Parquet time-travel)

**New file**: `src/tw_signal_engine/server/replay_manager.py`

```python
class ReplayManager:
    def __init__(self, date: str, snapshot_dir: str = "./cache/replay/") -> None:
        self._df = pd.read_parquet(f"{snapshot_dir}/ReplayData_{date}.parquet")
        self._current_idx = 0

    def is_ready(self) -> bool: ...
    def jump_to_time(self, time_str: str) -> dict: ...
    def get_current_snapshot(self) -> dict: ...
```

### 6.6 Server CLI entry point

**New file**: `src/tw_signal_engine/cli/run_server.py`

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Run signal engine web server")
    parser.add_argument("--date", required=True)
    parser.add_argument("--mode", choices=["live", "replay"], default="replay")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.mode == "live":
        # Start engine with RedisLiveProvider in background thread
        # FastAPI serves state via hooks
    else:
        # Load Parquet snapshots
        # Serve via ReplayManager

    uvicorn.run(socket_app, host=args.host, port=args.port)
```

### 6.7 Verification

- Start server in replay mode, hit `/api/screened-groups` — verify JSON response
- Start server, POST to `/api/replay/jump` with `{"time": "10:30"}` — verify snapshot changes
- WebSocket test: connect, verify `new_signal` events fire during paced replay

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/server/__init__.py` | **New** |
| `src/tw_signal_engine/server/app.py` | **New** |
| `src/tw_signal_engine/server/routes.py` | **New** |
| `src/tw_signal_engine/server/replay_manager.py` | **New** |
| `src/tw_signal_engine/cli/run_server.py` | **New** |
| `pyproject.toml` | **Edit** — add fastapi, uvicorn, python-socketio |

---

## Phase 7: Backfill on Startup **[COMPLETED]**

**Goal**: When the engine starts mid-session in live mode, catch up on missed ticks.

### 7.1 Implement backfill logic

**New file**: `src/tw_signal_engine/market_data/backfill_provider.py`

```python
class BackfillThenLiveProvider(MarketDataProvider):
    """Replays today's file up to 'now', then switches to Redis live."""

    def __init__(
        self,
        file_provider: FileReplayProvider,
        redis_provider: RedisLiveProvider,
        cutover_time_str: int,  # switch point
    ) -> None: ...

    def iterate_ticks(self) -> Iterator[MarketTick]:
        # Phase 1: yield file ticks up to cutover_time_str
        for tick in self.file_provider.iterate_ticks():
            if tick.match_time_str >= self.cutover_time_str:
                break
            yield tick
        # Phase 2: switch to Redis live
        yield from self.redis_provider.iterate_ticks()
```

The cutover point is computed as `current wall-clock time → match_time_str` minus a small overlap window (e.g., 30 seconds) to avoid missing ticks during the switch.

### 7.2 Verification

- Start mid-session with a partial-day file + Redis mock
- Verify no gaps or duplicate ticks at the cutover boundary
- Verify screening/signal state is correct (same as full-day replay up to cutover point)

### Files touched

| File | Action |
|---|---|
| `src/tw_signal_engine/market_data/backfill_provider.py` | **New** |
| `src/tw_signal_engine/cli/run_live.py` | **Edit** — use `BackfillThenLiveProvider` when file exists |

---

## Dependency Summary

| Phase | New Packages |
|---|---|
| 1-2 | None |
| 3 | `redis` |
| 5 | `pyarrow`, `pandas` |
| 6 | `fastapi`, `uvicorn`, `python-socketio` |

---

## Execution Order & Dependencies

```
Phase 1 (Provider abstraction)
    │
    ├─→ Phase 2 (Paced replay)     [independent]
    │
    └─→ Phase 3 (Redis live)
            │
            └─→ Phase 7 (Backfill)

Phase 4 (Event hooks)
    │
    ├─→ Phase 5 (Parquet snapshots)
    │
    └─→ Phase 6 (FastAPI server)
```

Phases 1 and 4 are independent and can be done in parallel. Within each dependency chain, phases must be sequential.

**Recommended PR sequence**:
1. PR #1: Phase 1 (provider abstraction) — pure refactor, safe to merge early
2. PR #2: Phase 4 (event hooks) — small, additive, no behavior change
3. PR #3: Phase 2 (paced replay) — small feature, useful for dev/testing
4. PR #4: Phase 3 (Redis live) — the core live feature
5. PR #5: Phase 5 (Parquet snapshots)
6. PR #6: Phase 6 (FastAPI server)
7. PR #7: Phase 7 (Backfill)

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| **Replay parity regression** | Phase 1 is a pure refactor. Run golden parity tests before/after. |
| **Threading bugs in Redis provider** | Queue-based bridge keeps main loop single-threaded. Only the listener thread touches Redis. |
| **Price precision loss** | All providers yield `MarketTick` with `int × 10000` prices. No float conversion. |
| **Out-of-order Redis messages** | Optional reorder buffer in Phase 3 (configurable `reorder_buffer_ms`). |
| **Memory in live mode** | Same as replay (all symbol state in dicts). Monitor with `tracemalloc` for ~2000 symbols. |
| **Backfill gap at cutover** | 30-second overlap window + dedup by `(symbol, match_time_str)`. |

---

## What This Plan Does NOT Cover

- Frontend/dashboard UI (separate repo, consumes the API)
- Signal parity verification between SS and SE (tracked separately)
- Historical multi-day live recording/playback
- Authentication/authorization on the API
- Production deployment (Docker, systemd, monitoring)
