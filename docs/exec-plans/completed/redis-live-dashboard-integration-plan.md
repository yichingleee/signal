# Redis Live Dashboard Integration Plan

Status: completed 2026-04-30
Created: 2026-04-30

## Objective

Integrate the Redis live-data flow patterns from
`/home/r12944005/b07401012/Trading/TWSE-backtest-test-UI-for-VWAP-strategies`
into this repository's Python engine and React dashboard in a way that preserves
the existing `tw_signal_engine` architecture.

The target result is:

- live Redis ticks flow through the existing engine path, not a parallel
  dashboard-only processor;
- the dashboard exposes live Redis connection health, data freshness, and feed
  diagnostics clearly;
- the implementation can be tested thoroughly without access to the actual Redis
  server;
- a real Redis smoke workflow remains available for market-hours validation when
  the server is reachable.

## Assumptions and decisions

- "Copy that into this repo" means copy the useful architecture and behavior,
  not vendor the full source application. The source repo has a Dash heatmap app
  and a separate StockScreening FastAPI app; this repo already has a FastAPI
  server and React dashboard.
- The engine remains the system of record. Redis messages become
  `MarketTick` objects through `RedisLiveProvider`, then flow through
  `run_daily_replay()`, session hooks, `LiveState`, FastAPI, Socket.IO, and the
  React dashboard.
- Do not introduce a second Redis consumer in the dashboard process. Duplicating
  ingestion would create inconsistent strategy state and make replay/live parity
  harder to prove.
- Prefer dependency-injected fake providers and fake Redis clients for tests.
  A real Redis server is optional and only belongs in a manual smoke workflow or
  explicitly marked integration tests.
- Keep Socket.IO because both repos already use it and the target dashboard
  already has a `dashboard:snapshot` event plus REST polling fallback.

## Source research summary

### Source repo: StockHeatmap Redis flow

Relevant files:

- `StockHeatmap/refactor/redis_handler.py`
- `StockHeatmap/real_time_panel.py`
- `StockHeatmap/README_real_time_panel.md`
- `StockHeatmap/sunredisCode/mock_redis_module.py`
- `StockHeatmap/sunredisCode/subscribe.py`
- `StockHeatmap/sunredisCode/sub_redis_example.py`

Findings:

- Redis Pub/Sub channels are stock symbols such as `2330`.
- Trade messages use CSV-like lines:

  ```text
  Trade,<symbol>,<HHMMSSuuuuuu>,<func_code>,<price_x10000>,<tick_volume>,<total_volume>,...
  ```

- Depth messages are also CSV-like and contain `BID:5` and `ASK:5` sections.
- Symbols may contain trailing spaces and must be stripped.
- Price is integer scaled by 10000 and must stay integer internally where this
  repo already uses integer price fields.
- `func_code == 0` is normal trade data. Simulated/opening/odd-lot style rows
  are filtered out.
- The heatmap implementation updates a shared in-memory data store directly
  from a Redis listener thread. That works for Dash visualization, but it is not
  the right pattern for this repo because this repo intentionally keeps engine
  state changes on the main replay/live loop.
- The useful pieces to bring over are protocol documentation, mock Redis
  behavior, reconnect expectations, and operator-facing feed diagnostics.

### Source repo: StockScreening live flow

Relevant files:

- `StockScreening/services/market_data_provider.py`
- `StockScreening/services/background.py`
- `StockScreening/main.py`
- `StockScreening/services/socketio_manager.py`
- `StockScreening/templates/signals.html`
- `StockScreening/doc/LIVE_MODE_ANALYSIS.md`

Findings:

- The source app abstracts data ingestion behind `MarketDataProvider` with
  Redis, mock, and file replay implementations.
- `RedisDataProvider.listen()` uses a reconnect loop around
  `pubsub.get_message(timeout=1.0)`.
- `MockDataProvider` uses `StockHeatmap.sunredisCode.mock_redis_module` to
  exercise the same callback path without Redis.
- `FileReplayDataProvider` can pace a raw quote file by message timestamp, which
  is useful for UI development without Redis.
