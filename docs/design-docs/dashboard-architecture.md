# Dashboard Architecture

This document describes the as-built architecture of the Dashboard UI system — the FastAPI backend, React frontend, dual-mode API pattern, WebSocket real-time push, and replay time-travel.

**Related docs**:
- Live data providers that feed the dashboard: [live-data-architecture.md](live-data-architecture.md)
- Pre-implementation research: [live-data-integration-research.md](live-data-integration-research.md)

---

## 1. System Overview

The dashboard is a monitoring tool for the signal engine. It shows strong groups, strong singles, VWAP proximity, and Signal A trade lifecycle (preparing → entered → exited) in real time.

```
┌─────────────────────────────────────────────────────┐
│                  React SPA (dashboard/)              │
│  MarketOverview  │  SignalAMonitor                   │
│  ─ GroupGrid     │  ─ PreparingCards                 │
│  ─ SinglesTable  │  ─ ActiveCards                    │
│  ─ VWAPTable     │  ─ ExitedCards + Counters         │
└────────┬────────────────────┬────────────────────────┘
         │ HTTP polling       │ WebSocket (Socket.IO)
         ▼                    ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Backend (server/)                │
│  /api/dashboard/{groups,singles,vwap,signal-a}       │
│  /api/replay/{status,jump}                           │
│  Socket.IO: dashboard:snapshot                       │
└────────┬────────────────────┬────────────────────────┘
         │                    │
    ┌────▼────┐         ┌────▼─────────┐
    │LiveState│         │ReplayManager │
    │(thread- │         │(Parquet-     │
    │ safe)   │         │ backed)      │
    └────┬────┘         └──────────────┘
         │
    SessionHooks from replay_session.py
```

**Key idea**: The frontend is mode-agnostic. The same React components render data from either live or replay sources. The branching between modes happens entirely in the backend API handlers.

---

## 2. Backend Architecture

### 2.1 Dual-Mode API Pattern

Every data endpoint follows the same pattern:

```python
@app.get("/api/dashboard/groups")
def dashboard_groups():
    if _server_mode == "live" and _live_state is not None:
        return {"groups": _live_state.get_dashboard_groups()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "dashboard_groups" in snapshot:
            return {"groups": snapshot["dashboard_groups"]}
    return {"groups": []}
```

- **Live mode**: reads from `LiveState` (thread-safe, updated by engine hooks)
- **Replay mode**: reads from `ReplayManager` (Parquet-backed, time-travel via `jump_to_time`)
- **Fallback**: returns empty data if neither source is available

This means the frontend never needs to know which mode is active — it calls the same endpoints.

### 2.2 API Endpoints

**File**: `src/tw_signal_engine/server/app.py`

#### Core Status

| Endpoint | Method | Returns |
|---|---|---|
| `GET /api/status` | GET | `{mode, tick_count, last_time_str, ready, time_range}` |
| `GET /api/config` | GET | `{mode}` |

#### Dashboard V1 (used by React frontend)

| Endpoint | Method | Returns |
|---|---|---|
| `GET /api/dashboard/groups` | GET | Strong group cards with ranked member tables |
| `GET /api/dashboard/singles` | GET | Strong individual stocks |
| `GET /api/dashboard/vwap` | GET | VWAP monitoring table for all universe symbols |
| `GET /api/dashboard/signal-a` | GET | Signal A lifecycle: preparing, entered, exited, counters |
| `GET /api/dashboard/status` | GET | Mode-specific dashboard status |

#### Legacy Endpoints (pre-dashboard API)

| Endpoint | Method | Returns |
|---|---|---|
| `GET /api/positions` | GET | Open positions with current P&L |
| `GET /api/signals` | GET | Active + expired signal states |
| `GET /api/screened-groups` | GET | Raw screening results |
| `GET /api/trades` | GET | Completed trades |

#### Replay Control

