# Research: Live Data Integration from StockScreening

**Source**: `TWSE-backtest/StockScreening` (branch `website_test`)
**Target**: `signal-live-data/src/tw_signal_engine/`
**Date**: 2026-03-24

---

## 1. Executive Summary

The StockScreening dashboard (hereafter "SS") already implements three live-data capabilities that `tw_signal_engine` (hereafter "SE") lacks:

| Capability | SS Implementation | SE Status |
|---|---|---|
| **Live Redis market stream** | Redis Pub/Sub → background thread → state update | Not implemented (replay-only) |
| **Replay with timing** | `FileReplayDataProvider` with wall-clock pacing; `ReplayManager` with Parquet time-jump | Text file sequential read, no pacing |
| **Server-side replay API + Parquet** | FastAPI endpoints + Parquet snapshots per minute | CLI-only, CSV outputs |

This document maps each subsystem in detail so a future integration can reuse the proven patterns and data formats while keeping SE's deterministic, typed, pure-Python architecture intact.

---

## 2. Redis Live Market Stream

### 2.1 Architecture in SS

```
Redis Server (192.168.100.130:6379)
    │  Pub/Sub channels = one per stock symbol
    ▼
RedisDataProvider.listen()          ← blocking loop, auto-reconnect
    │  message['data'].decode('utf-8') → raw CSV line
    ▼
data_worker() callback: on_message()
    ├─ Trade line → _process_trade_message()
    │     parse price (÷10000), tick_vol, timestamp
    │     → mgr.process_redis_message(t, code, price, tick_vol)
    │     → signal_tracker.process_trade(...)
    └─ Depth line → _process_depth_message()
          parse best bid/ask from "BID:5,P*V,..." format
          → mgr.process_depth_message(t, code, bid, ask)
          → signal_tracker.process_depth(...)
```

**Key files**:
- `SS/services/market_data_provider.py` — abstract `MarketDataProvider` + `RedisDataProvider`, `FileReplayDataProvider`, `MockDataProvider`
- `SS/services/background.py` — `data_worker()`, `screening_worker()`, `signal_snapshot_worker()`
- `SS/services/message_handler.py` — `parse_trade_line()`, `parse_depth_line()`, `apply_trade_to_state()`, `apply_depth_to_state()`

### 2.2 Redis Connection Details

```python
# SS/core/config.py
REDIS_HOST = '192.168.100.130'
REDIS_PORT = 6379
```

- Channels: one per stock code (e.g., `"2330"`, `"2317"`)
- Each message is a single CSV line (Trade or Depth)
- Connection uses `redis.Redis(host, port, db=0, socket_timeout=5)`
- Listener uses `pubsub.get_message(timeout=1.0)` in a loop
- Auto-reconnect on `ConnectionError` with 5-second backoff

### 2.3 Message Formats

**Trade line** (7+ fields):
```
Trade,{symbol},{time},{func_code},{price},{volume},{total_vol},{seq}
```
- `time`: `HHMMSSuuuuuu` (11-12 digits, microsecond precision)
- `func_code`: `'0'` = normal trade (only accepted), `'1'` = simulated, `'2'` = opening auction, etc.
- `price`: integer × 10000 (same as SE convention)
- `volume`: single-trade tick volume (not cumulative)

**Depth line** (variable fields):
```
Depth,{symbol},{time},BID:5,{p1*v1},{p2*v2},...,ASK:5,{p1*v1},{p2*v2},...
```
- Prices in `p*v` pairs, price is integer × 10000
- `BID:5` / `ASK:5` are sentinel tags; first price after each is best bid/ask

**Important**: This is the *same file format* that SE parses in `parse_format6_replay_rows.py`. The Redis stream publishes lines identical to what's in `TSEQuote.YYYYMMDD` / `OTCQuote.YYYYMMDD` files. The key difference is that in live mode, lines arrive one at a time via Pub/Sub, while in replay mode they're read sequentially from disk.

