"""Tests for daily equity report generation."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_daily_equity_report import write_daily_equity_report


def _make_trade(pnl: float, date: str = "20260101", return_pct: float = 0.0) -> TradeRecord:
    return TradeRecord(
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=return_pct or pnl / 10000 * 100,
        trade_date=date,
        entry_time_raw=90000000000,
        exit_time_raw=100000000000,
    )


class TestDailyEquityReport:
    def test_basic_output(self, tmp_path: Path):
        trades = [
            _make_trade(100, "20260101"),
            _make_trade(-50, "20260101"),
            _make_trade(200, "20260102"),
        ]
        write_daily_equity_report(trades, str(tmp_path))

        path = tmp_path / "report_daily.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        assert rows[0][0] == "Date"
        # 2 dates
        assert len(rows) == 3  # header + 2 dates

    def test_cumulative_pnl(self, tmp_path: Path):
        trades = [
            _make_trade(100, "20260101"),
            _make_trade(200, "20260102"),
        ]
        write_daily_equity_report(trades, str(tmp_path))

        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        # Day 1 cum = 100, Day 2 cum = 300
        assert rows[1][4] == "100"
        assert rows[2][4] == "300"

    def test_drawdown(self, tmp_path: Path):
        trades = [
            _make_trade(200, "20260101"),
            _make_trade(-100, "20260102"),
        ]
        write_daily_equity_report(trades, str(tmp_path))

        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        # Day 1: cum=200, peak=200, dd=0
        assert rows[1][5] == "0"
        # Day 2: cum=100, peak=200, dd=100
        assert rows[2][5] == "100"

    def test_single_day(self, tmp_path: Path):
        trades = [_make_trade(100, "20260101")]
        write_daily_equity_report(trades, str(tmp_path))
        assert (tmp_path / "report_daily.csv").exists()

    def test_empty_trades(self, tmp_path: Path):
        write_daily_equity_report([], str(tmp_path))
        assert not (tmp_path / "report_daily.csv").exists()

    def test_concurrent_positions_computed(self, tmp_path: Path):
        """3 overlapping trades: t1=[90000-100000], t2=[95000-105000], t3=[110000-120000].
        Max concurrent = 2 (t1 and t2 overlap)."""
        trades = [
            TradeRecord(pnl=100, gross_pnl=100, net_pnl=100, return_pct=1.0,
                        trade_date="20260101",
                        entry_time_raw=90000000000, exit_time_raw=100000000000),
            TradeRecord(pnl=200, gross_pnl=200, net_pnl=200, return_pct=2.0,
                        trade_date="20260101",
                        entry_time_raw=95000000000, exit_time_raw=105000000000),
            TradeRecord(pnl=50, gross_pnl=50, net_pnl=50, return_pct=0.5,
                        trade_date="20260101",
                        entry_time_raw=110000000000, exit_time_raw=120000000000),
        ]
        write_daily_equity_report(trades, str(tmp_path))
        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        # Header has ConcurrentPositions at index 9
        assert rows[0][9] == "ConcurrentPositions"
        assert rows[1][9] == "2"

    def test_capital_utilized_computed(self, tmp_path: Path):
        """Capital = max_concurrent * position_cash. With return_pct=1.0 and pnl=100,
        position_cash = 100/1.0*100 = 10000. Max concurrent = 2 → capital = 20000."""
        trades = [
            TradeRecord(pnl=100, gross_pnl=100, net_pnl=100, return_pct=1.0,
                        trade_date="20260101",
                        entry_time_raw=90000000000, exit_time_raw=100000000000),
            TradeRecord(pnl=200, gross_pnl=200, net_pnl=200, return_pct=2.0,
                        trade_date="20260101",
                        entry_time_raw=95000000000, exit_time_raw=105000000000),
        ]
        write_daily_equity_report(trades, str(tmp_path))
        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        assert rows[0][10] == "CapitalUtilized"
        assert rows[1][10] == "20000"

    def test_no_overlap_concurrent_is_one(self, tmp_path: Path):
        """Non-overlapping trades should have max concurrent = 1."""
        trades = [
            TradeRecord(pnl=100, gross_pnl=100, net_pnl=100, return_pct=1.0,
                        trade_date="20260101",
                        entry_time_raw=90000000000, exit_time_raw=95000000000),
            TradeRecord(pnl=50, gross_pnl=50, net_pnl=50, return_pct=0.5,
                        trade_date="20260101",
                        entry_time_raw=100000000000, exit_time_raw=105000000000),
        ]
        write_daily_equity_report(trades, str(tmp_path))
        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        assert rows[1][9] == "1"