| Endpoint | Method | Returns |
|---|---|---|
| `GET /api/replay/status` | GET | `{enabled, ready, time_range: {min_time, max_time, count}}` |
| `POST /api/replay/jump` | POST | Body: `{"time": "10:30"}` → jumps to that minute's snapshot |

### 2.3 LiveState — Thread-Safe State Holder

**File**: `src/tw_signal_engine/server/live_state.py`

The engine runs in a background thread. The API runs in the main asyncio thread. `LiveState` bridges them with `threading.Lock`:

```
Engine thread (background)                API thread (main, asyncio)
    │                                         │
    │  SessionHooks callbacks                 │  GET /api/dashboard/groups
    │  ─ on_tick() → update prices            │  ─ live_state.get_dashboard_groups()
    │  ─ on_entry() → add to active           │     ─ acquire lock
    │  ─ on_exit() → move to completed        │     ─ read state
    │  ─ on_dashboard_snapshot()              │     ─ release lock
    │     → update _dashboard_snapshot        │
    ▼                                         ▼
         ┌──── threading.Lock ────┐
         │     LiveState fields   │
         └────────────────────────┘
```

**State tracked**:
- `_tick_count`, `_last_time_str` — progress
- `_last_prices[symbol]`, `_last_indices[symbol]` — per-symbol latest data
- `_active_entries[symbol]` — open positions
- `_completed_trades[]` — closed trades
- `_recent_signals[]` — signal generation history
- `_dashboard_snapshot` — latest minute-boundary dashboard snapshot (dict)
- `_engine_status` — `"starting"`, `"running"`, `"stopped"`, `"fatal"`

**Hooks wiring** (via `build_hooks()` method):
- `on_tick` → increment tick count, update last prices
- `on_entry` → populate `_active_entries`
- `on_exit` → move from active to completed
- `on_dashboard_snapshot` → store the full snapshot dict

### 2.4 ReplayManager — Parquet Time-Travel

**File**: `src/tw_signal_engine/server/replay_manager.py`

Loads pre-computed Parquet snapshots (generated by `--snapshots` flag during batch replay) and serves them via the API.

**Usage flow**:
1. Generate snapshots: `uv run python -m tw_signal_engine.cli.run_daily_replay --date 20260129 --snapshots`
2. Start server in replay mode: `uv run python -m tw_signal_engine.cli.run_server --date 20260129 --mode replay`
3. Frontend loads, calls `GET /api/replay/status` to discover time range
4. User clicks timeline or calls `POST /api/replay/jump {"time": "10:30"}` to time-travel

**Key operations**:
- `load()` → reads `ReplayData_{date}.parquet` into a DataFrame
- `jump_to_time("10:30")` → binary search for snapshot at or before that minute
- `get_current_snapshot()` → returns the last jumped-to snapshot
- `get_time_range()` → returns `{min_time, max_time, count}` for the timeline

### 2.5 WebSocket Real-Time Push

**Protocol**: Socket.IO (via `python-socketio`)

**Event**: `dashboard:snapshot` — emitted every ~1 second in live mode

```python
# server/app.py — background async task
async def _push_dashboard_snapshot_loop():
    while True:
        await asyncio.sleep(1.0)
        snapshot = _live_state.get_dashboard_snapshot_dict()
        if snapshot and snapshot != last_emitted:
            await sio.emit("dashboard:snapshot", snapshot)
```

**Dedup logic**: Tracks `(time_raw, tick_count)` tuple. Only emits when the snapshot actually changes (avoids flooding the frontend with identical data between minute boundaries).

### 2.6 Static File Serving

The React SPA build output (`dashboard/dist/`) is served as static files mounted at `/`. This is mounted **last** so API routes take precedence. React Router handles client-side navigation.

```python
_dashboard_dist = Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "dist"
if _dashboard_dist.exists():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")
```

---

## 3. Data Models