- `background.data_worker()` parses Redis messages, splits Trade versus Depth,
  filters non-normal Trade messages, updates the real-time manager, and forwards
  trade/depth data to VWAP signal tracking.
- `main.py` starts data ingestion in a background thread, starts a backfill
  thread, runs per-minute screening, and emits Socket.IO events from a background
  thread using `asyncio.run_coroutine_threadsafe`.
- `templates/signals.html` connects with `socket.io-client`, listens for
  `new_signal` and `signal_triggered`, shows browser/toast notifications, and
  keeps REST polling as a fallback.

What should be copied conceptually:

- data-source abstraction with Redis, file replay, and mock/fake modes;
- reconnect and stop-event behavior;
- protocol-level parsing tests;
- UI status around socket connection and data freshness;
- fallback polling behavior;
- optional notifications for new live events.

What should not be copied literally:

- mutable dashboard data stores updated directly from the listener thread;
- Dash-specific layout and callbacks;
- separate StockScreening signal tracker state that duplicates engine logic;
- global config constants as the primary runtime configuration mechanism.

## Target repo current state

Relevant files:

- `src/tw_signal_engine/market_data/redis_live_provider.py`
- `src/tw_signal_engine/market_data/backfill_provider.py`
- `src/tw_signal_engine/market_data/file_replay_provider.py`
- `src/tw_signal_engine/market_data/paced_replay_provider.py`
- `src/tw_signal_engine/cli/run_live.py`
- `src/tw_signal_engine/cli/run_server.py`
- `src/tw_signal_engine/server/app.py`
- `src/tw_signal_engine/server/live_state.py`
- `src/tw_signal_engine/server/dashboard_snapshot.py`
- `dashboard/src/hooks/useDashboardData.ts`
- `dashboard/src/api/socket.ts`
- `dashboard/src/App.tsx`
- `tests/unit/test_providers.py`
- `tests/unit/test_server.py`

Existing strengths:

- `RedisLiveProvider` already implements the correct queue-bridge pattern:
  listener thread reads Redis, main engine loop consumes `MarketTick` objects.
- It already buffers Trade rows until matching Depth rows arrive, flushes old
  Trade rows when a new Trade arrives first, filters non-zero status codes, and
  has an optional reorder buffer.
- `run_server --mode live` already starts the engine in a background thread,
  updates `LiveState` through hooks, and serves FastAPI plus Socket.IO.
- `server/app.py` already emits `dashboard:snapshot` over Socket.IO in live mode
  and deduplicates by `(time_raw, tick_count)`.
- `useDashboardData.ts` already listens for `dashboard:snapshot`, polls REST
  every two seconds as fallback, and marks the UI stale if no data arrives.
- `tests/unit/test_providers.py` already covers Trade/Depth pairing, Trade
  without Depth, empty lines, empty tick filter termination, status-code
  filtering, backfill/live handoff, and overlap deduplication.

Current gaps:

- The dashboard does not expose Redis connection state, subscribed channel count,
  reconnect count, dropped/ignored message counts, queue backlog, or last raw
  feed error.
- `RedisLiveProvider` logs reconnects but does not publish structured health
  metrics to `LiveState`.
- There is no first-class fake Redis Pub/Sub adapter for deterministic tests of
  listener reconnect behavior.
- There is no dashboard-specific test workflow proving that live mode remains
  useful when Redis is absent.
- The frontend socket wrapper does not surface reconnect attempts or transport
  mode beyond a boolean connected state.
- Manual Redis validation is documented, but the no-Redis development workflow
  should be more explicit and scriptable.

## Architecture to implement

### Live data flow

Keep the target flow:

```text
Redis Pub/Sub or fake Pub/Sub
  -> RedisLiveProvider listener thread
  -> Queue[MarketTick | None]
  -> RedisLiveProvider.iterate_ticks()
  -> run_daily_replay()
  -> SessionHooks and on_dashboard_snapshot
  -> LiveState
  -> FastAPI REST + Socket.IO dashboard:snapshot
  -> React useDashboardData()
  -> dashboard routes
```

Do not add this flow:

```text
Redis Pub/Sub
  -> dashboard-specific listener
  -> dashboard-only store
  -> UI
```

The second flow would be faster to copy from the source repo but would bypass
the strategy engine and break parity with replay snapshots.

### Provider health contract

Add structured live feed status separate from strategy snapshot data.

Suggested Python type:

```python
@dataclass
class LiveFeedStatus:
    source: str = "redis"
    connected: bool = False
    subscribed_channels: int = 0
    last_message_at: str = ""
    last_tick_time_raw: int = 0
    reconnect_count: int = 0
    parse_error_count: int = 0
    ignored_message_count: int = 0
    dropped_tick_count: int = 0
    queue_depth: int = 0
    last_error: str = ""
```

Implementation notes:

- Let `RedisLiveProvider` own status updates because it knows Redis connection,
  Pub/Sub, parsing, queue depth, and reconnect behavior.
- Expose a `get_status()` method on live-capable providers.
- In `run_server._start_live_mode()`, bridge provider status into `LiveState`.
  Avoid calling provider internals from FastAPI directly.
- Add `LiveState.update_feed_status()` and include the latest feed status in
  `/api/status` and `/api/dashboard/status`.
- Keep status optional so file replay, paced replay, and test providers can use
  a minimal compatible shape.

### Redis adapter boundary for tests

Refactor `RedisLiveProvider` just enough to support dependency injection.

Recommended approach:

- Add an optional `redis_client_factory` constructor argument.
- Default factory creates `redis.Redis(...)` exactly as today.
- Tests pass a fake factory returning fake clients and fake pubsub objects.
- Keep the public provider behavior unchanged.

Fake objects should support:

- `pubsub()`
- `get_message(timeout=...)`
- `subscribe(*channels)`
- `unsubscribe()`
- `close()`
- `Redis.close()`
- configured exceptions on selected calls for reconnect tests.

Do not import the source repo's `mock_redis_module` directly into production
code. Its random generator is useful as a reference, but deterministic tests
need explicit fixtures and message sequences.

### Dashboard UI integration

Extend the existing dashboard rather than adding a separate page tree.

Backend additions:

- Include `feed_status` in `GET /api/status`.
- Include `feed_status` in `GET /api/dashboard/status`.
- Optionally include `feed_status` in the top-level `DashboardSnapshot` if the
  UI needs point-in-time feed health alongside strategy data.

Frontend additions:

- Extend `dashboard/src/types/dashboard.ts` with `LiveFeedStatus`.
- Extend `dashboard/src/api/client.ts` status typing.
- Extend `useDashboardData.ts` to store feed status from `/api/status` and
  `/api/dashboard/status`.
- Update `StatusBar` to show:
  - server mode;
  - socket connected/disconnected;
  - feed connected/disconnected;
  - last message age;
  - subscribed channel count;
  - reconnect count;
  - queue backlog warning;
  - parse/ignored counts when non-zero.
- Keep existing stale UI behavior. Add a distinct message for "socket connected
  but Redis feed stale" because these are different failures.

Suggested UI states:

- `Live / Redis connected / fresh`: normal live operation.
- `Live / Redis disconnected / retrying`: provider is reconnecting; UI remains
  connected to server.
- `Live / Redis connected / stale`: Redis connection exists but no fresh
  messages have arrived recently.
- `Live / socket disconnected / polling`: browser has lost Socket.IO but REST
  fallback may still work.
- `Replay`: hide Redis health except for disabled or "not applicable" text.

### Optional live event notifications

The source repo emits `new_signal` and `signal_triggered`; this repo currently
pushes whole dashboard snapshots. Keep `dashboard:snapshot` as the primary
transport.

If operator notifications are desired, add derived frontend notifications from
snapshot deltas rather than adding new backend event types first. This keeps the
backend contract smaller and works in replay mode too.

Only add backend event types later if whole-snapshot diffing becomes expensive
or ambiguous.

## Implementation milestones

### Milestone 1: Provider diagnostics and dependency injection — completed 2026-04-30

Files likely touched:

