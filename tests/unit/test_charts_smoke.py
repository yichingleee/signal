"""Smoke tests for chart generation — verify no crash and output exists."""

from __future__ import annotations

from pathlib import Path

import pytest

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.charts.trade_day_models import IntradayPoint, SymbolTradeDay, TradeMarker
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker

try:
    import matplotlib  # noqa: F401
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

pytestmark = pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")


def _make_trade(
    pnl: float,
    mae_pct: float = -0.5,
    mfe_pct: float = 1.5,
    leave_cause: str = "takeProfit",
    entry_time: int = 91500000000,
    exit_time: int = 100000000000,
    date: str = "20260101",
    market_chg: float = 0.5,
    hour_bucket: str = "09:15-09:30",
) -> TradeRecord:
    return TradeRecord(
        symbol="2330",
        signal_type="SignalA",
        enter_cause="StrongGroup",
        final_leave_cause=leave_cause,
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=pnl / 10000 * 100,
        mae_pct=mae_pct,
        mfe_pct=mfe_pct,
        entry_time_raw=entry_time,
        exit_time_raw=exit_time,
        trade_date=date,
        market_entry_chg_pct=market_chg,
        entry_hour_bucket=hour_bucket,
    )


def _sample_trades() -> list[TradeRecord]:
    return [
        _make_trade(100, leave_cause="takeProfit"),
        _make_trade(-50, mae_pct=-2.0, mfe_pct=0.3, leave_cause="stopLoss"),
        _make_trade(200, mae_pct=-0.1, mfe_pct=3.0, leave_cause="takeProfit"),
        _make_trade(-30, mae_pct=-1.5, mfe_pct=0.5, leave_cause="bailout"),
        _make_trade(150, mae_pct=-0.3, mfe_pct=2.0, leave_cause="timeExit"),
    ]


class TestEquityCurveChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.equity_curve import plot_equity_curve
        plot_equity_curve(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_equity_curve.png").exists()
        assert (tmp_path / "chart_equity_curve.png").stat().st_size > 1024

    def test_single_trade(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.equity_curve import plot_equity_curve
        plot_equity_curve([_make_trade(100)], str(tmp_path))
        # Less than 2 trades -> no chart
        assert not (tmp_path / "chart_equity_curve.png").exists()


class TestPnLDistributionChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.pnl_distribution import plot_pnl_distribution
        plot_pnl_distribution(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_pnl_distribution.png").exists()
        assert (tmp_path / "chart_pnl_distribution.png").stat().st_size > 1024

    def test_all_wins(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.pnl_distribution import plot_pnl_distribution
        trades = [_make_trade(100 + i * 10) for i in range(5)]
        plot_pnl_distribution(trades, str(tmp_path))
        assert (tmp_path / "chart_pnl_distribution.png").exists()

    def test_all_losses(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.pnl_distribution import plot_pnl_distribution
        trades = [_make_trade(-100 - i * 10) for i in range(5)]
        plot_pnl_distribution(trades, str(tmp_path))
        assert (tmp_path / "chart_pnl_distribution.png").exists()


class TestMAEMFEChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.mae_mfe_scatter import plot_mae_mfe_scatter
        plot_mae_mfe_scatter(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_mae_mfe.png").exists()
        assert (tmp_path / "chart_mae_mfe.png").stat().st_size > 1024


class TestConcentrationChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.concentration import plot_concentration
        plot_concentration(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_concentration.png").exists()
        assert (tmp_path / "chart_concentration.png").stat().st_size > 1024


class TestCategoryBarsChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.category_bars import plot_category_bars
        plot_category_bars(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_category_pnl.png").exists()
        assert (tmp_path / "chart_category_pnl.png").stat().st_size > 1024


class TestFunnelChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.funnel import plot_funnel
        funnel = FunnelTracker(
            universe_count=500,
            valid_group_symbols=200,
            signal_triggered=50,
            entry_filter_blocked=10,
            executed_trades=40,
        )
        plot_funnel(funnel, str(tmp_path))
        assert (tmp_path / "chart_funnel.png").exists()
        assert (tmp_path / "chart_funnel.png").stat().st_size > 1024


class TestRegimeHeatmapChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.regime_heatmap import plot_regime_heatmap
        plot_regime_heatmap(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_regime_heatmap.png").exists()
        assert (tmp_path / "chart_regime_heatmap.png").stat().st_size > 1024


class TestTradeScatterChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.trade_scatter import plot_trade_scatter
        plot_trade_scatter(_sample_trades(), str(tmp_path))
        assert (tmp_path / "chart_trade_scatter.png").exists()
        assert (tmp_path / "chart_trade_scatter.png").stat().st_size > 1024


class TestRollingMetricsChart:
    def test_no_crash_and_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.rolling_metrics import plot_rolling_metrics
        trades = [
            _make_trade(100, date="20260101"),
            _make_trade(-50, date="20260102"),
            _make_trade(200, date="20260103"),
        ]
        plot_rolling_metrics(trades, str(tmp_path))
        assert (tmp_path / "chart_rolling_metrics.png").exists()
        assert (tmp_path / "chart_rolling_metrics.png").stat().st_size > 1024


class TestTradeDayTimelineChart:
    def test_single_trade_symbol_chart_renders(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.trade_day_timeline import plot_trade_day_timeline

        symbol_day = SymbolTradeDay(
            symbol="2330",
            points=[
                IntradayPoint(time_raw=91500000000, price=50.0, vwap=50.0),
                IntradayPoint(time_raw=92000000000, price=50.5, vwap=50.3),
                IntradayPoint(time_raw=93000000000, price=51.0, vwap=50.6),
            ],
            markers=[
                TradeMarker(kind="signal", time_raw=91500000000, price=50.0, label="Signal SignalA (StrongGroup)"),
                TradeMarker(kind="entry", time_raw=91500000000, price=50.0, label="Entry 50.00 (StrongGroup)"),
                TradeMarker(kind="exit", time_raw=93000000000, price=51.0, label="Exit 51.00 (takeProfit)"),
            ],
        )

        plot_trade_day_timeline(symbol_day, str(tmp_path))
        out = tmp_path / "chart_trade_day_2330.png"
        assert out.exists()
        assert out.stat().st_size > 1024

    def test_multiple_markers_same_timestamp_no_crash(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.trade_day_timeline import plot_trade_day_timeline

        symbol_day = SymbolTradeDay(
            symbol="2317",
            points=[
                IntradayPoint(time_raw=91500000000, price=100.0, vwap=100.0),
                IntradayPoint(time_raw=91600000000, price=100.2, vwap=100.1),
            ],
            markers=[
                TradeMarker(kind="signal", time_raw=91500000000, price=100.0, label="Signal SignalA"),
                TradeMarker(kind="entry", time_raw=91500000000, price=100.0, label="Entry 100.00"),
                TradeMarker(kind="exit", time_raw=91500000000, price=99.8, label="Exit 99.80"),
                TradeMarker(kind="signal", time_raw=91500000000, price=100.1, label="Signal SignalB"),
            ],
        )

        plot_trade_day_timeline(symbol_day, str(tmp_path))
        assert (tmp_path / "chart_trade_day_2317.png").exists()

    def test_empty_points_skips_output(self, tmp_path: Path):
        from tw_signal_engine.reporting.charts.trade_day_timeline import plot_trade_day_timeline

        symbol_day = SymbolTradeDay(
            symbol="2454",
            points=[],
            markers=[TradeMarker(kind="entry", time_raw=91500000000, price=10.0, label="Entry 10.00")],
        )
        plot_trade_day_timeline(symbol_day, str(tmp_path))
        assert not (tmp_path / "chart_trade_day_2454.png").exists()