### 2.4 Mapping to SE's Existing Parser

| SS field | SE field | Notes |
|---|---|---|
| `price / 10000.0` (float) | `match.price` (int, × 10000) | SE keeps integer; SS converts to float |
| `tick_vol` | `match.qty` | Same semantics |
| `HHMMSSuuuuuu` parsed to `datetime` | `match_time_str` (int) + `match_time_us` (int) | SE uses raw integer time |
| `best_bid / 10000.0` | `bid[0].price` (int) | SE keeps 5 levels as int |
| `best_ask / 10000.0` | `ask[0].price` (int) | SE keeps 5 levels as int |

SE's `parse_format6_replay_rows.py` already handles the exact same CSV format. For live integration, the only change needed is a new *source* that feeds lines from Redis instead of a file.

---

## 3. Replay with Timing Behavior

SS supports two replay modes, controlled by config flags.

### 3.1 Sequential Playback (`FileReplayDataProvider`)

**Config**: `DATA_SOURCE_TYPE = 'FILE'`, `REPLAY_MODE = False`

Reads the quote file line-by-line and inserts wall-clock delays to simulate real-time pacing:

```python
# Simplified from SS/services/market_data_provider.py:149-203
class FileReplayDataProvider(MarketDataProvider):
    def listen(self, callback, stop_event):
        with open(self.file_path, 'r') as f:
            for line in f:
                # Parse timestamp from line
                current_data_time_sec = parse_hhmmssuuuuuu(parts[2])

                if self.simulation_start_wall_time is None:
                    self.simulation_start_wall_time = time.time()
                    self.simulation_start_data_time = current_data_time_sec
                else:
                    target_delay = (current_data_time_sec - self.simulation_start_data_time) / REPLAY_SPEED
                    actual_delay = time.time() - self.simulation_start_wall_time
                    sleep_needed = target_delay - actual_delay
                    if sleep_needed > 0:
                        time.sleep(sleep_needed)

                callback(line)  # Same handler as live mode
```

**Key design**: The callback is *identical* to live mode — no code branching. The provider abstraction handles timing.

**Speed control**: `REPLAY_SPEED = 1.0` (real-time), `2.0` (2× faster), etc.

### 3.2 Time-Jump Replay (`ReplayManager` + Parquet snapshots)

**Config**: `DATA_SOURCE_TYPE = 'FILE'`, `REPLAY_MODE = True`

This is a fundamentally different approach: instead of streaming lines, the system pre-computes minute-by-minute snapshots offline, stores them in Parquet, and serves them via API.

**Offline Phase** (`PrecomputeEngine`):
1. Load all quote lines into memory grouped by minute
2. Initialize `RealTimeManager` + `VWAPSignalTracker` (same classes as live mode)
3. For each minute (540=09:00 to 660=11:00):
   - Process all Trade/Depth lines using `apply_trade_to_state()` / `apply_depth_to_state()`
   - Run `calculate_screening_results()` + `update_qualified_stocks()`
   - Serialize screening results + signal states to JSON
   - Append snapshot row
4. Save as `cache/replay/ReplayData_{date}.parquet`
5. Save signals as `cache/replay/ReplaySignals_{date}.parquet`

**Online Phase** (`ReplayManager`):
1. Load Parquet into `pd.DataFrame`
2. On `jump_to_time("10:30")`: filter `df[df['timestamp'] <= target_min].iloc[-1]`
3. Deserialize JSON fields → return as API response
4. Restore `signal_tracker.active_signals` / `expired_signals` from snapshot

### 3.3 Implications for SE

SE's replay loop (`replay_session.py`) is deterministic and processes ticks one at a time. Two integration paths:

**Path A — Sequential pacing (simpler)**:
Add an optional `sleep` between ticks based on `match_time_str` differences, same pattern as `FileReplayDataProvider`. This would let SE simulate live timing without any architecture changes.