- `src/tw_signal_engine/market_data/redis_live_provider.py`
- `src/tw_signal_engine/market_data/providers.py` if a shared status protocol is
  useful
- `tests/unit/test_providers.py`

Tasks:

- [x] Add a `LiveFeedStatus` dataclass or lightweight typed structure.
- [x] Add `RedisLiveProvider.get_status()`.
- [x] Update status in these places:
   - listener start;
   - successful connection;
   - subscribe success;
   - each decoded message;
   - each emitted tick;
   - ignored non-Trade/non-Depth message;
   - parse failure;
   - reconnect;
   - clean stop.
- [x] Add optional `redis_client_factory`.
- [x] Add deterministic fake Redis Pub/Sub tests.

Acceptance criteria:

- Existing provider tests still pass.
- Tests can drive `_listen()` or a bounded listener path without a real Redis
  server.
- Reconnect status can be asserted without sleeping for real reconnect delays.
- Empty tick filter still terminates without hanging.

### Milestone 2: Bridge provider health into server state — completed 2026-04-30

Files likely touched:

- `src/tw_signal_engine/server/live_state.py`
- `src/tw_signal_engine/cli/run_server.py`
- `src/tw_signal_engine/server/app.py`
- `tests/unit/test_server.py`
- `tests/unit/test_run_server_cli.py`

Tasks:

- [x] Add feed-status storage to `LiveState` with lock protection.
- [x] Add a bounded status updater in live server mode. Options:
   - update from the engine thread through a hook-adjacent callback;
   - start a small daemon thread that periodically reads `provider.get_status()`
     and writes `LiveState.update_feed_status()`.
- [x] Include `feed_status` in `/api/status`.
- [x] Include `feed_status` in `/api/dashboard/status`.
- [x] Ensure fatal engine startup errors and Redis reconnect errors remain distinct.

Acceptance criteria:

- `/api/status` shows engine status and feed status in live mode.
- Replay mode does not claim a Redis connection.
- A provider reconnect does not mark the engine fatal unless the engine actually
  crashes.
- Unit tests cover status defaults, updates, and replay/live response shape.

### Milestone 3: Frontend feed-health display — completed 2026-04-30

Files likely touched:

- `dashboard/src/types/dashboard.ts`
- `dashboard/src/api/client.ts`
- `dashboard/src/hooks/useDashboardData.ts`
- `dashboard/src/components/layout/StatusBar.tsx`
- `dashboard/src/components/layout/Header.tsx` only if the header should show
  compact Redis state

Tasks:

- [x] Add TypeScript types for `LiveFeedStatus`.
- [x] Fetch dashboard status periodically or include status in the existing polling
   path.
- [x] Keep socket connection state separate from Redis feed state.
- [x] Render compact operator status in `StatusBar`.
- [x] Add warning styles for stale feed, disconnected feed, reconnecting feed, and
   queue backlog.

Acceptance criteria:

- In live mode, operators can tell whether the browser socket, server, and Redis
  feed are independently healthy.
- In replay mode, the UI does not show misleading Redis errors.
- Existing dashboard pages continue to consume the same snapshot data shape.

### Milestone 4: No-Redis live simulation workflow — completed 2026-04-30

Files likely touched:

- `src/tw_signal_engine/cli/run_server.py`
- `src/tw_signal_engine/cli/run_live.py`
- `src/tw_signal_engine/market_data/fake_redis_provider.py` or equivalent only
  if fake mode should be productized
- `docs/references/dashboard-operations.md`
- `docs/design-docs/live-data-architecture.md`

Preferred implementation:

- [x] Do not productize a random Redis mock first.
- [x] Reuse existing file/paced replay providers for dashboard development.
- [x] Add clear CLI documentation for:

  ```bash
  uv run python -m tw_signal_engine.cli.run_daily_replay --date <YYYYMMDD> --snapshots
  uv run python -m tw_signal_engine.cli.run_server --mode replay --date <YYYYMMDD>
  ```

- [x] If live-mode UI specifically needs to be tested without Redis, add a
  deterministic fake Pub/Sub mode behind an explicit flag such as
  `--live-source fake-redis-fixture` or a test-only factory, not a hidden
  fallback that masks production Redis failures.

