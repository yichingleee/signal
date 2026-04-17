"""Tests for replay-session lifecycle helpers."""

from __future__ import annotations

import inspect

import pytest

from tw_signal_engine.config.strategy_config import ExecutionConfig, NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair, TradeRecord
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.records.trade_records import EntryTrade
from tw_signal_engine.replay.replay_session import _finalize_open_positions, run_daily_replay
from tw_signal_engine.replay.session_hooks import SessionHooks
from tw_signal_engine.replay.session_time import fmt_time
from tw_signal_engine.server.dashboard_snapshot import DashboardSnapshot
from tw_signal_engine.state.position_state import PositionState
from tw_signal_engine.state.symbol_state import IndexData


class _LogWriterStub:
    def __init__(self) -> None:
        self.leave_rows: list[tuple[str, str]] = []

    def write_leave(
        self,
        symbol: str,
        match_time_str: int,
        price: int,
        cash: float,
        symbol_cash: float,
        cause: str,
        side: str,
        qty: float,
    ) -> None:
        self.leave_rows.append((symbol, cause))


def _make_pos(entry_time: int = 90000000000) -> PositionState:
    return PositionState(
        stocks={"2330": 10.0},
        symbol_cash={"2330": -100.0},
        orders={"2330": []},
        reserve_stocks={"2330": 0.0},
        profit_taken={"2330": False},
        open_trades={
            "2330": EntryTrade(
                symbol="2330",
                signal_type="SignalA",
                enter_cause="StrongGroup",
                entry_time_raw=entry_time,
                baseline=0.0,
            )
        },
    )


def test_finalize_open_positions_records_trade_and_clears_position() -> None:
    config = NormalizedStrategyConfig(execution=ExecutionConfig(position_cash=100.0))
    pos = _make_pos()
    completed_trades = []
    log_writer = _LogWriterStub()

    _finalize_open_positions(
        config,
        pos,
        {"2330": 110000},
        {"2330": "SignalA"},
        {"2330": IndexData()},
        completed_trades,
        log_writer,
        132500000000,
    )

    assert pos.stocks["2330"] == 0
    assert len(completed_trades) == 1
    assert completed_trades[0].final_leave_cause == "timeExit"
    assert completed_trades[0].pnl == 10.0
    assert completed_trades[0].exit_price == 11.0
    assert log_writer.leave_rows == [("2330", "timeExit")]


def test_finalize_exit_time_uses_last_match_time() -> None:
    """Regression: exit_time_raw must be a real timestamp, not sys.maxsize."""
    config = NormalizedStrategyConfig(execution=ExecutionConfig(position_cash=100.0))
    pos = _make_pos()
    completed_trades = []
    log_writer = _LogWriterStub()

    exit_time = 132500000000  # 13:25:00 — at exit_time_limit

    _finalize_open_positions(
        config,
        pos,
        {"2330": 110000},
        {"2330": "SignalA"},
        {"2330": IndexData()},
        completed_trades,
        log_writer,
        exit_time,
    )

    assert completed_trades[0].exit_time_raw == exit_time
    assert completed_trades[0].exit_price == 11.0
    assert fmt_time(exit_time) == "13:25:00"


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


def _make_tick(symbol: str, time_str: int, price: int = 5_000_000) -> MarketTick:
    tick = MarketTick()
    tick.symbol = symbol
    tick.market = "TSE"
    tick.match_time_str = time_str
    tick.match_time_us = time_str // 1000
    tick.trade_code = 1
    tick.status_code = 0
    tick.match = QuotePair(price=price, qty=100)
    tick.bid[0].price = price
    return tick


def test_run_daily_replay_contract_restores_live_params() -> None:
    params = inspect.signature(run_daily_replay).parameters
    assert "provider" in params
    assert "hooks" in params
    assert "on_dashboard_snapshot" in params


