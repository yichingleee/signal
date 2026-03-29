"""Tests for run_server live-mode startup behavior."""

from __future__ import annotations

import argparse

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.reference_records import ReferenceSymbol


def _ref(symbol: str) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name=symbol,
        market="TSE",
        previous_close=100.0,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


def _make_args() -> argparse.Namespace:
    return argparse.Namespace(
        date="20260129",
        mode="live",
        config="exec/cfg/parameter.cfg",
        data_dir="exec/data",
        files_dir="exec/files",
        group_file="exec/files/group.csv",
        host="127.0.0.1",
        port=8000,
        snapshot_dir="./cache/replay/",
        redis_host=None,
        redis_port=None,
        no_cache=False,
    )


def test_start_live_mode_fail_fast_sets_fatal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.cli import run_server

    captured = {}

    def _fake_configure(mode: str, live_state=None, replay_manager=None) -> None:
        captured["mode"] = mode
        captured["live_state"] = live_state

    def _bad_run_daily_replay(
        trade_date: str,
        config_path: str = "./cfg/parameter.cfg",
        data_dir: str = "./data/",
        files_dir: str = "./files/",
        group_file: str = "./files/group.csv",
        history: HistoryWindow | None = None,
        use_cache: bool = True,
    ) -> list[object]:
        return []

    monkeypatch.setattr("tw_signal_engine.server.app.configure", _fake_configure)
    monkeypatch.setattr("tw_signal_engine.config.load_legacy_ini.load_legacy_ini", lambda _: {})
    monkeypatch.setattr(
        "tw_signal_engine.config.normalize_strategy_config.normalize_strategy_config",
        lambda _: NormalizedStrategyConfig(),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.load_symbol_reference.load_symbol_reference",
        lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.derive_prev_day_limit_up.derive_prev_day_limit_up",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.load_group_membership.load_group_membership",
        lambda *_: ([], {}, {}),
    )
    monkeypatch.setattr(
        "tw_signal_engine.market_data.load_history_window.load_history_window",
        lambda *args, **kwargs: HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
    )
    monkeypatch.setattr("tw_signal_engine.replay.replay_session.run_daily_replay", _bad_run_daily_replay)
    monkeypatch.setattr(run_server.signal, "signal", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="Live engine failed during startup"):
        run_server._start_live_mode(_make_args())

    live_state = captured["live_state"]
    status = live_state.get_status()
    assert captured["mode"] == "live"
    assert status["engine_status"] == "fatal"
    assert "unexpected keyword argument 'provider'" in status["fatal_error"]


def test_start_live_mode_accepts_restored_replay_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.cli import run_server

    captured = {}

    def _fake_configure(mode: str, live_state=None, replay_manager=None) -> None:
        captured["mode"] = mode
        captured["live_state"] = live_state

    def _ok_run_daily_replay(*args, **kwargs) -> list[object]:
        return []

    monkeypatch.setattr("tw_signal_engine.server.app.configure", _fake_configure)
    monkeypatch.setattr("tw_signal_engine.config.load_legacy_ini.load_legacy_ini", lambda _: {})
    monkeypatch.setattr(
        "tw_signal_engine.config.normalize_strategy_config.normalize_strategy_config",
        lambda _: NormalizedStrategyConfig(),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.load_symbol_reference.load_symbol_reference",
        lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.derive_prev_day_limit_up.derive_prev_day_limit_up",
        lambda *_: {},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reference_data.load_group_membership.load_group_membership",
        lambda *_: ([], {}, {}),
    )
    monkeypatch.setattr(
        "tw_signal_engine.market_data.load_history_window.load_history_window",
        lambda *args, **kwargs: HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
    )
    monkeypatch.setattr("tw_signal_engine.replay.replay_session.run_daily_replay", _ok_run_daily_replay)
    monkeypatch.setattr(run_server.signal, "signal", lambda *args, **kwargs: None)

    run_server._start_live_mode(_make_args())
    status = captured["live_state"].get_status()
    assert captured["mode"] == "live"
    assert status["engine_status"] in {"running", "stopped"}