Acceptance criteria:

- Developers can exercise the dashboard transport, stale-state behavior, and
  snapshot rendering without Redis.
- Production live mode fails visibly when Redis is unreachable instead of
  silently switching to fake data.
- Documentation clearly separates replay dashboard testing, fake Pub/Sub tests,
  and real Redis smoke testing.

### Milestone 5: Documentation updates — completed 2026-04-30

Files likely touched:

- `docs/design-docs/live-data-architecture.md`
- `docs/design-docs/dashboard-architecture.md`
- `docs/references/dashboard-operations.md`
- `docs/exec-plans/active/index.md`

Tasks:

- [x] Document the Redis message contract from the source repo:
   - symbol channels;
   - Trade rows;
   - Depth rows;
   - price scaling;
   - normal trade filtering;
   - Trade/Depth pairing.
- [x] Document provider health fields and what each UI status means.
- [x] Document no-Redis workflows and real-Redis smoke workflows.
- [x] Link this execution plan from the active plans index.

Acceptance criteria:

- A developer can understand and test live-dashboard behavior without reading
  the source repo.
- Operators can distinguish Redis outages from browser socket issues.

## Comprehensive testing workflow

### Layer 1: Pure parser and provider unit tests, no Redis

Use deterministic lines copied from the source protocol:

```text
Trade,2330  ,90000000000,0,5000000,100,1000,1
Depth,2330  ,90000000000,BID:5,4999000,100,ASK:5,5001000,200
```

Tests to add or keep:

- Trade then Depth emits one `MarketTick`.
- Trade then Trade flushes the first Trade without Depth.
- Depth without Trade is ignored.
- Empty lines are ignored.
- Unknown message types increment ignored count and emit no tick.
- Malformed Trade lines increment parse error count and emit no tick.
- `func_code != 0` or parsed non-normal status rows are filtered.
- Symbols are stripped before pairing and status lookup.
- Price scale remains compatible with `parse_trade_line()`.
- Reorder buffer yields ticks sorted by match time.
- `stop()` unblocks `iterate_ticks()`.
- Empty tick filter terminates cleanly.

Command:

```bash
rtk uv run pytest tests/unit/test_providers.py -q
```

### Layer 2: Fake Redis listener tests, no Redis

Create fake Redis client/pubsub objects with deterministic message sequences.

Cases:

- initial connect succeeds, subscribe receives expected channels;
- bytes payload and string payload both decode;
- timeout returns `None` and does not count as an error;
- connection error increments reconnect count and reconnects;
- unsubscribe/close happens on clean stop;
- queue depth status updates as ticks are produced and consumed;
- listener handles `stop_event` without leaking a thread.

Implementation detail:

- Avoid real sleeps by setting `reconnect_delay=0` in `LiveConfig` or injecting a
  sleep function if needed.
- Keep listener tests bounded by finite message sequences and explicit stop
  sentinels.

Command:

```bash
rtk uv run pytest tests/unit/test_providers.py -q
```

### Layer 3: LiveState and API tests, no Redis

Tests:

- `LiveState` default feed status is absent or disconnected but not fatal.
- `LiveState.update_feed_status()` is thread-safe and included in status APIs.
- `/api/status` live mode returns engine status plus feed status.
- `/api/dashboard/status` live mode returns `has_snapshot` plus feed status.
- replay mode omits or marks feed status as not applicable.
- fatal engine errors remain visible separately from Redis disconnects.

Command:

```bash
rtk uv run pytest tests/unit/test_server.py tests/unit/test_run_server_cli.py -q
```

### Layer 4: Dashboard TypeScript build and UI state checks, no Redis

Minimum validation:

```bash
cd dashboard
npm run build
```

Manual UI states to exercise with mocked API responses or replay mode:

- live plus Redis connected;
- live plus Redis reconnecting;
- live plus Redis stale;
- live plus browser socket disconnected but REST polling still updating;
- replay mode with Redis status hidden or marked not applicable.