**Path B — Parquet snapshot generation**:
After SE's replay completes (or during it), serialize per-minute state snapshots into Parquet. This gives a time-travel API on top of SE's authoritative signal engine.

---

## 4. Server-Side Time-Travel Replay APIs

### 4.1 API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `GET /api/replay/status` | GET | Returns `{enabled, ready, building, progress, current_time, min_time, max_time}` |
| `POST /api/replay/jump` | POST | Body: `{time: "10:30"}` → jumps to that minute |
| `GET /api/replay/signals/{date}` | GET | All signals from `ReplaySignals_{date}.parquet` |
| `GET /api/replay/all-signals-history` | GET | Current replay date's full signal history |
| `GET /api/screened-groups` | GET | **Dual-mode**: returns snapshot in replay mode, real-time calculation in live mode |
| `GET /api/signals` | GET | Active + expired VWAP signals |
| `GET /api/signal-c` | GET | Signal C candidates (near-VWAP bounce) |
| `GET /api/vwap-watchlist` | GET | Top N groups' lead stocks with VWAP alert |
| `GET /api/config` | GET | System configuration including `replay_mode` flag |

### 4.2 Dual-Mode Pattern

The key architectural pattern is that **data endpoints are mode-transparent**: the same API returns data from either live or replay sources. The branching happens inside each handler:

```python
@app.get("/api/screened-groups")
def get_screened_groups():
    if replay_manager_instance and replay_manager_instance.is_ready():
        return replay_manager_instance.get_current_snapshot()  # Parquet snapshot
    else:
        return manager.calculate_screening_results()  # Real-time
```

This is valuable because the frontend doesn't need to know which mode is active.

### 4.3 WebSocket Signal Broadcasting

SS uses Socket.IO for real-time signal push:

```python
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

def on_signal_generated(signal: SignalRecord):
    asyncio.run_coroutine_threadsafe(
        sio.emit('new_signal', signal.to_dict()),
        _main_loop
    )
```

The `VWAPSignalTracker` accepts an `on_signal_generated` callback, which is set to the WebSocket emitter during initialization. Signals are pushed immediately as they fire.

### 4.4 Background Worker Threads

SS runs three daemon threads alongside the main FastAPI event loop:

| Thread | Function | Interval |
|---|---|---|
| `data_worker` | Listens to Redis/File/Mock, calls message handlers | Continuous (blocking) |
| `screening_worker` | Recalculates screening, updates qualified stocks | Every 1 minute (aligned to clock) |
| `signal_snapshot_worker` | Persists signal tracker state to disk | Every 5 minutes |

All threads share a `threading.Event` for graceful shutdown.

---

## 5. Parquet Snapshot Schema

### 5.1 `ReplayData_{date}.parquet` — Minute Snapshots

| Column | Type | Description |
|---|---|---|
| `timestamp` | int | Minutes since midnight (540 = 09:00) |
| `time_str` | str | `"HH:MM"` |
| `market_time` | str | `"HH:MM:SS"` |
| `strong_groups` | str (JSON) | Serialized group screening results |
| `burst_groups` | str (JSON) | Serialized burst group results |
| `strong_stocks` | str (JSON) | Serialized strong stock list |
| `intraday_burst_stocks` | str (JSON) | Burst stock list |
| `signals` | str (JSON) | All active + expired `SignalRecord` objects |
| `signal_count` | int | Count of signals |

Written with `pyarrow` engine, `snappy` compression.

### 5.2 `ReplaySignals_{date}.parquet` — Signal Records

Per-signal rows with fields from `SignalRecord.to_dict()`:

| Field | Type | Description |
|---|---|---|
| `code` | str | Stock symbol |
| `signal_type` | str | `'A'` or `'B'` |
| `signal_time` | Timestamp | When signal was generated |
| `entry_time` | Timestamp | When entry was reached (or null) |
| `valid_until` | Timestamp | Signal expiry time |
| `price` | float | Price at signal generation |
| `vwap` | float | VWAP at signal generation |
| `target_price` | float | Computed entry target |
| `anchor_low` | float | Rolling low anchor |
| `entry_reached` | bool | Whether target was hit |
| `expired` | bool | Whether signal expired unused |
| `group_name` | str | Source group |
| `source_category` | str | `"強勢族群"` / `"強勢個股"` / `"未分類"` |
| `date` | str | `YYYYMMDD` |

