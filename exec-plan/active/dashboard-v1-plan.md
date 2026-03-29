# Dashboard V1 — Execution Plan

> **Date**: 2026-03-29
> **Status**: COMPLETED — Phases 1-6 COMPLETE
> **Scope**: Two-page real-time dashboard for the signal engine (live + replay modes)

### Execution Status

- [x] Phase 1 — Backend: dashboard snapshot models, replay/live serialization, API enrichment, Socket.IO push
- [x] Phase 2 — Frontend Foundation: Vite scaffold, shared types, API/socket clients, unified dashboard hook
- [x] Phase 3 — Market Overview Page: tabs + 強勢族群/強勢個股/VWAP monitor views
- [x] Phase 4 — Signal A Monitoring Page: counters + 準備掛單/已進場/已出場 + detail monitor table
- [x] Phase 5 — Replay Mode Support: mode detection, replay jump controls, timeline slider, auto-play/step
- [x] Phase 6 — Integration & Polish: static serving, connection/staleness status, responsive layout, inline error surfacing

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Phase 1 — Backend: Dashboard Snapshot & API Enrichment](#3-phase-1--backend-dashboard-snapshot--api-enrichment)
4. [Phase 2 — Frontend Foundation](#4-phase-2--frontend-foundation)
5. [Phase 3 — Market Overview Page](#5-phase-3--market-overview-page)
6. [Phase 4 — Signal A Monitoring Page](#6-phase-4--signal-a-monitoring-page)
7. [Phase 5 — Replay Mode Support](#7-phase-5--replay-mode-support)
8. [Phase 6 — Integration & Polish](#8-phase-6--integration--polish)
9. [Execution Order & Dependencies](#9-execution-order--dependencies)
10. [Open Decisions](#10-open-decisions)

---

## 1. Overview

### Goals

Build a React + Vite single-page application served from the existing FastAPI server.
Two main pages:

| Page | Tabs / Views | Purpose |
|---|---|---|
| **Market Overview** | 強勢族群, 強勢個股, VWAP 監控 | Group/stock screening results with real-time price and VWAP data |
| **Signal A 監測** | (single view) | Signal A state machine monitoring — preparing, entered, exited positions |

Both pages must work in **live mode** (Redis streaming) and **replay mode** (Parquet time-travel).

### Design Language

Dark theme matching the prototype screenshots:

- Background: `#0d1117`, Cards: `#161b22`, Borders: `#30363d`
- Text: `#e6edf3` primary, `#8b949e` secondary
- Green `#3fb950` (positive / entered), Red `#f85149` (negative / stop-loss)
- Orange `#d29922` (warning / near-VWAP), Yellow `#e3b341` (highlight values)

---

## 2. Architecture

```
┌───────────────────────────────────────────────────────┐
│  React + Vite SPA                                     │
│  ┌────────────────────┐  ┌──────────────────────────┐ │
│  │ Page 1: Market      │  │ Page 2: Signal A 監測     │ │
│  │ ├ 強勢族群 (tab)     │  │ ├ Summary counters       │ │
│  │ ├ 強勢個股 (tab)     │  │ ├ 準備掛單 (preparing)    │ │
│  │ └ VWAP 監控 (tab)   │  │ ├ 已進場 (active)        │ │
│  └────────────────────┘  │ ├ 已出場 (closed)         │ │
│                          │ └ Detail table            │ │
│                          └──────────────────────────┘ │
│                                                       │
│  Data layer:                                          │
│    Socket.IO subscription (live push, ~1s interval)   │
│    REST polling fallback  (2s interval)               │
└───────────────────────────────────────────────────────┘
                         │
                    /api  │  /socket.io
                         ▼
┌───────────────────────────────────────────────────────┐
│  FastAPI Server                                       │
│                                                       │
│  New endpoints:                                       │
│    GET /api/dashboard/groups     → list[GroupSnapshot] │
│    GET /api/dashboard/singles    → list[MemberSnapshot]│
│    GET /api/dashboard/vwap       → list[VWAPEntry]    │
│    GET /api/dashboard/signal-a   → SignalAMonitor     │
│                                                       │
│  Existing endpoints (unchanged):                      │
│    GET  /api/status                                   │
│    GET  /api/config                                   │
│    POST /api/replay/jump                              │
│    GET  /api/replay/status                            │
│                                                       │
│  Socket.IO events (new):                              │
│    dashboard:snapshot   (periodic, ~1s)               │
│                                                       │
│  Static files:                                        │
│    /  → dashboard/dist/  (production build)           │
└───────────────────────────────────────────────────────┘
                         │
                    hooks │
                         ▼
┌───────────────────────────────────────────────────────┐
│  Engine Thread (replay_session / live session)        │
│                                                       │
│  on_minute hook → build_dashboard_snapshot()           │
│    reads from:                                        │
│      StrongGroupEvaluator.to_snapshot()               │
│      StrongSingleEvaluator.to_snapshot()  (if enabled)│
│      signal_a_states dict                             │
│      position_state (open trades, completed trades)   │
│      idx_calcs (per-symbol VWAP, day_high, day_low)   │
│      f1_map (reference data — names, prev_close)      │
│                                                       │
│  → pushes DashboardSnapshot to LiveState              │
│  → LiveState serves it to API + Socket.IO             │
└───────────────────────────────────────────────────────┘
```

### Data Flow by Mode

| Mode | Data Source | Update Mechanism |
|---|---|---|
| **Live** | Engine thread → `LiveState` snapshot buffer | Socket.IO push (~1s) + REST polling fallback (2s) |
| **Replay** | Parquet files → `ReplayManager` | `POST /api/replay/jump` returns full snapshot on demand |

Both modes produce the same `DashboardSnapshot` schema.
Frontend components are mode-agnostic — only the data-fetching hook differs.

---

## 3. Phase 1 — Backend: Dashboard Snapshot & API Enrichment

### 1.1 Define `DashboardSnapshot` data model

**New file**: `src/tw_signal_engine/server/dashboard_snapshot.py`

This module defines the canonical data structures consumed by all dashboard API
endpoints. Using `dataclass` for the models (matching existing codebase style)
with a `to_dict()` helper for JSON serialization.

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict

# ── Strong Group ──

@dataclass(slots=True)
class MemberSnapshot:
    """One stock within a strong group."""
    symbol: str
    name: str                    # Chinese name (from ReferenceSymbol / GroupMembership)
    price: float                 # 現價 — actual price (divided by 10000)
    pct_chg: float               # 漲幅 — (price - prev_close) / prev_close
    vwap: float                  # VWAP — actual price (divided by 10000)
    vwap_pct_chg: float          # VWAP 漲幅 — (vwap - prev_close) / prev_close
    cum_vol_ratio: float         # 累積量比 — cumulative volume / monthly avg volume
    vol_shrink_ratio: float      # 量縮比 — intraday volume profile metric
    member_rank: int             # Rank within group by VWAP % change

@dataclass(slots=True)
class GroupSnapshot:
    """One strong group with its members."""
    group_name: str
    group_rank: int              # Rank among all groups by avg % change
    avg_pct_chg: float           # 平均漲幅 — group average percent change
    vol_ratio: float             # 量比 — group cumulative vol / monthly avg
    avg_vol_surge: float         # 平均爆量 — average volume surge across members
    members: list[MemberSnapshot] = field(default_factory=list)

# ── Strong Single ──

@dataclass(slots=True)
class SingleSnapshot:
    """One individually-strong stock (not via group)."""
    symbol: str
    name: str
    group_name: str              # Primary group (if any)
    price: float
    pct_chg: float
    vwap: float
    vwap_pct_chg: float
    cum_vol_ratio: float
    vol_shrink_ratio: float

# ── VWAP Monitor ──

@dataclass(slots=True)
class VWAPMonitorEntry:
    """Per-symbol VWAP tracking row."""
    symbol: str
    name: str
    group_name: str              # Primary group tag (e.g., "G12 IC 零組件通路商")
    price: float                 # 現價
    vwap: float                  # VWAP
    vwap_pct: float              # VWAP% — (vwap - prev_close) / prev_close
    pv_ratio: float              # P/VWAP — price / vwap
    signal_a_state: str          # "idle" | "near_vwap" | "triggered" | "forbidden"
    status: str                  # Display label: "接近VWAP", "持倉中", "停利出場", etc.

# ── Signal A Monitor ──

@dataclass(slots=True)
class PreparingEntry:
    """Stock qualifying for entry — screening passed + near_vwap detected."""
    symbol: str
    name: str
    group_name: str
    group_tag: str               # e.g., "G12 電供"
    order_price: float           # 掛單價 — estimated entry price
    current_price: float         # 現價
    distance_pct: float          # 距進場 — % distance from trigger
    vwap: float
    day_low: float               # 最低
    stop_loss: float             # 停損 — computed stop-loss level
    near_vwap_pv_ratio: float    # P/VWAP at time of near detection

@dataclass(slots=True)
class ActivePosition:
    """Currently held position from Signal A entry."""
    symbol: str
    name: str
    group_name: str
    group_tag: str
    entry_price: float           # 進場
    current_price: float         # 現價
    pnl_pct: float               # 損益 — unrealized P&L %
    stop_loss: float             # 停損
    take_profit: float           # 停利
    day_high: float              # DH — day high at entry
    entry_time: str              # HH:MM:SS

@dataclass(slots=True)
class CompletedTrade:
    """Closed trade from today's session."""
    symbol: str
    name: str
    group_name: str
    group_tag: str
    entry_price: float           # 進場
    exit_price: float            # 出場
    pnl_pct: float               # 損益
    entry_time: str              # 進場時間 HH:MM:SS
    exit_time: str               # 出場時間 HH:MM:SS
    exit_cause: str              # "take_profit" | "stop_loss" | "time_exit" | "bailout"

@dataclass(slots=True)
class SignalCounters:
    """Summary bar counters."""
    qualified: int = 0           # 符合條件
    not_qualified: int = 0       # 不符條件
    holding: int = 0             # 持倉
    take_profit: int = 0         # 停利
    stop_loss: int = 0           # 停損
    forbidden: int = 0           # 禁止

@dataclass(slots=True)
class SignalAMonitorSnapshot:
    """Full Signal A monitoring view."""
    preparing: list[PreparingEntry] = field(default_factory=list)
    entered: list[ActivePosition] = field(default_factory=list)
    exited: list[CompletedTrade] = field(default_factory=list)
    counters: SignalCounters = field(default_factory=SignalCounters)

# ── Top-level snapshot ──

@dataclass(slots=True)
class DashboardSnapshot:
    """Complete dashboard state at a point in time."""
    timestamp: str               # HH:MM:SS format
    time_raw: int                # match_time_str integer
    tick_count: int = 0

    groups: list[GroupSnapshot] = field(default_factory=list)
    singles: list[SingleSnapshot] = field(default_factory=list)
    vwap_monitor: list[VWAPMonitorEntry] = field(default_factory=list)
    signal_a: SignalAMonitorSnapshot = field(default_factory=SignalAMonitorSnapshot)

    def to_dict(self) -> dict:
        return asdict(self)
```

**Estimated size**: ~150 lines.

---

### 1.2 Add `to_snapshot()` methods to evaluators

Add serialization methods that read internal state without modifying it.

#### `StrongGroupEvaluator.to_snapshot()`

**File**: `src/tw_signal_engine/screening/evaluate_strong_group.py`

Add method:

```python
def to_snapshot(self, idx_map: dict[str, IndexData]) -> list[GroupSnapshot]:
    """Serialize current group rankings and members to dashboard format."""
    result = []
    for gain, group_name in self.group_rank.iter_ranked():
        members_ranked = self.group_member_vwap_rank.get(group_name)
        if members_ranked is None:
            continue

        # Build member list
        member_snapshots = []
        for rank_idx, (vwap_pct, symbol) in enumerate(members_ranked.iter_ranked(), 1):
            ref = self.f1_map.get(symbol)
            name = ref.name if ref else symbol
            prev_close = self._prev_close_cache.get(symbol, 0)
            price_raw = self.price_last.get(symbol, 0)
            idx = idx_map.get(symbol)
            vwap_raw = idx.vwap if idx else 0.0

            vol_cumu = self.vol_cumu.get(symbol, 0)
            month_avg = self._month_avg_tv.get(symbol, 1)
            cum_vol_ratio = vol_cumu / (month_avg / 10000) if month_avg > 0 else 0.0
            # vol_shrink_ratio: TODO — requires volume profile data

            member_snapshots.append(MemberSnapshot(
                symbol=symbol,
                name=name,
                price=price_raw / 10000,
                pct_chg=self._percentage_chg(symbol, price_raw),
                vwap=vwap_raw / 10000,
                vwap_pct_chg=vwap_pct,
                cum_vol_ratio=cum_vol_ratio,
                vol_shrink_ratio=0.0,  # placeholder
                member_rank=rank_idx,
            ))

        # Group-level aggregates
        avg_pct = self._group_percentage_chg(group_name, self.config.is_weighted_avg)
        group_tv_cumu = self.group_trading_value_cumu.get(group_name, 0)
        group_tv_month = self.group_trading_value_month_avg_sum.get(group_name, 1)
        vol_ratio = group_tv_cumu / group_tv_month if group_tv_month > 0 else 0.0

        result.append(GroupSnapshot(
            group_name=group_name,
            group_rank=self.group_rank.get_rank(group_name),
            avg_pct_chg=avg_pct,
            vol_ratio=vol_ratio,
            avg_vol_surge=0.0,  # placeholder — needs volume profile
            members=member_snapshots,
        ))
    return result
```

**Changes**: ~50 lines added to `evaluate_strong_group.py`.

#### Signal A state serialization

No new method on a class — the signal A states are a plain `dict[str, SignalAState]`.
The snapshot builder in the replay session will read from this dict directly:

```python
def _signal_a_state_label(state: SignalAState) -> str:
    if state.triggered:
        return "triggered"
    if state.forbidden:
        return "forbidden"
    if state.near_vwap:
        return "near_vwap"
    return "idle"
```

---

### 1.3 Build `build_dashboard_snapshot()` in replay session

**File**: `src/tw_signal_engine/replay/replay_session.py`

Add a method to `ReplaySession` (or a standalone function that takes session state):

```python
def build_dashboard_snapshot(self) -> DashboardSnapshot:
    """Serialize current engine state into a dashboard-consumable snapshot."""
    # 1. Strong groups
    groups = self._strong_group_eval.to_snapshot(self._idx_map)

    # 2. Strong singles (if evaluator exists)
    singles = self._strong_single_eval.to_snapshot(...) if self._strong_single_eval else []

    # 3. VWAP monitor — iterate all symbols in universe
    vwap_entries = []
    for symbol in self._replay_universe:
        idx = self._idx_map.get(symbol)
        if idx is None:
            continue
        sig_state = self._signal_a_states.get(symbol)
        state_label = _signal_a_state_label(sig_state) if sig_state else "idle"
        # ... build VWAPMonitorEntry ...
        vwap_entries.append(entry)

    # 4. Signal A monitor
    signal_a = self._build_signal_a_monitor()

    return DashboardSnapshot(
        timestamp=format_time(self._last_time_str),
        time_raw=self._last_time_str,
        tick_count=self._tick_count,
        groups=groups,
        singles=singles,
        vwap_monitor=vwap_entries,
        signal_a=signal_a,
    )
```

The `_build_signal_a_monitor()` helper combines:
- **preparing**: symbols where `screening qualified == True` AND `signal_a_state.near_vwap == True`
- **entered**: read from `position_state.open_trades`
- **exited**: read from completed trades list
- **counters**: count each category

**Changes**: ~80 lines added to `replay_session.py`.

---

### 1.4 Wire snapshot into `LiveState`

**File**: `src/tw_signal_engine/server/live_state.py`

Add snapshot storage and accessors:

```python
class LiveState:
    def __init__(self) -> None:
        # ... existing fields ...
        self._dashboard_snapshot: DashboardSnapshot | None = None

    def update_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Called from on_minute hook with the latest snapshot."""
        with self._lock:
            self._dashboard_snapshot = snapshot

    def get_dashboard_groups(self) -> list[dict]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(g) for g in self._dashboard_snapshot.groups]

    def get_dashboard_singles(self) -> list[dict]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(s) for s in self._dashboard_snapshot.singles]

    def get_dashboard_vwap(self) -> list[dict]:
        with self._lock:
            if self._dashboard_snapshot is None:
                return []
            return [asdict(v) for v in self._dashboard_snapshot.vwap_monitor]

    def get_dashboard_signal_a(self) -> dict:
        with self._lock:
            if self._dashboard_snapshot is None:
                return asdict(SignalAMonitorSnapshot())
            return asdict(self._dashboard_snapshot.signal_a)
```

The `on_minute` hook in `SessionHooks` will call `live_state.update_snapshot(snapshot)`.

**Changes**: ~60 lines added to `live_state.py`.

---

### 1.5 New API endpoints

**File**: `src/tw_signal_engine/server/app.py`

```python
@app.get("/api/dashboard/groups")
def dashboard_groups() -> dict[str, Any]:
    """Strong group cards with member tables."""
    if _server_mode == "live" and _live_state is not None:
        return {"groups": _live_state.get_dashboard_groups()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "groups" in snapshot:
            return {"groups": snapshot["groups"]}
    return {"groups": []}


@app.get("/api/dashboard/singles")
def dashboard_singles() -> dict[str, Any]:
    """Strong individual stocks."""
    if _server_mode == "live" and _live_state is not None:
        return {"singles": _live_state.get_dashboard_singles()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "singles" in snapshot:
            return {"singles": snapshot["singles"]}
    return {"singles": []}


@app.get("/api/dashboard/vwap")
def dashboard_vwap() -> dict[str, Any]:
    """VWAP monitoring table for all universe symbols."""
    if _server_mode == "live" and _live_state is not None:
        return {"vwap": _live_state.get_dashboard_vwap()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "vwap_monitor" in snapshot:
            return {"vwap": snapshot["vwap_monitor"]}
    return {"vwap": []}


@app.get("/api/dashboard/signal-a")
def dashboard_signal_a() -> dict[str, Any]:
    """Signal A monitoring — preparing, entered, exited, counters."""
    if _server_mode == "live" and _live_state is not None:
        return _live_state.get_dashboard_signal_a()
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "signal_a" in snapshot:
            return snapshot["signal_a"]
    return asdict(SignalAMonitorSnapshot())
```

**Changes**: ~50 lines added to `app.py`.

---

### 1.6 Socket.IO periodic push

**File**: `src/tw_signal_engine/server/app.py`

In live mode, after each `update_snapshot()`, emit the full snapshot via Socket.IO:

```python
async def push_dashboard_snapshot(snapshot: DashboardSnapshot) -> None:
    await sio.emit("dashboard:snapshot", snapshot.to_dict())
```

The `on_minute` hook (called from the engine thread) schedules this into the
asyncio event loop. ~10 lines.

---

### 1.7 Enrich Parquet snapshot writer

**File**: `src/tw_signal_engine/replay/replay_session.py` (snapshot writing section)

Currently the Parquet snapshots store `strong_groups`, `signals`, `positions` as
JSON strings. Enrich to include the full `DashboardSnapshot.to_dict()` output:

- Add columns: `dashboard_groups`, `dashboard_singles`, `dashboard_vwap`, `dashboard_signal_a`
- Or replace the existing columns with a single `dashboard_snapshot` JSON column

This ensures `ReplayManager` can serve the same data format in replay mode.

**Changes**: ~30 lines in the snapshot writer.

Update `ReplayManager._row_to_dict()` to parse the new fields.

---

### 1.8 Backend summary

| File | Action | Est. Lines |
|---|---|---|
| `server/dashboard_snapshot.py` | **New** — data models | ~150 |
| `screening/evaluate_strong_group.py` | Add `to_snapshot()` | ~50 |
| `replay/replay_session.py` | Add `build_dashboard_snapshot()` + wire `on_minute` | ~80 |
| `server/live_state.py` | Add snapshot storage + getters | ~60 |
| `server/app.py` | Add 4 endpoints + Socket.IO push | ~60 |
| `replay/session_hooks.py` | Extend `on_minute` signature (if needed) | ~5 |
| Snapshot writer section | Enrich Parquet columns | ~30 |
| **Total backend** | | **~435** |

---

## 4. Phase 2 — Frontend Foundation

### 2.1 Project scaffold

Create a `dashboard/` directory at repo root:

```
dashboard/
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── vite.config.ts
├── src/
│   ├── main.tsx                     # React root mount
│   ├── App.tsx                      # Router + layout shell
│   ├── api/
│   │   ├── client.ts                # fetch() wrapper with base URL + error handling
│   │   └── socket.ts                # Socket.IO connection manager
│   ├── hooks/
│   │   ├── useDashboardData.ts      # Polling + socket merge logic
│   │   └── useReplayControls.ts     # Time-travel state for replay mode
│   ├── pages/
│   │   ├── MarketOverview.tsx        # Page 1 shell + tab routing
│   │   └── SignalAMonitor.tsx        # Page 2
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Header.tsx            # Top bar: title, nav links, live indicator
│   │   │   ├── StatusBar.tsx         # Last update time, connection status
│   │   │   └── TabBar.tsx            # Toggle buttons (強勢族群 / 強勢個股 / VWAP 監控)
│   │   ├── groups/
│   │   │   ├── GroupCard.tsx          # Single group card with member table
│   │   │   └── GroupGrid.tsx          # 3-column card grid
│   │   ├── singles/
│   │   │   └── SinglesTable.tsx       # Strong individual stocks table
│   │   ├── vwap/
│   │   │   └── VWAPTable.tsx          # VWAP monitor table
│   │   ├── signal/
│   │   │   ├── CounterBar.tsx         # Summary counters (符合條件 / 不符條件 / ...)
│   │   │   ├── PreparingCards.tsx     # 準備掛單 section
│   │   │   ├── ActiveCards.tsx        # 已進場 section
│   │   │   ├── ExitedCards.tsx        # 已出場 section
│   │   │   └── MonitorTable.tsx       # Detail table at bottom
│   │   └── replay/
│   │       └── TimelineSlider.tsx     # Time scrubber for replay mode
│   ├── types/
│   │   └── dashboard.ts              # TypeScript interfaces (mirrors backend models)
│   └── styles/
│       ├── globals.css                # CSS custom properties (theme), reset
│       └── components.css             # Component-specific styles
```

### 2.2 Dependencies

```json
{
  "dependencies": {
    "react": "^19",
    "react-dom": "^19",
    "react-router-dom": "^7",
    "socket.io-client": "^4"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4",
    "typescript": "^5.7",
    "vite": "^6",
    "@types/react": "^19",
    "@types/react-dom": "^19"
  }
}
```

No component library — custom CSS matching the dark prototype. Keeps bundle small
and avoids fighting a library's design opinions.

### 2.3 Vite configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/socket.io': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
```

In development: `npm run dev` runs Vite at :5173, proxying API to FastAPI at :8000.
In production: `npm run build` → `dist/`, served by FastAPI.

### 2.4 TypeScript types

`src/types/dashboard.ts` — mirrors the Python dataclasses 1:1:

```typescript
export interface MemberSnapshot {
  symbol: string
  name: string
  price: number
  pct_chg: number
  vwap: number
  vwap_pct_chg: number
  cum_vol_ratio: number
  vol_shrink_ratio: number
  member_rank: number
}

export interface GroupSnapshot {
  group_name: string
  group_rank: number
  avg_pct_chg: number
  vol_ratio: number
  avg_vol_surge: number
  members: MemberSnapshot[]
}

// ... VWAPMonitorEntry, PreparingEntry, ActivePosition,
//     CompletedTrade, SignalCounters, SignalAMonitorSnapshot
```

### 2.5 API client

```typescript
// src/api/client.ts
const BASE = ''  // same origin in production; proxied in dev

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json()
}

export const api = {
  status:   () => fetchJSON<StatusResponse>('/api/status'),
  groups:   () => fetchJSON<{ groups: GroupSnapshot[] }>('/api/dashboard/groups'),
  singles:  () => fetchJSON<{ singles: SingleSnapshot[] }>('/api/dashboard/singles'),
  vwap:     () => fetchJSON<{ vwap: VWAPMonitorEntry[] }>('/api/dashboard/vwap'),
  signalA:  () => fetchJSON<SignalAMonitorSnapshot>('/api/dashboard/signal-a'),
  replayJump: (time: string) => fetch('/api/replay/jump', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time }),
  }).then(r => r.json()),
}
```

### 2.6 Socket.IO client

```typescript
// src/api/socket.ts
import { io, Socket } from 'socket.io-client'

let socket: Socket | null = null

export function connectSocket(): Socket {
  if (!socket) {
    socket = io({ transports: ['websocket', 'polling'] })
  }
  return socket
}

// Usage in hook:
// socket.on('dashboard:snapshot', (data: DashboardSnapshot) => setState(data))
```

### 2.7 Data-fetching hook

```typescript
// src/hooks/useDashboardData.ts
export function useDashboardData() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [mode, setMode] = useState<'live' | 'replay'>('live')
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    // 1. Check mode on mount
    api.status().then(s => setMode(s.mode))

    // 2. Socket.IO subscription (live mode)
    const socket = connectSocket()
    socket.on('connect', () => setConnected(true))
    socket.on('disconnect', () => setConnected(false))
    socket.on('dashboard:snapshot', (data) => setSnapshot(data))

    // 3. Polling fallback (2s interval)
    const poll = setInterval(async () => {
      const [groups, singles, vwap, signalA] = await Promise.all([
        api.groups(), api.singles(), api.vwap(), api.signalA(),
      ])
      setSnapshot(prev => ({ ...prev, groups: groups.groups, ... }))
    }, 2000)

    return () => { socket.disconnect(); clearInterval(poll) }
  }, [])

  return { snapshot, mode, connected }
}
```

### 2.8 Routing

```typescript
// src/App.tsx
<BrowserRouter>
  <Header mode={mode} connected={connected} />
  <Routes>
    <Route path="/" element={<MarketOverview />} />
    <Route path="/signal-a" element={<SignalAMonitor />} />
  </Routes>
</BrowserRouter>
```

Two top-level routes. Header provides navigation links between them.

---

## 5. Phase 3 — Market Overview Page

### 3.1 Page structure

```
┌────────────────────────────────────────────────────────┐
│  Market Strong Groups                   10:14:38 ● Live │
├────────────────────────────────────────────────────────┤
│  [✓ 強勢族群]  [強勢個股]  [VWAP 監控]                    │
├────────────────────────────────────────────────────────┤
│                                                        │
│  (active tab content rendered below)                   │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 3.2 強勢族群 tab — Group Cards Grid

**Component**: `GroupGrid.tsx` + `GroupCard.tsx`

Layout: CSS grid, 3 columns on desktop, 2 on tablet, 1 on mobile.

Each `GroupCard`:
```
┌──────────────────────────────────────────┐
│  低軌衛星     平均漲幅  量比   平均爆量    │
│              7.17%   0.75x   0.77x     │
│──────────────────────────────────────────│
│  代碼   名稱   現價   漲幅   VWAP  累積量比 量縮比│
│  6568  宏觀   217  6.9%  219.33  1.35x  0.83 │
│  2313  華通  228.5 9.07% 225.84  0.77x  1.65 │
└──────────────────────────────────────────┘
```

Color rules:
- 漲幅 > 0: green text
- 累積量比 > 1.0: red text (high volume surge), else green
- 量縮比 > 1.0: red text

Data source: `snapshot.groups` (sorted by `group_rank`).

### 3.3 強勢個股 tab — Singles Table

**Component**: `SinglesTable.tsx`

Full-width table:

| 代碼 | 名稱 | 族群 | 現價 | 漲幅 | VWAP | VWAP% | 累積量比 |
|---|---|---|---|---|---|---|---|

Data source: `snapshot.singles`.

Sorted by VWAP% descending. Color coding same as group members.

### 3.4 VWAP 監控 tab — VWAP Monitor Table

**Component**: `VWAPTable.tsx`

Table matching the bottom section of the Signal C prototype:

| G# | 族群 | 代碼 | 名稱 | 現價 | VWAP | VWAP% | P/VWAP | 狀態 |
|---|---|---|---|---|---|---|---|---|

Color rules:
- VWAP% column: green gradient (higher = darker green)
- P/VWAP: green if > 1.0 (above VWAP), red if < 1.0
- 狀態 column: color-coded badge
  - 接近VWAP: yellow
  - 持倉中: green highlight row
  - 停利出場: green + "+X.XX% @ price (HH:MM:SS)"
  - 停損出場: red
  - —: grey (idle)

Data source: `snapshot.vwap_monitor`.

### 3.5 Real-time updates

- Socket.IO `dashboard:snapshot` event replaces the full `snapshot.groups`, `snapshot.singles`, `snapshot.vwap_monitor` arrays.
- React key on `symbol` ensures smooth DOM diffing.
- Optional: CSS transition on price/percentage changes (brief flash on value change).

---

## 6. Phase 4 — Signal A Monitoring Page

### 4.1 Page structure

```
┌───────────────────────────────────────────────────────────────┐
│  Signal A 監測                                                │
├───────────────────────────────────────────────────────────────┤
│  符合條件  不符條件  持倉   停利   停損   禁止   最後更新         │
│     4       42      1      2      1     4    上午10:14:48     │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─ 準備掛單 ─────────────────────────────────────────────┐   │
│  │  [6282 康舒 card]    [4768 晶呈科技 card]               │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─ 已進場 ──────────────────────────────────────────────┐   │
│  │  [3702 大聯大 card]                                    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─ 已出場 (停利 2 / 停損 1) ────────────────────────────┐   │
│  │  [6285 啟碁 ✓]  [5347 世界 ✓]  [8086 宏捷科 ✗]        │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─ Detail Table ────────────────────────────────────────┐   │
│  │  G# | 族群 | 代碼 | 名稱 | 現價 | VWAP | VWAP% | ... │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 4.2 Summary counter bar

**Component**: `CounterBar.tsx`

Horizontal bar with 6 counters + last update time.
Each counter is a labeled number with color:
- 符合條件: green
- 不符條件: default
- 持倉: yellow
- 停利: green
- 停損: red
- 禁止: red

Data source: `snapshot.signal_a.counters`.

### 4.3 準備掛單 section (Preparing Orders)

**Component**: `PreparingCards.tsx`

Blue-bordered card per qualifying stock. Criteria for inclusion:
- Strong-group screening passed (qualified == True)
- AND Signal A state == `near_vwap`

Card content:
```
┌─────────────────────────────────────────────┐
│  6282  康舒   G12 電供                       │
│  掛單價 47.60  現價 47.4  距進場 +0.42%       │
│  VWAP 47.23   最低 47.2   停損 46.99         │
└─────────────────────────────────────────────┘
```

Fields:
- **掛單價**: estimate = current price (or configurable based on bounce ratio)
- **距進場**: `(price - low_since_near) / low_since_near` as % — how close to bounce trigger
- **停損**: `entry_vwap * (1 - stop_loss_ratio)` — pre-computed stop-loss if entered now

### 4.4 已進場 section (Active Positions)

**Component**: `ActiveCards.tsx`

Green-bordered card per open position:
```
┌─────────────────────────────────────────────────────────┐
│  3702  大聯大   G12 IC 零組件通路商                       │
│  進場 96   現價 96.7   損益 +0.73%                       │
│  停損 94.9   停利 99.9   DH 97.8                        │
└─────────────────────────────────────────────────────────┘
```

P&L color: green if positive, red if negative.

### 4.5 已出場 section (Completed Trades)

**Component**: `ExitedCards.tsx`

Section header shows summary: "已出場 (停利 2 / 停損 1)"

Cards colored by exit cause:
- **Green card** (take-profit): `+3.39%`, shows entry/exit prices and times
- **Red card** (stop-loss): `-1.55%`, shows entry/exit prices and times

```
┌─────────────────────────────────────────────────────────┐
│  6285  啟碁   G15 網路通訊                               │
│  進場 177   出場 183   損益 +3.39%                       │
│  進場時間 09:04:49   出場時間 09:45:00                    │
└─────────────────────────────────────────────────────────┘
```

### 4.6 Detail table (bottom)

**Component**: `MonitorTable.tsx`

Full VWAP monitor table filtered to Signal A universe symbols, with 狀態 showing
signal-specific states:

| G# | 族群 | 代碼 | 名稱 | 現價 | VWAP | VWAP% | P/VWAP | 狀態 |
|---|---|---|---|---|---|---|---|---|
| G12 | IC 零組件通路商 | 3702 | 大聯大 | 96.7 | 96.45 | 6.34% | 1.0026 | **持倉中** |
| G12 | 電供 | 6282 | 康舒 | 47.4 | 47.23 | 4.72% | 1.0036 | **接近VWAP** |

狀態 values and colors:
- 持倉中 (green bg): currently holding position
- 接近VWAP (orange): `near_vwap` state, preparing to enter
- 停利出場 (green text): exited with profit, show `+X.XX% @ price (HH:MM:SS)`
- 停損出場 (red text): exited with loss
- 禁止 (grey): `forbidden` state
- — (dim): `idle`

---

## 7. Phase 5 — Replay Mode Support

### 5.1 Mode detection on mount

```typescript
useEffect(() => {
  api.status().then(s => {
    setMode(s.mode)
    if (s.mode === 'replay') {
      // Fetch initial replay status (time range, readiness)
      api.replayStatus().then(setReplayInfo)
    }
  })
}, [])
```

### 5.2 Timeline slider component

**Component**: `TimelineSlider.tsx`

Only visible in replay mode. Positioned at the bottom of the page (sticky).

```
┌──────────────────────────────────────────────────────────┐
│  ▶ 09:00 ─────────────●───────────────────── 13:30       │
│                     10:14                                │
│                  [◀ -1m] [+1m ▶]                         │
└──────────────────────────────────────────────────────────┘
```

Features:
- Range: `replay_status.time_range.min_time` to `max_time`
- Dragging or clicking jumps: `POST /api/replay/jump { time: "HH:MM" }`
- Response contains full snapshot → updates all dashboard views
- Play button: auto-advance 1 minute per second via `setInterval`
- Step buttons: ±1 minute

### 5.3 Replay data hook

```typescript
// src/hooks/useReplayControls.ts
export function useReplayControls() {
  const [currentTime, setCurrentTime] = useState('09:00')
  const [playing, setPlaying] = useState(false)
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)

  const jumpTo = async (time: string) => {
    const result = await api.replayJump(time)
    if (result.snapshot) {
      setSnapshot(parseDashboardSnapshot(result.snapshot))
      setCurrentTime(time)
    }
  }

  // Auto-advance when playing
  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      setCurrentTime(prev => addMinutes(prev, 1))
    }, 1000)
    return () => clearInterval(id)
  }, [playing])

  useEffect(() => { jumpTo(currentTime) }, [currentTime])

  return { currentTime, playing, setPlaying, jumpTo, snapshot }
}
```

### 5.4 Unified data provider

Both modes feed into the same `DashboardSnapshot` state.
A top-level context provider selects the right data source:

```typescript
function DashboardProvider({ children }) {
  const { mode } = useServerMode()

  // Live mode: Socket.IO + polling
  const live = useLiveDashboardData()

  // Replay mode: jump-based
  const replay = useReplayControls()

  const snapshot = mode === 'live' ? live.snapshot : replay.snapshot
  const connected = mode === 'live' ? live.connected : true

  return (
    <DashboardContext.Provider value={{ snapshot, mode, connected, replay }}>
      {children}
      {mode === 'replay' && <TimelineSlider {...replay} />}
    </DashboardContext.Provider>
  )
}
```

All page components consume `DashboardContext` — they don't know or care about the mode.

---

## 8. Phase 6 — Integration & Polish

### 6.1 Production build & static serving

Add to `app.py`:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

dashboard_dist = Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "dist"
if dashboard_dist.exists():
    # Serve React SPA — must be mounted LAST (catch-all)
    app.mount("/", StaticFiles(directory=str(dashboard_dist), html=True), name="dashboard")
```

Build command added to project scripts:

```bash
cd dashboard && npm run build    # → dashboard/dist/
```

Single-process deployment:
```bash
uv run python -m tw_signal_engine.cli.run_server \
  --date 20260329 --mode live --port 8000
# Serves both API and dashboard on :8000
```

### 6.2 Connection status indicator

**Component**: `StatusBar.tsx` (top-right corner, matching prototype)

```
  ⚠ 6   10:14:38   ● Live
```

- Green dot + "Live": Socket.IO connected, data flowing
- Yellow dot + "Reconnecting...": Socket.IO disconnected, attempting reconnect
- Red dot + "Offline": connection failed
- Warning badge with count: number of alerts/anomalies (optional V1)

### 6.3 Value change animations

CSS transitions for price/percentage updates:
- Brief green flash when value increases
- Brief red flash when value decreases
- 300ms transition duration

```css
.value-updated-up { animation: flash-green 0.3s ease-out; }
.value-updated-down { animation: flash-red 0.3s ease-out; }

@keyframes flash-green {
  0% { background-color: rgba(63, 185, 80, 0.3); }
  100% { background-color: transparent; }
}
```

### 6.4 Responsive breakpoints

```css
/* Group cards grid */
.group-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(3, 1fr);  /* desktop */
}

@media (max-width: 1200px) {
  .group-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .group-grid { grid-template-columns: 1fr; }
}
```

### 6.5 Error boundaries

- API fetch errors: show inline warning banner, keep stale data visible (dimmed)
- Socket disconnect: auto-reconnect with exponential backoff (Socket.IO default)
- Data staleness: if no update for > 5 seconds in live mode, show "Data may be stale" warning

---

## 9. Execution Order & Dependencies

```
Phase 1 (Backend)              Phase 2 (Frontend scaffold)
───────────────                ────────────────────────────
1.1 Data models ──────┐       2.1 Scaffold + vite config ──┐
                      │       2.2 Dependencies              │
1.2 Evaluator         │       2.3 Proxy config              │
    to_snapshot() ────┤       2.4 TypeScript types ─────────┤
                      │       2.5 API client ───────────────┤
1.3 build_dashboard   │       2.6 Socket.IO client ─────────┤
    _snapshot() ──────┤       2.7 Data hook ────────────────┤
                      │       2.8 Routing ──────────────────┤
1.4 LiveState ────────┤                                     │
                      │                                     │
1.5 API endpoints ────┤                                     │
                      │                                     │
1.6 Socket.IO push ───┤                                     │
                      │                                     │
1.7 Parquet enrichment┤                                     │
                      ▼                                     ▼
               ┌──────────────────────────────────────────────┐
               │  Phase 3: Market Overview Page               │
               │  3.1 GroupCard + GroupGrid                    │
               │  3.2 強勢族群 tab                             │
               │  3.3 強勢個股 tab (SinglesTable)              │
               │  3.4 VWAP 監控 tab (VWAPTable)               │
               └──────────────────┬───────────────────────────┘
                                  │
               ┌──────────────────┴───────────────────────────┐
               │  Phase 4: Signal A Monitoring Page           │
               │  4.1 CounterBar                              │
               │  4.2 PreparingCards                          │
               │  4.3 ActiveCards                             │
               │  4.4 ExitedCards                             │
               │  4.5 MonitorTable                            │
               └──────────────────┬───────────────────────────┘
                                  │ (Phases 3 & 4 can run in parallel)
                                  │
               ┌──────────────────┴───────────────────────────┐
               │  Phase 5: Replay Mode                        │
               │  5.1 Mode detection                          │
               │  5.2 TimelineSlider                          │
               │  5.3 Replay data hook                        │
               │  5.4 Unified provider                        │
               └──────────────────┬───────────────────────────┘
                                  │
               ┌──────────────────┴───────────────────────────┐
               │  Phase 6: Integration & Polish               │
               │  6.1 Static file serving                     │
               │  6.2 Connection indicator                    │
               │  6.3 Value animations                        │
               │  6.4 Responsive layout                       │
               │  6.5 Error boundaries                        │
               └──────────────────────────────────────────────┘
```

### Parallelism opportunities

- Phase 1 (backend) and Phase 2 (frontend scaffold) are fully independent.
- Phase 3 and Phase 4 are independent of each other — can be built simultaneously.
- Phase 5 depends on 3+4 being complete (needs pages to add replay controls to).
- Phase 6 depends on 3+4+5.

---

## 10. Open Decisions

### 10.1 量縮比 (vol_shrink_ratio) calculation

The prototype shows this column but the current engine doesn't compute an explicit
"volume shrinkage ratio." Need to decide:

- **Option A**: `current_minute_volume / previous_minute_volume` — simple ratio
- **Option B**: `current_volume / expected_volume_at_this_time` — uses historical profile
- **Option C**: Defer to V2 — show placeholder "—" for now

### 10.2 Strong Singles evaluator

`StrongSingleEvaluator` exists but is disabled in config (`enabled: false`).
For the 強勢個股 tab:

- **Option A**: Enable it and add `to_snapshot()` — full implementation
- **Option B**: Show the tab but with "Coming soon" — minimal effort
- **Option C**: Only show symbols that are rank-1 in their group but not entered — reuse group data

### 10.3 Alert badge count

The prototype shows a warning triangle with count badge (top-right).
What should this count represent?

- Potential options: anomalous price gaps, data feed delays, circuit breaker events
- Can defer to V2 if not critical

### 10.4 掛單價 (order price) for preparing stocks

How to compute the estimated entry price shown in the 準備掛單 cards?

- **Option A**: Current ask price (best ask from depth data)
- **Option B**: Current match price (latest trade)
- **Option C**: `low_since_near * (1 + bounce_ratio)` — the trigger price

### 10.5 Snapshot update frequency

In live mode, how often should `build_dashboard_snapshot()` run?

- **Option A**: Every minute (via `on_minute` hook) — simple, low overhead
- **Option B**: Every N ticks (e.g., every 100 ticks) — more responsive
- **Option C**: On every signal state transition + every minute — event-driven + periodic

Recommendation: Start with **Option A** (every minute) for V1. Increase frequency
if users need sub-minute updates.
