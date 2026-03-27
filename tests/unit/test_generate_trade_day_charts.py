"""Integration tests for per-symbol trade-day chart pipeline wiring."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.replay.replay_session import _generate_reports
from tw_signal_engine.reporting.charts.trade_day_models import (
    IntradayPoint,
    SymbolTradeDay,
    TradeMarker,
)
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker
from tw_signal_engine.reporting.generate_charts import generate_daily_charts


def _trade(
    symbol: str,
    entry_time: int = 91500000000,
    exit_time: int = 93000000000,
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        signal_type="SignalA",
        enter_cause="StrongGroup",
        final_leave_cause="takeProfit",
        entry_time_raw=entry_time,
        exit_time_raw=exit_time,
        entry_price=50.0,
        exit_price=51.0,
        pnl=100.0,
        return_pct=1.0,
    )


def _fake_symbol_day(symbol: str) -> SymbolTradeDay:
    return SymbolTradeDay(
        symbol=symbol,
        points=[IntradayPoint(time_raw=91500000000, price=50.0, vwap=50.0)],
        markers=[
            TradeMarker(kind="signal", time_raw=91500000000, price=50.0, label="Signal SignalA"),
            TradeMarker(kind="entry", time_raw=91500000000, price=50.0, label="Entry 50.00"),
            TradeMarker(kind="exit", time_raw=93000000000, price=51.0, label="Exit 51.00"),
        ],
    )


def test_one_trade_produces_one_trade_day_chart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_day_traces",
        lambda *args, **kwargs: {"2330": _fake_symbol_day("2330").points},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_markers",
        lambda trades: {"2330": _fake_symbol_day("2330").markers},
    )

    def _fake_plot(symbol_day: SymbolTradeDay, log_dir: str) -> None:
        path = Path(log_dir) / f"chart_trade_day_{symbol_day.symbol}.png"
        path.write_bytes(b"fake-png")

    monkeypatch.setattr("tw_signal_engine.reporting.charts.trade_day_timeline.plot_trade_day_timeline", _fake_plot)

    generate_daily_charts(
        [_trade("2330")],
        funnel=None,
        log_dir=str(tmp_path),
        trade_date="20260102",
        data_dir="./data/",
        prev_day_limit_up={},
    )

    assert (tmp_path / "chart_trade_day_2330.png").exists()


def test_two_symbols_produce_two_trade_day_charts(tmp_path: Path, monkeypatch) -> None:
    symbol_days = {
        "2330": _fake_symbol_day("2330"),
        "2317": _fake_symbol_day("2317"),
    }
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_day_traces",
        lambda *args, **kwargs: {symbol: day.points for symbol, day in symbol_days.items()},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_markers",
        lambda trades: {symbol: day.markers for symbol, day in symbol_days.items()},
    )

    calls: list[str] = []

    def _fake_plot(symbol_day: SymbolTradeDay, log_dir: str) -> None:
        calls.append(symbol_day.symbol)
        (Path(log_dir) / f"chart_trade_day_{symbol_day.symbol}.png").write_bytes(b"fake-png")

    monkeypatch.setattr("tw_signal_engine.reporting.charts.trade_day_timeline.plot_trade_day_timeline", _fake_plot)

    generate_daily_charts(
        [_trade("2330"), _trade("2317")],
        funnel=None,
        log_dir=str(tmp_path),
        trade_date="20260102",
        data_dir="./data/",
        prev_day_limit_up={},
    )

    assert set(calls) == {"2330", "2317"}
    assert (tmp_path / "chart_trade_day_2330.png").exists()
    assert (tmp_path / "chart_trade_day_2317.png").exists()


def test_no_charts_true_skips_daily_chart_generation(tmp_path: Path, monkeypatch) -> None:
    called = False

    def _fake_generate(*args, **kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("tw_signal_engine.reporting.generate_charts.generate_daily_charts", _fake_generate)

    _generate_reports(
        completed_trades=[_trade("2330")],
        log_dir=str(tmp_path),
        market_open_chg_pct=0.0,
        funnel=None,
        trade_date="20260102",
        no_charts=True,
        data_dir="./data/",
        prev_day_limit_up={},
    )

    assert called is False
    assert not (tmp_path / "chart_trade_day_2330.png").exists()


def test_aggregate_charts_still_run_under_prior_conditions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_day_traces",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.build_trade_day_traces.build_trade_markers",
        lambda trades: {},
    )

    called: list[str] = []
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.equity_curve.plot_equity_curve",
        lambda trades, log_dir: called.append("equity_curve"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.pnl_distribution.plot_pnl_distribution",
        lambda trades, log_dir: called.append("pnl_distribution"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.mae_mfe_scatter.plot_mae_mfe_scatter",
        lambda trades, log_dir: called.append("mae_mfe"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.concentration.plot_concentration",
        lambda trades, log_dir: called.append("concentration"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.category_bars.plot_category_bars",
        lambda trades, log_dir: called.append("category_bars"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.trade_scatter.plot_trade_scatter",
        lambda trades, log_dir: called.append("trade_scatter"),
    )
    monkeypatch.setattr(
        "tw_signal_engine.reporting.charts.funnel.plot_funnel",
        lambda funnel, log_dir: called.append("funnel"),
    )

    generate_daily_charts(
        [_trade("2330"), _trade("2317")],
        funnel=FunnelTracker(universe_count=1),
        log_dir=str(tmp_path),
        trade_date="20260102",
        data_dir="./data/",
        prev_day_limit_up={},
    )

    assert set(called) == {
        "equity_curve",
        "pnl_distribution",
        "mae_mfe",
        "concentration",
        "category_bars",
        "trade_scatter",
        "funnel",
    }