### 5.3 `ReplayCandidates_{date}.parquet` — Rejection Analysis

Tracks qualified stocks that *didn't* generate signals, with rejection reasons:

| Field | Type | Description |
|---|---|---|
| `timestamp` | int | Minute |
| `code` | str | Stock symbol |
| `stock_name` | str | Stock name |
| `group_name` | str | Group |
| `source_category` | str | Source classification |
| `current_price` | float | Price at that minute |
| `vwap` | float | VWAP at that minute |
| `rejection_reasons` | str | Semicolon-separated reasons (e.g., `"A: 價格過高; B: 當日已禁用"`) |

---

## 6. Critical Differences Between SS and SE

### 6.1 Price Representation

| System | Convention | Example (stock at 100.50) |
|---|---|---|
| SE | `int × 10000` throughout | `1_005_000` |
| SS | `float` after parsing (`/10000.0`) | `100.50` |

SE's integer convention is faster and avoids floating-point drift. Any integration should keep SE's convention and only convert at API boundaries.

### 6.2 Time Representation

| System | Convention | Example (09:15:00.000000) |
|---|---|---|
| SE | `match_time_str` = `91500000000` (int) + `match_time_us` = microseconds since midnight | Two integers |
| SS | `datetime.datetime` object | `datetime(2026, 1, 16, 9, 15, 0, 0)` |

SE's `match_time_str` is the canonical key for ordering. SS uses `datetime` objects which are richer but slower.

### 6.3 State Management

| Aspect | SS | SE |
|---|---|---|
| Per-symbol state | `StockState` class with `update_with_tick()` | `IndexCalc` / `IndexData` with explicit field updates |
| Signal state | `VWAPSignalTracker` with `VWAPState` per stock | `SignalAState` / `SignalBState` dataclasses |
| Position state | None (SS is screening only) | `PositionState` with cash, symbol_cash, stocks |
| Screening | `RealTimeManager.calculate_screening_results()` | `StrongGroupEvaluator` / `StrongSingleEvaluator` |

SS and SE compute the same screening and signal logic but with different class hierarchies. SE's code is more granular and typed (Pydantic configs, dataclass records), while SS uses a monolithic `RealTimeManager` (~1666 lines).

### 6.4 Configuration

| System | Config Source | Format |
|---|---|---|
| SE | `exec/cfg/parameter.cfg` → Pydantic models | Legacy INI → typed Python |
| SS | `core/config.py` module-level constants + `VWAP_SupStrat/config.yaml` | Python constants + YAML |

---

## 7. Integration Strategy

### 7.1 Phase 1: Abstract Data Source (Provider Pattern)

Introduce a `MarketDataProvider` abstraction into SE, following SS's proven pattern:

```python
# Proposed: src/tw_signal_engine/market_data/providers.py

class MarketDataProvider(ABC):
    @abstractmethod
    def iterate_ticks(self, tick_filter: set[str]) -> Iterator[MarketTick]:
        """Yield MarketTick objects in chronological order."""

class FileReplayProvider(MarketDataProvider):
    """Current behavior — reads TSEQuote/OTCQuote files."""

class RedisLiveProvider(MarketDataProvider):
    """New — subscribes to Redis Pub/Sub channels."""

class PacedReplayProvider(MarketDataProvider):
    """New — wraps FileReplayProvider with wall-clock pacing."""
```

The key insight from SS: **the provider abstraction handles source + timing, while the processing logic stays identical**. SE's `replay_session.py` currently calls `merge_market_streams()` which returns an iterator of `MarketTick`. The provider pattern slots in naturally here.