def test_run_daily_replay_uses_injected_provider_and_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _Provider:
        def __init__(self) -> None:
            self._ticks = [
                _make_tick("2330", 93000000000, 5_000_000),
                _make_tick("2330", 93100000000, 5_010_000),
            ]

        def iterate_ticks(self):
            yield from self._ticks

    class _LogWriter:
        def __init__(self, log_dir: str, date: str) -> None:
            self.log_dir = log_dir
            self.date = date

        def write_entry(
            self,
            symbol: str,
            time_str: int,
            price: int,
            cash: float,
            symbol_cash: float,
            signal_type: str,
            cause: str,
            side: str,
            remaining_qty: float,
            group_info: str,
        ) -> None:
            return None

        def write_leave(
            self,
            symbol: str,
            time_str: int,
            price: int,
            cash: float,
            symbol_cash: float,
            cause: str,
            side: str,
            remaining_qty: float,
        ) -> None:
            return None

        def close(self) -> None:
            return None

    class _FailFileProvider:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("FileReplayProvider should not be constructed when provider is injected")

    def _fake_execute_entry(*args, **kwargs) -> None:
        tick = args[2]
        pos = args[6]
        idx = args[3]
        pos.stocks[tick.symbol] = 1.0
        pos.symbol_cash[tick.symbol] = -100.0
        pos.open_trades[tick.symbol] = EntryTrade(
            symbol=tick.symbol,
            side="long",
            signal_type="SignalA",
            enter_cause="StrongGroup",
            entry_time_raw=tick.match_time_str,
            baseline=0.0,
            entry_price=tick.match.price / 10000,
            entry_vwap=idx.vwap / 10000,
            entry_qty=1.0,
        )

    def _fake_on_tick_exit(
        config,
        symbol,
        price,
        bid_price,
        ask_price,
        match_time_str,
        signal_type,
        entry_idx,
        pos,
        completed_trades,
        trade_date="",
    ):
        if abs(pos.stocks.get(symbol, 0)) <= 0.001:
            return None
        if match_time_str < 93100000000:
            return None
        pos.stocks[symbol] = 0.0
        pos.open_trades.pop(symbol, None)
        completed_trades.append(
            TradeRecord(
                symbol=symbol,
                signal_type=signal_type,
                final_leave_cause="stopLoss",
                entry_time_raw=93000000000,
                exit_time_raw=match_time_str,
                pnl=100.0,
                return_pct=0.5,
            )
        )
        return "stopLoss"

    signal_calls = iter([(True, "StrongGroup"), (False, "None")])

    monkeypatch.setattr(rs, "FileReplayProvider", _FailFileProvider)
    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    cfg = NormalizedStrategyConfig()
    cfg.signal_a.enabled = True
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {}, {}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(rs, "should_enter", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(rs, "execute_entry", _fake_execute_entry)
    monkeypatch.setattr(rs, "on_tick_exit", _fake_on_tick_exit)
    monkeypatch.setattr(rs, "evaluate_signal_a", lambda *args, **kwargs: next(signal_calls))

    events: list[str] = []
    snapshots: list[DashboardSnapshot] = []
    hooks = SessionHooks(
        on_tick=lambda tick, idx: events.append(f"tick:{tick.match_time_str}"),
        on_screening=lambda symbol, match_type, qualified: events.append(f"screen:{symbol}:{match_type}:{qualified}"),
        on_signal=lambda symbol, signal_type, triggered: events.append(
            f"signal:{symbol}:{signal_type}:{triggered}"
        ),
        on_entry=lambda symbol, trade: events.append(f"entry:{symbol}"),
        on_exit=lambda symbol, cause, record: events.append(f"exit:{symbol}:{cause}"),
        on_minute=lambda match_time_str: events.append(f"minute:{match_time_str}"),
    )

    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=_Provider(),
        hooks=hooks,
        on_dashboard_snapshot=snapshots.append,
        no_charts=True,
    )

    assert len(trades) == 1
    assert trades[0].final_leave_cause == "stopLoss"
    assert events == [
        "tick:93000000000",
        "screen:2330:None:False",
        "signal:2330:SignalA:True",
        "entry:2330",
        "minute:93000000000",
        "tick:93100000000",
        "exit:2330:stopLoss",
        "screen:2330:None:False",
        "signal:2330:SignalA:False",
        "minute:93100000000",
    ]
    assert [snap.time_raw for snap in snapshots] == [93000000000, 93100000000]
