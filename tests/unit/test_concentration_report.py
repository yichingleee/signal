"""Tests for concentration report generation."""

from __future__ import annotations

from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_concentration_report import (
    _percentile_contributions,
    _top_contributions,
    write_concentration_report,
)


def _make_trade(symbol: str, pnl: float, group: str = "G1", date: str = "20260101") -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        group_name=group,
        trade_date=date,
    )


class TestTopContributions:
    def test_sorted_by_abs_pnl(self):
        items = [("A", 10.0), ("B", -50.0), ("C", 30.0)]
        result = _top_contributions(items, 100.0)
        assert result[0][0] == "B"  # highest abs PnL

    def test_cumulative_percentage(self):
        items = [("A", 100.0)]
        result = _top_contributions(items, 100.0)
        assert abs(result[0][2] - 100.0) < 0.01


class TestPercentileContributions:
    def test_uniform_pnl(self):
        pnls = [10.0] * 100
        total = 1000.0
        result = _percentile_contributions(pnls, total)
        assert abs(result["Top 1%"] - 1.0) < 0.1
        assert abs(result["Top 10%"] - 10.0) < 0.1

    def test_skewed_pnl(self):
        pnls = [1000.0] + [1.0] * 99
        total = sum(pnls)
        result = _percentile_contributions(pnls, total)
        # Top 1% should contribute almost all PnL
        assert result["Top 1%"] > 90.0

    def test_zero_total_pnl(self):
        result = _percentile_contributions([0.0, 0.0], 0.0)
        assert result["Top 1%"] == 0.0


class TestConcentrationReport:
    def test_basic_output(self, tmp_path: Path):
        trades = [
            _make_trade("2330", 100, "G1", "20260101"),
            _make_trade("2317", -50, "G2", "20260101"),
            _make_trade("2330", 200, "G1", "20260102"),
        ]
        write_concentration_report(trades, str(tmp_path))

        path = tmp_path / "report_concentration.csv"
        assert path.exists()
        content = path.read_text()
        assert "TopSymbols" in content
        assert "TopDates" in content
        assert "TopGroups" in content
        assert "Percentiles" in content

    def test_empty_trades(self, tmp_path: Path):
        write_concentration_report([], str(tmp_path))
        assert not (tmp_path / "report_concentration.csv").exists()

    def test_negative_total_pnl(self, tmp_path: Path):
        trades = [_make_trade("2330", -100), _make_trade("2317", -200)]
        write_concentration_report(trades, str(tmp_path))
        assert (tmp_path / "report_concentration.csv").exists()