### 7.2 Phase 2: Redis Integration

Reuse SS's `RedisDataProvider` connection logic (auto-reconnect, pub/sub) but produce SE's `MarketTick` objects instead of SS's `TradeData`/`DepthData`:

1. Subscribe to stock symbol channels
2. On each message, parse using SE's existing `parse_format6_replay_rows` logic (same format)
3. Yield `MarketTick` objects into the same event loop

**Threading model**: SS runs Redis listener in a background thread with a callback. For SE, we could either:
- (a) Use the same threaded callback model with a `queue.Queue` → main loop polls queue
- (b) Use an async generator if SE moves to async

Option (a) is simpler and matches SS's proven approach.

### 7.3 Phase 3: Parquet Snapshot Generation

Add a snapshot serializer that runs alongside (or after) SE's replay loop:

1. At each minute boundary (based on `match_time_str`), capture:
   - Strong group evaluator state
   - Signal A/B states
   - Position state
   - Market gate state
2. Serialize to Parquet using SS's schema (or an extended version)
3. Store in `exec/cache/replay/`

This enables time-travel replay on SE's authoritative engine output.

### 7.4 Phase 4: FastAPI Server

Add an optional web server that exposes SE's engine state:

1. `/api/screened-groups` — current screening results (live or replay snapshot)
2. `/api/replay/jump` — time-travel in replay mode
3. `/api/signals` — active/expired signals
4. WebSocket push for new signals

SE's Pydantic models are already well-suited for JSON serialization.

---

## 8. Data Flow: Proposed End State

```
                    ┌──────────────┐
                    │ Redis Server │
                    │ 192.168.x.x  │
                    └──────┬───────┘
                           │ Pub/Sub (Trade/Depth lines)
                           ▼
              ┌────────────────────────┐
              │  RedisLiveProvider     │
              │  parse → MarketTick    │
              └────────────┬───────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
┌─────────────────┐  ┌──────────┐  ┌──────────────────┐
│ FileReplay      │  │ Paced    │  │ (same MarketTick │
│ Provider        │  │ Replay   │  │  iterator API)   │
│ (current)       │  │ Provider │  │                  │
└────────┬────────┘  └────┬─────┘  └────────┬─────────┘
         │                │                  │
         └────────────────┼──────────────────┘
                          ▼
              ┌───────────────────────┐
              │  replay_session.py    │
              │  (main event loop)    │
              │  ─ market gate        │
              │  ─ symbol state       │
              │  ─ exits → screening  │
              │  ─ signals → entries  │
              └───────────┬───────────┘
                          │
                ┌─────────┼─────────┐
                ▼                   ▼
    ┌──────────────────┐  ┌──────────────────┐
    │  CSV Reports     │  │  Parquet         │
    │  (existing)      │  │  Snapshots (new) │
    └──────────────────┘  └────────┬─────────┘
                                   │
                          ┌────────▼─────────┐
                          │  FastAPI Server   │
                          │  (optional, new)  │
                          │  ─ /api/...       │
                          │  ─ WebSocket      │
                          └──────────────────┘
```

---

## 9. Shared Quote File Format Reference

Both SE and SS consume the same raw quote files (`TSEQuote.YYYYMMDD`, `OTCQuote.YYYYMMDD`). Here is the canonical format:

### Trade Line
```
Trade,{symbol:6},{match_time:11-12},{func_code:1},{price:int×10000},{tick_vol:int},{total_vol:int},{seq:int}
```

Example:
```
Trade,2330  ,100500123456,0,6255000,150,285000,12345
```
- Symbol `2330`, time 10:05:00.123456, normal trade, price 625.50, tick volume 150 shares

### Depth Line
```
Depth,{symbol:6},{match_time:11-12},BID:{count},{p1*v1},{p2*v2},...,ASK:{count},{p1*v1},{p2*v2},...
```

Example:
```
Depth,2330  ,100500123456,BID:5,6254000*50,6253000*120,...,ASK:5,6255000*80,6256000*200,...
```