**Python side**: `src/tw_signal_engine/server/dashboard_snapshot.py`
**TypeScript side**: `dashboard/src/types/dashboard.ts`

The TypeScript interfaces mirror the Python dataclasses exactly.

### DashboardSnapshot (top-level container)

```
DashboardSnapshot
├── timestamp: str          # human-readable time
├── time_raw: int           # match_time_str integer
├── tick_count: int         # total ticks processed
├── groups: GroupSnapshot[]
│   └── members: MemberSnapshot[]
├── singles: SingleSnapshot[]
├── vwap_monitor: VWAPMonitorEntry[]
└── signal_a: SignalAMonitorSnapshot
    ├── preparing: PreparingEntry[]
    ├── entered: ActivePosition[]
    ├── exited: CompletedTrade[]
    └── counters: SignalCounters
```

### Key Data Types

| Type | Purpose | Key fields |
|---|---|---|
| `GroupSnapshot` | One strong group | `group_name`, `group_rank`, `avg_pct_chg`, `vol_ratio`, `members[]` |
| `MemberSnapshot` | One stock in a group | `symbol`, `price`, `pct_chg`, `vwap`, `vwap_pct_chg`, `cum_vol_ratio` |
| `SingleSnapshot` | Strong individual stock | `symbol`, `price`, `pct_chg`, `vwap`, `group_name` |
| `VWAPMonitorEntry` | VWAP proximity tracking | `symbol`, `price`, `vwap`, `vwap_pct`, `signal_a_state` |
| `PreparingEntry` | Near VWAP, awaiting entry | `symbol`, `order_price`, `distance_pct`, `stop_loss` |
| `ActivePosition` | Open position | `symbol`, `entry_price`, `current_price`, `pnl_pct`, `stop_loss`, `take_profit` |
| `CompletedTrade` | Closed trade | `symbol`, `entry_price`, `exit_price`, `pnl_pct`, `exit_cause` |
| `SignalCounters` | Summary bar | `qualified`, `holding`, `take_profit`, `stop_loss`, `forbidden` |

### Snapshot Building

`DashboardSnapshot` is built inside `replay_session.py` at minute boundaries (function `_build_dashboard_snapshot()`). It reads from:

- `StrongGroupEvaluator` state → `groups[]`
- `StrongSingleEvaluator` state → `singles[]`
- `signal_a_map[]` + latest prices → `vwap_monitor[]` + `signal_a.preparing[]`
- `pos.open_trades` → `signal_a.entered[]`
- `completed_trades[]` → `signal_a.exited[]`
- Aggregated counters → `signal_a.counters`

---

## 4. Frontend Architecture

**Framework**: React + TypeScript + Vite
**Location**: `dashboard/`

### 4.1 Component Structure

```
dashboard/src/
├── App.tsx                         # Router: / → MarketOverview, /signal-a → SignalAMonitor
├── pages/
│   ├── MarketOverview.tsx          # Groups + Singles + VWAP monitoring
│   └── SignalAMonitor.tsx          # Signal A lifecycle tracking
├── components/
│   ├── groups/                     # GroupGrid, GroupCard
│   ├── singles/                    # Singles table
│   ├── vwap/                       # VWAP monitoring table
│   ├── signal/                     # PreparingCards, ActiveCards, ExitedCards
│   ├── replay/                     # Replay timeline controls
│   └── layout/                     # Shared layout (nav, header)
├── hooks/
│   └── useDashboardData.ts         # Central data hook
├── api/
│   ├── client.ts                   # HTTP fetch wrapper
│   └── socket.ts                   # Socket.IO client
├── types/
│   └── dashboard.ts                # TypeScript interfaces
└── styles/                         # CSS
```

### 4.2 `useDashboardData` Hook

**File**: `dashboard/src/hooks/useDashboardData.ts`

This is the central state management hook. It:

