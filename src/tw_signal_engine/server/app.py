"""FastAPI application for the signal engine web server."""

from __future__ import annotations

from typing import Any

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


def configure(
    mode: str,
    live_state: LiveState | None = None,
    replay_manager: ReplayManager | None = None,
) -> None:
    """Configure the app's data sources. Called before uvicorn.run()."""
    global _live_state, _replay_manager, _server_mode
    _server_mode = mode
    _live_state = live_state
    _replay_manager = replay_manager


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
