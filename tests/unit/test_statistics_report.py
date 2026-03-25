"""Tests for statistics report generation."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_statistics_report import (
    _kurtosis,
    _skewness,
    write_statistics_report,
)


def _make_trade(pnl: float, return_pct: float = 0.0) -> TradeRecord:
    return TradeRecord(
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=return_pct if return_pct != 0 else pnl / 10000 * 100,
    )


class TestStatisticsMetrics:
    def test_skewness_symmetric(self):
        """Symmetric distribution should have ~0 skewness."""
        vals = [-2.0, -1.0, 0.0, 1.0, 2.0]
        mean = 0.0
        std = (sum(v ** 2 for v in vals) / len(vals)) ** 0.5
        assert abs(_skewness(vals, mean, std)) < 0.01

    def test_skewness_positive(self):
        """Right-skewed distribution should have positive skewness."""
        vals = [1.0, 1.0, 1.0, 1.0, 10.0]
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        assert _skewness(vals, mean, std) > 0

    def test_kurtosis_normal_like(self):
        """Near-normal distribution should have ~0 excess kurtosis."""
        vals = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        kurt = _kurtosis(vals, mean, std)
        assert abs(kurt) < 3  # excess kurtosis should be moderate

    def test_skewness_insufficient_data(self):
        """Fewer than 3 values should return 0."""
        assert _skewness([1.0, 2.0], 1.5, 0.5) == 0.0

    def test_kurtosis_insufficient_data(self):
        """Fewer than 4 values should return 0."""
        assert _kurtosis([1.0, 2.0, 3.0], 2.0, 1.0) == 0.0

    def test_zero_std(self):
        """Zero std should return 0 for skewness and kurtosis."""
        assert _skewness([5.0, 5.0, 5.0], 5.0, 0.0) == 0.0
        assert _kurtosis([5.0, 5.0, 5.0, 5.0], 5.0, 0.0) == 0.0


class TestStatisticsReport:
    def test_basic_output(self, tmp_path: Path):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(200)]
        write_statistics_report(trades, str(tmp_path))

        path = tmp_path / "report_statistics.csv"
        assert path.exists()
        with open(path) as f:
            reader = csv.reader(f)
            rows = list(reader)
        # Check header
        assert rows[0] == ["Metric", "Value"]
        # Check N Trades
        assert rows[1][1] == "3"

    def test_all_wins(self, tmp_path: Path):
        trades = [_make_trade(100), _make_trade(200), _make_trade(50)]
        write_statistics_report(trades, str(tmp_path))

        path = tmp_path / "report_statistics.csv"
        with open(path) as f:
            reader = csv.reader(f)
            rows = list(reader)
        metrics = {r[0]: r[1] for r in rows[1:]}
        assert "Mean PnL" in metrics
        assert int(float(metrics["Mean PnL"].replace(",", ""))) > 0

    def test_all_losses(self, tmp_path: Path):
        trades = [_make_trade(-100), _make_trade(-200), _make_trade(-50)]
        write_statistics_report(trades, str(tmp_path))

        path = tmp_path / "report_statistics.csv"
        with open(path) as f:
            reader = csv.reader(f)
            rows = list(reader)
        metrics = {r[0]: r[1] for r in rows[1:]}
        assert float(metrics["Profit Factor"]) == 0.0

    def test_single_trade(self, tmp_path: Path):
        trades = [_make_trade(100)]
        write_statistics_report(trades, str(tmp_path))

        path = tmp_path / "report_statistics.csv"
        assert path.exists()

    def test_empty_trades(self, tmp_path: Path):
        write_statistics_report([], str(tmp_path))
        path = tmp_path / "report_statistics.csv"
        assert not path.exists()
