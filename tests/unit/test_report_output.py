"""Integration tests for per-day report output structure and values."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_daily_summary import write_summary_report
from tw_signal_engine.reporting.build_funnel_report import write_funnel_report
from tw_signal_engine.reporting.build_trade_path_report import write_trade_path_report
from tw_signal_engine.reporting.build_trade_report_rows import write_trade_report
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


def _make_trade(
    symbol: str = "2330",
    pnl: float = 100.0,
    return_pct: float = 1.0,
    mae_pct: float = -0.5,
    mfe_pct: float = 1.5,
    signal_type: str = "SignalA",
    leave_cause: str = "takeProfit",
    entry_time: int = 91500000000,
    exit_time: int = 100000000000,
    tp_slices: int = 3,
    group_name: str = "G1",
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        signal_type=signal_type,
        enter_cause="StrongGroup",
        final_leave_cause=leave_cause,
        entry_time_raw=entry_time,
        exit_time_raw=exit_time,
        pnl=pnl,
        return_pct=return_pct,
        mae_pct=mae_pct,
        mfe_pct=mfe_pct,
        mae_price=49.75,
        mfe_price=50.75,
        tp_slices_filled=tp_slices,
        tp_pnl=pnl * 0.7,
        residual_pnl=pnl * 0.3,
        gross_pnl=pnl,
        commission=0.0,
        tax=0.0,
        net_pnl=pnl,
        trade_date="20260101",
        exit_trade_date="20260101",
        is_overnight=False,
        entry_hour_bucket="09:15-09:30",
        entry_price=50.0,
        group_name=group_name,
    )


class TestFunnelReport:
    def test_output_structure(self, tmp_path: Path):
        funnel = FunnelTracker(
            universe_count=500,
            valid_group_symbols=200,
            signal_triggered=50,
            entry_filter_blocked=10,
            entry_filter_reasons={"entry_time_limit": 5, "prev_day_limit_up": 3, "no_entry_friday": 2},
            executed_trades=40,
        )
        write_funnel_report(funnel, str(tmp_path))

        path = tmp_path / "report_funnel.csv"
        assert path.exists()
        content = path.read_text()
        assert "Pipeline" in content
        assert "BlockReasons" in content
        assert "entry_time_limit" in content

    def test_empty_funnel(self, tmp_path: Path):
        funnel = FunnelTracker()
        write_funnel_report(funnel, str(tmp_path))
        assert (tmp_path / "report_funnel.csv").exists()


class TestTradePathReport:
    def test_output_structure(self, tmp_path: Path):
        trades = [_make_trade(), _make_trade(symbol="2317", pnl=-50)]
        write_trade_path_report(trades, str(tmp_path))

        path = tmp_path / "report_trade_paths.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        assert "MAE%" in rows[0]
        assert "MFE%" in rows[0]
        assert "TPSlices" in rows[0]
        assert len(rows) == 3  # header + 2 trades

    def test_empty_trades(self, tmp_path: Path):
        write_trade_path_report([], str(tmp_path))
        assert not (tmp_path / "report_trade_paths.csv").exists()


class TestEnhancedTradeReport:
    def test_new_columns_present(self, tmp_path: Path):
        trades = [_make_trade()]
        write_trade_report(trades, str(tmp_path))

        path = tmp_path / "report_trades.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        header = rows[0]
        assert "Side" in header
        assert "MAE%" in header
        assert "MFE%" in header
        assert "GrossPnL" in header
        assert "Commission" in header
        assert "Tax" in header
        assert "NetPnL" in header
        assert "TradeDate" in header
        assert "ExitTradeDate" in header
        assert "IsOvernight" in header
        assert "EntryHourBucket" in header

    def test_exit_trade_date_and_overnight_values_are_written(self, tmp_path: Path):
        trades = [_make_trade()]
        trades[0].is_overnight = True
        trades[0].exit_trade_date = "20260102"
        write_trade_report(trades, str(tmp_path))

        with open(tmp_path / "report_trades.csv") as f:
            rows = list(csv.reader(f))
        header = rows[0]
        data = rows[1]
        assert data[header.index("TradeDate")] == "20260101"
        assert data[header.index("ExitTradeDate")] == "20260102"
        assert data[header.index("IsOvernight")] == "1"


class TestEnhancedSummaryReport:
    def test_cost_rows_present(self, tmp_path: Path):
        trades = [_make_trade(pnl=100), _make_trade(pnl=-50)]
        write_summary_report(trades, str(tmp_path))

        path = tmp_path / "report_summary.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        metrics = {r[0]: r[1] for r in rows[1:]}
        assert "Total Gross PnL" in metrics
        assert "Total Commission" in metrics
        assert "Total Tax" in metrics
        assert "Total Net PnL" in metrics
        assert "Net Profit Factor" in metrics
        assert "Avg Net Return%" in metrics

    def test_zero_costs(self, tmp_path: Path):
        """When costs are 0, gross == net."""
        trades = [_make_trade(pnl=100)]
        write_summary_report(trades, str(tmp_path))

        with open(tmp_path / "report_summary.csv") as f:
            rows = list(csv.reader(f))
        metrics = {r[0]: r[1] for r in rows[1:]}
        assert metrics["Total Gross PnL"] == metrics["Total Net PnL"]