If frontend tests are added later, cover:

- `useDashboardData()` keeps socket `connected` distinct from feed
  `connected`;
- `StatusBar` renders separate warnings for socket failure and Redis failure;
- stale feed status does not erase the last valid dashboard snapshot;
- replay mode disconnects Socket.IO and does not show Redis outage warnings.

### Layer 5: End-to-end no-Redis dashboard workflow

Use replay snapshots to validate the dashboard without Redis:

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date <YYYYMMDD> \
  --snapshots

uv run python -m tw_signal_engine.cli.run_server \
  --mode replay \
  --date <YYYYMMDD> \
  --snapshot-dir ./cache/replay/
```

Acceptance checks:

- `/api/status` reports replay mode and ready state.
- `/api/dashboard/status` reports replay readiness and time range.
- The React dashboard loads from `dashboard/dist` after build.
- Timeline jump updates the same UI components used in live mode.
- No Redis warning is displayed in replay mode.

### Layer 6: Live-mode no-Redis failure workflow

Run live mode with an unreachable Redis host to prove robustness:

```bash
uv run python -m tw_signal_engine.cli.run_server \
  --mode live \
  --date <YYYYMMDD> \
  --redis-host 127.0.0.1 \
  --redis-port 6399
```

Expected behavior:

- Server starts if reference data and history are valid.
- Engine status is not confused with Redis feed status.
- Feed status reports disconnected/retrying.
- Dashboard remains reachable.
- UI shows "Redis disconnected/retrying" or equivalent.
- REST polling and Socket.IO connection status remain visible.

This workflow must not silently fall back to fake market data.

### Layer 7: Real Redis smoke workflow, optional

Only run when the Redis host is reachable and market data is expected:

```bash
uv run python -m tw_signal_engine.cli.run_server \
  --mode live \
  --date <YYYYMMDD> \
  --redis-host 192.168.100.130 \
  --redis-port 6379
```

Checks:

- subscribed channel count is non-zero;
- last message time advances during market data flow;
- tick count advances;
- dashboard snapshot time advances;
- reconnect count remains stable under normal network conditions;
- parse error count remains zero or explainable;
- browser shows socket connected and feed fresh.

Do not make this workflow mandatory in CI.

## Robustness requirements

- Redis outage must not crash the web server.
- Browser socket outage must not erase the last good snapshot.
- Redis reconnect must be visible to operators.
- Queue backlog must be visible before it becomes a latency incident.
- Parser errors must be counted but must not kill the listener.
- Fake/mock testing must never be enabled implicitly in production live mode.
- Replay mode must remain the primary no-Redis dashboard development path.
- Live and replay dashboard pages must keep sharing the same React components.

## Risks and mitigations

- Risk: adding provider health to `DashboardSnapshot` widens replay snapshot
  schema unnecessarily.
  Mitigation: prefer `/api/status` and `/api/dashboard/status` for live feed
  health unless point-in-time replay of feed diagnostics is required.

- Risk: fake Redis mode hides production configuration mistakes.
  Mitigation: require an explicit CLI flag or test-only factory; never fall back
  automatically from Redis to fake data in live mode.

- Risk: listener tests hang.
  Mitigation: use finite fake message sequences, zero reconnect delay, stop
  sentinels, and small timeouts.

- Risk: thread-safety bugs in status sharing.
  Mitigation: keep `LiveState` as the only server-facing mutable state and guard
  all reads/writes with the existing lock.

- Risk: frontend conflates socket connectivity with Redis feed connectivity.
  Mitigation: represent them as separate fields and render separate UI labels.

## Definition of done

- The Redis protocol and source-repo findings are documented in this repo.
- `RedisLiveProvider` exposes structured health and supports deterministic fake
  Redis tests.
- Live server status endpoints expose feed health in live mode.
- The React dashboard shows feed health without disrupting existing live/replay
  data loading.
- Unit tests prove parsing, reconnect behavior, feed status propagation, and API
  shape without real Redis.
- The dashboard can be exercised end-to-end in replay mode without Redis.
- A documented optional smoke test exists for the real Redis server.