1. **Detects mode** on mount via `GET /api/status`
2. **Live mode**: connects Socket.IO, listens for `dashboard:snapshot` events, with HTTP polling fallback (2s interval)
3. **Replay mode**: uses HTTP polling + exposes `jumpToTime(hhmm)` for time-travel
4. **Tracks staleness**: if no update received for >5 seconds in live mode, marks data as stale

All page components consume this hook — they never fetch data directly.

### 4.3 API Client

**File**: `dashboard/src/api/client.ts`

Minimal fetch wrapper with typed responses:

```typescript
export const api = {
  status:       () => fetchJSON<StatusResponse>('/api/status'),
  groups:       () => fetchJSON<{groups: GroupSnapshot[]}>('/api/dashboard/groups'),
  singles:      () => fetchJSON<{singles: SingleSnapshot[]}>('/api/dashboard/singles'),
  vwap:         () => fetchJSON<{vwap: VWAPMonitorEntry[]}>('/api/dashboard/vwap'),
  signalA:      () => fetchJSON<SignalAMonitorSnapshot>('/api/dashboard/signal-a'),
  replayStatus: () => fetchJSON<ReplayStatusResponse>('/api/replay/status'),
  replayJump:   (time: string) => fetch('/api/replay/jump', {...}),
}
```

### 4.4 Socket.IO Client

**File**: `dashboard/src/api/socket.ts`

- Lazy initialization (created on first use)
- Transports: WebSocket first, falls back to polling
- Single global instance (no per-component connections)
- Event: `dashboard:snapshot` → full `DashboardSnapshot` object

---

## 5. Usage Scenarios

### 5.1 Live Monitoring (Production)

During market hours, monitor the signal engine in real time:

```bash
# Start the server with live engine
uv run python -m tw_signal_engine.cli.run_server \
  --date $(date +%Y%m%d) \
  --mode live \
  --config exec/cfg/parameter.cfg \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --port 8000
```

Open `http://localhost:8000` in a browser. The dashboard auto-detects live mode and connects via WebSocket for real-time updates.

### 5.2 Paced Replay (Development/Demo)

Replay a historical day with simulated timing for dashboard development:

```bash
# Start the server with paced file replay
uv run python -m tw_signal_engine.cli.run_server \
  --date 20260129 \
  --mode live \
  --paced --speed 60.0 \
  --config exec/cfg/parameter.cfg \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv
```

This replays the day at 60× speed (~4.5 minutes) while serving the dashboard at `http://localhost:8000`. The frontend sees this as "live mode" (WebSocket updates flow in real time).

### 5.3 Parquet Replay with Time-Travel

Review a historical day with instant time-travel:

```bash
# Step 1: Generate Parquet snapshots (one-time per date)
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date 20260129 --snapshots \
  --config exec/cfg/parameter.cfg \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv

# Step 2: Start server in replay mode
uv run python -m tw_signal_engine.cli.run_server \
  --date 20260129 --mode replay --port 8000
```

Open `http://localhost:8000`. The replay timeline appears. Click any minute to jump instantly.

### 5.4 API-Only Usage (No Browser)

```bash
# Check engine status
curl http://localhost:8000/api/status

# Get strong groups
curl http://localhost:8000/api/dashboard/groups

# Get Signal A monitor
curl http://localhost:8000/api/dashboard/signal-a

# Time-travel in replay mode
curl -X POST http://localhost:8000/api/replay/jump \
  -H 'Content-Type: application/json' \
  -d '{"time": "10:30"}'
```

---

## 6. Testing and Verification

### 6.1 Backend Unit Tests

**Start the server and hit endpoints**:

```bash
# Start server in replay mode (requires Parquet snapshots)
uv run python -m tw_signal_engine.cli.run_server --date 20260129 --mode replay &

# Verify API responses
curl -s http://localhost:8000/api/status | python -m json.tool
curl -s http://localhost:8000/api/dashboard/groups | python -m json.tool
curl -s http://localhost:8000/api/dashboard/signal-a | python -m json.tool

# Test replay jump
curl -s -X POST http://localhost:8000/api/replay/jump \
  -H 'Content-Type: application/json' \
  -d '{"time": "10:00"}' | python -m json.tool
```

