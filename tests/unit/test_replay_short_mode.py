"""Replay integration tests for short-mode behavior."""

from __future__ import annotations

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.replay.replay_session import run_daily_replay


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


def _tick(symbol: str, time_str: int, price: int = 5_000_000) -> MarketTick:
    tick = MarketTick()
    tick.symbol = symbol
    tick.market = "TSE"
    tick.match_time_str = time_str
    tick.match_time_us = time_str // 1000
    tick.trade_code = 1
    tick.status_code = 0
    tick.match = QuotePair(price=price, qty=100)
    tick.bid[0].price = price
    tick.ask[0].price = price
    return tick


class _Provider:
    def iterate_ticks(self):
        yield _tick("2330", 93000000000)


class _LogWriter:
    def __init__(self, log_dir: str, date: str) -> None:
        self.log_dir = log_dir
        self.date = date

    def write_entry(self, *args, **kwargs) -> None:
        return None

    def write_leave(self, *args, **kwargs) -> None:
        return None

    def close(self) -> None:
        return None


def test_short_mode_does_not_call_strong_single_on_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    from tw_signal_engine.replay import replay_session as rs

    call_count = {"n": 0}

    def _spy_on_tick(self, *args, **kwargs):
        call_count["n"] += 1
        return True

    monkeypatch.setattr(rs.StrongSingleEvaluator, "on_tick", _spy_on_tick)
    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})

    cfg = NormalizedStrategyConfig()
    cfg.signal_a.enabled = True
    cfg.strong_single.enabled = True
    cfg.strategy.trade_mode = "short"

    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: cfg)
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"2330": _ref("2330"), "0050": _ref("0050")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {}, {}))
    monkeypatch.setattr(rs, "OrderLogWriter", _LogWriter)
    monkeypatch.setattr(rs, "_generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(rs, "build_replay_universe", lambda *args, **kwargs: {"2330", "0050"})

    trades = run_daily_replay(
        trade_date="20260129",
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=_Provider(),
        no_charts=True,
    )

    assert trades == []
    assert call_count["n"] == 0
