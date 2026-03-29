"""FastAPI application for the signal engine web server."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tw_signal_engine.server.dashboard_snapshot import SignalAMonitorSnapshot
from tw_signal_engine.server.live_state import LiveState
from tw_signal_engine.server.replay_manager import ReplayManager

app = FastAPI(title="tw_signal_engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO for real-time signal push
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)

# These are set by the server CLI before starting uvicorn
_live_state: LiveState | None = None
_replay_manager: ReplayManager | None = None
_server_mode: str = "replay"
_dashboard_push_task: asyncio.Task[None] | None = None
_last_dashboard_emit_key: tuple[int, int] | None = None


def configure(
    mode: str,
    live_state: LiveState | None = None,
    replay_manager: ReplayManager | None = None,
) -> None:
    """Configure the app's data sources. Called before uvicorn.run()."""
    global _live_state, _replay_manager, _server_mode, _last_dashboard_emit_key
    _server_mode = mode
    _live_state = live_state
    _replay_manager = replay_manager
    _last_dashboard_emit_key = None


async def _push_dashboard_snapshot_loop() -> None:
    """Emit dashboard snapshots over Socket.IO at ~1s cadence in live mode."""
    global _last_dashboard_emit_key
    while True:
        await asyncio.sleep(1.0)
        if _server_mode != "live" or _live_state is None:
            continue
        snapshot = _live_state.get_dashboard_snapshot_dict()
        if snapshot is None:
            continue

        key: tuple[int, int] | None = None
        time_raw = snapshot.get("time_raw")
        tick_count = snapshot.get("tick_count")
        if isinstance(time_raw, int) and isinstance(tick_count, int):
            key = (time_raw, tick_count)
            if key == _last_dashboard_emit_key:
                continue
            _last_dashboard_emit_key = key

        await sio.emit("dashboard:snapshot", snapshot)


@app.on_event("startup")
async def _startup_dashboard_push() -> None:
    global _dashboard_push_task
    if _dashboard_push_task is None:
        _dashboard_push_task = asyncio.create_task(_push_dashboard_snapshot_loop())


@app.on_event("shutdown")
async def _shutdown_dashboard_push() -> None:
    global _dashboard_push_task
    if _dashboard_push_task is None:
        return
    _dashboard_push_task.cancel()
    with suppress(asyncio.CancelledError):
        await _dashboard_push_task
    _dashboard_push_task = None


# --- API Routes ---


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    """Engine status: mode, readiness, tick count."""
    result: dict[str, Any] = {"mode": _server_mode}
    if _server_mode == "live" and _live_state is not None:
        result.update(_live_state.get_status())
    elif _server_mode == "replay" and _replay_manager is not None:
        result["ready"] = _replay_manager.is_ready()
        result["time_range"] = _replay_manager.get_time_range()
    return result


@app.get("/api/positions")
def get_positions() -> dict[str, Any]:
    """Open positions with current P&L."""
    if _server_mode == "live" and _live_state is not None:
        return {"positions": _live_state.get_positions()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "positions" in snapshot:
            return {"positions": snapshot["positions"]}
    return {"positions": {}}


@app.get("/api/signals")
def get_signals() -> dict[str, Any]:
    """Active + expired signal states."""
    if _server_mode == "live" and _live_state is not None:
        return {"signals": _live_state.get_recent_signals()}
    if _replay_manager is not None:
        return {"signals": _replay_manager.get_signals()}
    return {"signals": []}


@app.get("/api/screened-groups")
def get_screened_groups() -> dict[str, Any]:
    """Current screening results — dual-mode transparent."""
    if _server_mode == "live" and _live_state is not None:
        return {"groups": _live_state.get_screening_hits()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "strong_groups" in snapshot:
            return {"groups": snapshot["strong_groups"]}
    return {"groups": []}


@app.get("/api/trades")
def get_trades() -> dict[str, Any]:
    """Completed trades."""
    if _server_mode == "live" and _live_state is not None:
        return {"trades": _live_state.get_completed_trades()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "completed_trades" in snapshot:
            return {"trades": snapshot["completed_trades"]}
    return {"trades": []}


class JumpRequest(BaseModel):
    time: str  # "HH:MM" format


@app.post("/api/replay/jump")
def replay_jump(req: JumpRequest) -> dict[str, Any]:
    """Time-travel to a specific minute (replay mode only)."""
    if _replay_manager is None:
        return {"error": "Not in replay mode or no data loaded"}
    snapshot = _replay_manager.jump_to_time(req.time)
    if snapshot is None:
        return {"error": f"No snapshot at or before {req.time}"}
    return {"snapshot": snapshot}


@app.get("/api/replay/status")
def replay_status() -> dict[str, Any]:
    """Replay readiness, time range."""
    if _replay_manager is None:
        return {"enabled": False, "ready": False}
    return {
        "enabled": True,
        "ready": _replay_manager.is_ready(),
        "time_range": _replay_manager.get_time_range(),
    }


@app.get("/api/config")
def get_config() -> dict[str, str]:
    """Current server configuration."""
    return {"mode": _server_mode}


# --- Dashboard API (V1) ---


@app.get("/api/dashboard/groups")
def dashboard_groups() -> dict[str, Any]:
    """Strong group cards with member tables."""
    if _server_mode == "live" and _live_state is not None:
        return {"groups": _live_state.get_dashboard_groups()}
    if _replay_manager is not None:
        snapshot = _replay_manager.get_current_snapshot()
        if snapshot and "dashboard_groups" in snapshot:
            return {"groups": snapshot["dashboard_groups"]}
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
        if snapshot and "dashboard_singles" in snapshot:
            return {"singles": snapshot["dashboard_singles"]}
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
        if snapshot and "dashboard_vwap" in snapshot:
            return {"vwap": snapshot["dashboard_vwap"]}
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
        if snapshot and "dashboard_signal_a" in snapshot:
            result: dict[str, Any] = snapshot["dashboard_signal_a"]
            return result
        if snapshot and "signal_a" in snapshot:
            result = snapshot["signal_a"]
            if isinstance(result, dict):
                return result
    return asdict(SignalAMonitorSnapshot())


@app.get("/api/dashboard/status")
def dashboard_status() -> dict[str, Any]:
    """Dashboard-specific status."""
    result: dict[str, Any] = {"mode": _server_mode}
    if _server_mode == "live" and _live_state is not None:
        status = _live_state.get_status()
        result.update(status)
        result["has_snapshot"] = _live_state.get_dashboard_snapshot_dict() is not None
    elif _server_mode == "replay" and _replay_manager is not None:
        result["ready"] = _replay_manager.is_ready()
        result["time_range"] = _replay_manager.get_time_range()
    return result


# --- Static file serving (dashboard SPA) ---
# Must be mounted LAST — it's a catch-all for the React SPA.

_dashboard_dist = Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "dist"
if _dashboard_dist.exists():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")
