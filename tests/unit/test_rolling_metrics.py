"""Tests for rolling metrics report generation."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_rolling_metrics import write_rolling_metrics_report


def _make_trade(pnl: float, date: str = "20260101") -> TradeRecord:
    return TradeRecord(
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=pnl / 10000 * 100,
        trade_date=date,
        entry_time_raw=90000000000,
        exit_time_raw=100000000000,
    )


class TestRollingMetrics:
    def test_basic_output(self, tmp_path: Path):
        trades = [
            _make_trade(100, "20260101"),
            _make_trade(-50, "20260102"),
            _make_trade(200, "20260103"),
        ]
        write_rolling_metrics_report(trades, str(tmp_path))

        path = tmp_path / "report_rolling.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        assert rows[0][0] == "EndDate"
        # 3 dates -> 3 data rows
        assert len(rows) == 4

    def test_window_less_than_20_days(self, tmp_path: Path):
        """With fewer than 20 dates, window should cover all available dates."""
        trades = [_make_trade(100, f"2026010{i}") for i in range(1, 6)]
        write_rolling_metrics_report(trades, str(tmp_path), window=20)

        with open(tmp_path / "report_rolling.csv") as f:
            rows = list(csv.reader(f))
        # Window column should show growing window size
        assert rows[1][1] == "1"  # First row has 1-day window
        assert rows[-1][1] == "5"  # Last row has 5-day window

    def test_rolling_win_rate(self, tmp_path: Path):
        """All-win should show 100% win rate."""
        trades = [_make_trade(100, f"2026010{i}") for i in range(1, 4)]
        write_rolling_metrics_report(trades, str(tmp_path))

        with open(tmp_path / "report_rolling.csv") as f:
            rows = list(csv.reader(f))
        for row in rows[1:]:
            assert row[2] == "100.0%"

    def test_empty_trades(self, tmp_path: Path):
        write_rolling_metrics_report([], str(tmp_path))
        assert not (tmp_path / "report_rolling.csv").exists()

    def test_single_date(self, tmp_path: Path):
        trades = [_make_trade(100, "20260101")]
        write_rolling_metrics_report(trades, str(tmp_path))
        assert (tmp_path / "report_rolling.csv").exists()