### Filtering Rules
- Only `func_code == '0'` lines are accepted (normal trades)
- Simulated (`1`), opening auction (`2`), circuit breaker (`3`), odd-lot (`4`) are filtered out
- Both systems apply the same filter

---

## 10. Configuration Mapping

How SS config constants map to SE's Pydantic config models:

| SS constant | SE config field | Notes |
|---|---|---|
| `STRONG_GROUP_AVG_CHANGE` | `strong_group.group_min_avg_pct_chg` | Same semantics |
| `STRONG_GROUP_VOL_MULT` | `strong_group.group_min_val_ratio` | Same semantics |
| `STRONG_GROUP_LIQUIDITY` | `strong_group.group_min_month_trading_val` | Same semantics |
| `SIGNAL_C_NEAR_VWAP_RATIO` | `signal_a.vwap_near_ratio` | Signal C ≈ Signal A |
| `SIGNAL_C_BOUNCE_RATIO` | `signal_a.bounce_ratio` | Same |
| `SIGNAL_C_ENTRY_START_TIME` | `signal_a.entry_start_time` | Format differs (HH:MM vs int) |
| `SIGNAL_C_MAX_CHANGE_PCT` | `signal_a.trade_zone_max_increase_ratio` | SS uses %, SE uses ratio |
| `REDIS_HOST` / `REDIS_PORT` | — (not in SE) | New config needed |

---

## 11. Risk & Compatibility Notes

1. **Signal parity**: SS's `VWAPSignalTracker` and SE's `evaluate_signal_a/b` compute the same concepts but with different implementations. Before integrating live data, verify that they produce identical results on the same input. Use SE's golden parity tests as the reference.

2. **Threading safety**: SE is currently single-threaded and deterministic. Adding Redis (which requires a listener thread + queue) changes the concurrency model. The queue-based approach (Phase 2, option a) minimizes risk by keeping the main loop single-threaded.

3. **Price precision**: SS converts to float early (`/10000.0`); SE keeps integers. Any bridge code must convert at the boundary and not lose precision.

4. **Time ordering**: Live Redis messages may arrive out of order (rare but possible with Pub/Sub). SE assumes strict `match_time_str` ordering. A small reorder buffer (50-100ms) may be needed.

5. **Backfill on startup**: SS has a `manager.execute_backfill()` that reads historical logs to catch up. SE would need equivalent backfill logic if it starts mid-session.

6. **Memory**: SS's `RealTimeManager` holds all stock states in memory (~2000 stocks × state). SE already does this during replay but frees it after. For live mode, state persists for the full session.

---

## 12. Files to Study in SS

For anyone continuing this integration, the essential files to read:

| Priority | File | Lines | Why |
|---|---|---|---|
| **P0** | `services/market_data_provider.py` | 245 | Provider abstraction + Redis + File replay |
| **P0** | `services/background.py` | 239 | Threading model, message dispatch |
| **P0** | `services/message_handler.py` | 251 | Trade/Depth parsing, state application |
| **P1** | `services/replaymode/manager.py` | 313 | Time-travel replay with Parquet |
| **P1** | `services/replaymode/precompute_engine.py` | 725 | Offline Parquet snapshot generation |
| **P1** | `main.py` | 673 | FastAPI routes, dual-mode endpoints |
| **P2** | `services/vwap_signal_tracker.py` | ~900 | Signal generation (compare to SE's signal_a/b) |
| **P2** | `services/realtime_processor.py` | ~1666 | Screening computation (compare to SE's screening/) |
| **P2** | `core/config.py` | 147 | All config constants |
| **P3** | `services/replaymode/data/loader.py` | ~100 | Batch memory loading for precompute |
| **P3** | `services/replaymode/data/time_parser.py` | ~50 | Time parsing utility |
| **P3** | `services/file_indexer.py` | ~500 | Quote file indexing for O(1) minute access |
