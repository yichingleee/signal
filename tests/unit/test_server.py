"""Tests for server components."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tw_signal_engine.market_data.providers import LiveFeedStatus
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.server.live_state import LiveState
from tw_signal_engine.server.replay_manager import ReplayManager
from tw_signal_engine.state.symbol_state import IndexData


class TestReplayManager:
    def test_load_nonexistent(self):
        mgr = ReplayManager("99999999", snapshot_dir="/nonexistent/")
        assert mgr.load() is False
        assert mgr.is_ready() is False

    def test_load_and_query(self, tmp_path: Path):
        # Create a minimal Parquet file
        rows = [
            {
                "timestamp": 540,
                "time_str": "09:00",
                "market_time": "09:00:00",
                "strong_groups": json.dumps([{"group": "半導體", "gain": 0.02}]),
                "signals_a": "{}",
                "signals_b": "{}",
                "positions": "{}",
                "completed_trades": "[]",
                "market_disabled": False,
                "total_trades": 0,
            },
            {
                "timestamp": 570,
                "time_str": "09:30",
                "market_time": "09:30:00",
                "strong_groups": json.dumps([{"group": "半導體", "gain": 0.03}]),
                "signals_a": "{}",
                "signals_b": "{}",
                "positions": "{}",
                "completed_trades": "[]",
                "market_disabled": False,
                "total_trades": 1,
            },
        ]
        df = pd.DataFrame(rows)
        parquet_path = tmp_path / "ReplayData_20260129.parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

        mgr = ReplayManager("20260129", snapshot_dir=str(tmp_path))
        assert mgr.load() is True
        assert mgr.is_ready() is True

        time_range = mgr.get_time_range()
        assert time_range["min_time"] == "09:00"
        assert time_range["max_time"] == "09:30"
        assert time_range["count"] == 2

    def test_jump_to_time(self, tmp_path: Path):
        rows = [
            {"timestamp": 540, "time_str": "09:00", "market_time": "09:00:00",
             "strong_groups": "[]", "signals_a": "{}", "signals_b": "{}",
             "positions": "{}", "completed_trades": "[]",
             "market_disabled": False, "total_trades": 0},
            {"timestamp": 570, "time_str": "09:30", "market_time": "09:30:00",
             "strong_groups": "[]", "signals_a": "{}", "signals_b": "{}",
             "positions": "{}", "completed_trades": "[]",
             "market_disabled": False, "total_trades": 0},
            {"timestamp": 600, "time_str": "10:00", "market_time": "10:00:00",
             "strong_groups": "[]", "signals_a": "{}", "signals_b": "{}",
             "positions": "{}", "completed_trades": "[]",
             "market_disabled": False, "total_trades": 0},
        ]
        df = pd.DataFrame(rows)
        (tmp_path / "ReplayData_20260129.parquet").unlink(missing_ok=True)
        df.to_parquet(tmp_path / "ReplayData_20260129.parquet", engine="pyarrow")

        mgr = ReplayManager("20260129", snapshot_dir=str(tmp_path))
        mgr.load()

        # Jump to 09:30
        result = mgr.jump_to_time("09:30")
        assert result is not None
        assert result["time_str"] == "09:30"

        # Jump to 09:45 — should get 09:30 (latest at or before)
        result = mgr.jump_to_time("09:45")
        assert result is not None
        assert result["time_str"] == "09:30"

        # Jump to 08:00 — before any data
        result = mgr.jump_to_time("08:00")
        assert result is None

    def test_json_fields_parsed(self, tmp_path: Path):
        groups = [{"group": "半導體", "gain": 0.05}]
        rows = [
            {"timestamp": 540, "time_str": "09:00", "market_time": "09:00:00",
             "strong_groups": json.dumps(groups, ensure_ascii=False),
             "signals_a": "{}", "signals_b": "{}",
             "positions": "{}", "completed_trades": "[]",
             "market_disabled": False, "total_trades": 0},
        ]
        df = pd.DataFrame(rows)
        df.to_parquet(tmp_path / "ReplayData_20260129.parquet", engine="pyarrow")

        mgr = ReplayManager("20260129", snapshot_dir=str(tmp_path))
        mgr.load()

        snapshot = mgr.get_current_snapshot()
        assert snapshot is not None
        # JSON fields should be parsed back to Python objects
        assert isinstance(snapshot["strong_groups"], list)
        assert snapshot["strong_groups"][0]["group"] == "半導體"


class TestLiveState:
    def test_initial_status(self):
        state = LiveState()
        status = state.get_status()
        assert status["mode"] == "live"
        assert status["tick_count"] == 0
        assert status["feed_status"]["source"] == "redis"
        assert status["feed_status"]["connected"] is False

    def test_on_tick_updates_state(self):
        state = LiveState()
        hooks = state.build_hooks()

        tick = MarketTick()
        tick.symbol = "2330"
        tick.match_time_str = 93000000000
        tick.match = QuotePair(price=5000000, qty=100)
        idx = IndexData(vwap=500.0, day_high=5050000, day_low=4950000)

        assert hooks.on_tick is not None
        hooks.on_tick(tick, idx)

        status = state.get_status()
        assert status["tick_count"] == 1
        assert status["last_time_str"] == 93000000000

    def test_on_entry_and_exit(self):
        state = LiveState()
        hooks = state.build_hooks()

        entry = EntryTrade(
            symbol="2330",
            side="short",
            signal_type="SignalA",
            enter_cause="StrongGroup",
            entry_time_raw=93000000000,
            entry_price=500.0,
            entry_vwap=499.5,
            group_name="半導體",
        )

        assert hooks.on_entry is not None
        hooks.on_entry("2330", entry)

        positions = state.get_positions()
        assert "2330" in positions
        assert positions["2330"]["side"] == "short"
        assert positions["2330"]["signal_type"] == "SignalA"

        # Now exit
        record = TradeRecord()
        record.symbol = "2330"
        record.signal_type = "SignalA"
        record.pnl = 1000.0
        record.return_pct = 0.5
        record.entry_time_raw = 93000000000
        record.exit_time_raw = 100000000000

        assert hooks.on_exit is not None
        hooks.on_exit("2330", "takeProfit", record)

        positions = state.get_positions()
        assert "2330" not in positions

        trades = state.get_completed_trades()
        assert len(trades) == 1
        assert trades[0]["side"] == "long"
        assert trades[0]["pnl"] == 1000.0

    def test_on_signal(self):
        state = LiveState()
        hooks = state.build_hooks()

        # First set a time via on_tick
        tick = MarketTick()
        tick.symbol = "2330"
        tick.match_time_str = 93000000000
        tick.match = QuotePair(price=5000000, qty=100)
        assert hooks.on_tick is not None
        hooks.on_tick(tick, IndexData())

        assert hooks.on_signal is not None
        hooks.on_signal("2330", "SignalA", True)

        signals = state.get_recent_signals()
        assert len(signals) == 1
        assert signals[0]["symbol"] == "2330"
        assert signals[0]["signal_type"] == "SignalA"

    def test_bounded_lists(self):
        state = LiveState()
        hooks = state.build_hooks()

        # Set time first
        tick = MarketTick()
        tick.symbol = "2330"
        tick.match_time_str = 93000000000
        tick.match = QuotePair(price=5000000, qty=100)
        assert hooks.on_tick is not None
        hooks.on_tick(tick, IndexData())

        # Add 600 signals — should be bounded
        assert hooks.on_signal is not None
        for i in range(600):
            hooks.on_signal(f"SYM{i}", "SignalA", True)

        signals = state.get_recent_signals()
        assert len(signals) <= 200

    def test_update_feed_status(self):
        state = LiveState()

        state.update_feed_status(
            LiveFeedStatus(
                connected=True,
                subscribed_channels=2,
                last_message_at="2026-04-30T01:00:00+00:00",
                reconnect_count=1,
            )
        )

        status = state.get_status()
        assert status["engine_status"] == "starting"
        assert status["feed_status"]["connected"] is True
        assert status["feed_status"]["subscribed_channels"] == 2
        assert status["feed_status"]["reconnect_count"] == 1


class TestStatusApis:
    def test_live_status_includes_feed_status(self):
        from tw_signal_engine.server import app as server_app

        state = LiveState()
        state.update_feed_status({"source": "redis", "connected": True, "subscribed_channels": 3})
        server_app.configure(mode="live", live_state=state)

        status = server_app.get_status()
        dashboard_status = server_app.dashboard_status()

        assert status["mode"] == "live"
        assert status["feed_status"]["connected"] is True
        assert dashboard_status["feed_status"]["subscribed_channels"] == 3
        assert dashboard_status["has_snapshot"] is False

    def test_replay_status_does_not_claim_redis_connection(self, tmp_path: Path):
        from tw_signal_engine.server import app as server_app

        manager = ReplayManager("20260129", snapshot_dir=str(tmp_path))
        server_app.configure(mode="replay", replay_manager=manager)

        status = server_app.get_status()
        dashboard_status = server_app.dashboard_status()

        assert status["mode"] == "replay"
        assert status["ready"] is False
        assert "feed_status" not in status
        assert "feed_status" not in dashboard_status