### 6.2 Frontend Development

```bash
cd dashboard
npm install
npm run dev    # Vite dev server with HMR at http://localhost:5173
```

The Vite dev server proxies `/api` to the backend (configure in `vite.config.ts`). This allows hot-reloading the frontend while the backend runs separately.

### 6.3 Building for Production

```bash
cd dashboard
npm run build  # Output to dashboard/dist/
```

The built SPA is served by FastAPI's `StaticFiles` mount — no separate web server needed.

### 6.4 Verifying WebSocket Push

```python
# Quick Socket.IO test client
import socketio

sio = socketio.Client()

@sio.on("dashboard:snapshot")
def on_snapshot(data):
    print(f"Snapshot: tick_count={data['tick_count']}, time={data['timestamp']}")
    print(f"  Groups: {len(data.get('groups', []))}")
    print(f"  Signal A entered: {len(data.get('signal_a', {}).get('entered', []))}")

sio.connect("http://localhost:8000")
sio.wait()
```

### 6.5 Verifying Data Consistency

The dashboard data should match the engine's CSV output:

1. Run a paced replay with the dashboard server
2. After completion, compare:
   - Dashboard's `signal_a.exited[]` → should match `report_trades.csv`
   - Dashboard's `groups[]` at each minute → should match Parquet snapshots
3. Run the same date as a batch replay and diff outputs

### 6.6 Edge Cases to Test

| Scenario | How to test | Expected |
|---|---|---|
| Server starts before engine ready | Start server, immediately hit API | `{"mode": "live", "tick_count": 0}`, empty dashboard |
| Engine fatal error | Kill Redis while live engine running | `engine_status: "fatal"`, error message in API |
| Replay with no Parquet file | Start replay mode without running `--snapshots` | `{"enabled": true, "ready": false}`, empty dashboard |
| WebSocket disconnect | Reload browser page | Socket reconnects, data resumes |
| Stale data | Stop engine, keep server running | Frontend shows stale indicator after 5s |
| Multiple browser tabs | Open dashboard in 2+ tabs | All tabs receive WebSocket updates |

---

## 7. File Map

### Backend

| File | Purpose |
|---|---|
| `src/tw_signal_engine/server/app.py` | FastAPI app, all routes, Socket.IO setup, static file mount |
| `src/tw_signal_engine/server/live_state.py` | Thread-safe state holder for live mode |
| `src/tw_signal_engine/server/replay_manager.py` | Parquet-backed time-travel for replay mode |
| `src/tw_signal_engine/server/dashboard_snapshot.py` | Python dataclasses for dashboard data models |
| `src/tw_signal_engine/cli/run_server.py` | Server CLI entry point |

### Frontend

| File | Purpose |
|---|---|
| `dashboard/src/App.tsx` | Router and top-level layout |
| `dashboard/src/hooks/useDashboardData.ts` | Central data hook (WebSocket + HTTP polling) |
| `dashboard/src/api/client.ts` | Typed HTTP API client |
| `dashboard/src/api/socket.ts` | Socket.IO client wrapper |
| `dashboard/src/types/dashboard.ts` | TypeScript interfaces (mirrors Python dataclasses) |
| `dashboard/src/pages/MarketOverview.tsx` | Groups + singles + VWAP page |
| `dashboard/src/pages/SignalAMonitor.tsx` | Signal A lifecycle page |
| `dashboard/src/components/groups/` | Group grid and card components |
| `dashboard/src/components/signal/` | Preparing, active, exited card components |
| `dashboard/src/components/vwap/` | VWAP monitoring table |
| `dashboard/src/components/replay/` | Replay timeline controls |
