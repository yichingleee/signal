"""Integration tests for batch-level reports."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.generate_batch_reports import generate_batch_reports


def _make_trade(
    pnl: float,
    date: str = "20260101",
    return_pct: float = 0.0,
    market_chg: float = 0.5,
    hour_bucket: str = "09:15-09:30",
    group_rank: int = 3,
) -> TradeRecord:
    return TradeRecord(
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=return_pct or pnl / 10000 * 100,
        trade_date=date,
        entry_time_raw=90000000000,
        exit_time_raw=100000000000,
        market_entry_chg_pct=market_chg,
        entry_hour_bucket=hour_bucket,
        group_rank=group_rank,
    )


class TestBatchReports:
    def test_all_batch_reports_generated(self, tmp_path: Path):
        trades = [
            _make_trade(100, "20260101"),
            _make_trade(-50, "20260101"),
            _make_trade(200, "20260102"),
            _make_trade(-30, "20260103"),
        ]
        generate_batch_reports(trades, str(tmp_path))

        assert (tmp_path / "report_daily.csv").exists()
        assert (tmp_path / "report_rolling.csv").exists()
        assert (tmp_path / "report_regime.csv").exists()
        assert (tmp_path / "report_statistics.csv").exists()
        assert (tmp_path / "report_concentration.csv").exists()

    def test_cumulative_pnl_consistency(self, tmp_path: Path):
        """Cumulative PnL in daily report should match total from statistics."""
        trades = [
            _make_trade(100, "20260101"),
            _make_trade(200, "20260102"),
            _make_trade(-50, "20260103"),
        ]
        generate_batch_reports(trades, str(tmp_path))

        # Check daily report final cumulative
        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        last_cum = float(rows[-1][4])

        # Check statistics total
        with open(tmp_path / "report_statistics.csv") as f:
            stats = {r[0]: r[1] for r in csv.reader(f)}
        assert int(float(stats.get("Mean PnL", "0").replace(",", ""))) > 0

        # The final cum should be total PnL
        expected = sum(t.pnl for t in trades)
        assert abs(last_cum - expected) < 0.01

    def test_drawdown_in_daily(self, tmp_path: Path):
        trades = [
            _make_trade(200, "20260101"),
            _make_trade(-300, "20260102"),
        ]
        generate_batch_reports(trades, str(tmp_path))

        with open(tmp_path / "report_daily.csv") as f:
            rows = list(csv.reader(f))
        # Day 2 should have drawdown = 200 - (-100) = 300
        assert float(rows[2][5]) > 0  # Drawdown > 0

    def test_regime_bucket_boundaries(self, tmp_path: Path):
        trades = [
            _make_trade(100, market_chg=-2.0),  # <-1%
            _make_trade(100, market_chg=-0.5),  # -1% to 0%
            _make_trade(100, market_chg=0.5),   # 0% to 1%
            _make_trade(100, market_chg=1.5),   # >1%
        ]
        generate_batch_reports(trades, str(tmp_path))

        with open(tmp_path / "report_regime.csv") as f:
            rows = list(csv.reader(f))
        market_rows = [r for r in rows[1:] if r[0] == "MarketState"]
        # All 4 buckets should have count=1
        for row in market_rows:
            assert row[2] == "1"


class TestBatchCLIPropagation:
    """Verify that batch CLI flags propagate to per-day replays."""

    @patch("tw_signal_engine.cli.run_batch_replay._get_trading_dates", return_value=["20260101"])
    @patch("tw_signal_engine.replay.replay_session.run_daily_replay", return_value=[])
    @patch("tw_signal_engine.replay.replay_session._merge_history_windows")
    @patch("tw_signal_engine.market_data.rolling_history.RollingHistoryProvider")
    def test_cost_model_override_propagated(self, mock_provider_cls, mock_merge, mock_replay, mock_dates):
        import sys

        from tw_signal_engine.cli.run_batch_replay import main
        mock_provider_cls.return_value.get_history.return_value = None
        mock_merge.return_value = None

        with patch.object(sys, "argv", [
            "prog", "--start", "20260101", "--end", "20260101",
            "--cost-model", "commission=0.001425,tax=0.0015",
        ]):
            main()

        mock_replay.assert_called_once()
        call_kwargs = mock_replay.call_args[1]
        assert call_kwargs["cost_model_override"] == "commission=0.001425,tax=0.0015"

    @patch("tw_signal_engine.cli.run_batch_replay._get_trading_dates", return_value=["20260101"])
    @patch("tw_signal_engine.replay.replay_session.run_daily_replay", return_value=[])
    @patch("tw_signal_engine.replay.replay_session._merge_history_windows")
    @patch("tw_signal_engine.market_data.rolling_history.RollingHistoryProvider")
    def test_no_charts_propagated(self, mock_provider_cls, mock_merge, mock_replay, mock_dates):
        import sys

        from tw_signal_engine.cli.run_batch_replay import main
        mock_provider_cls.return_value.get_history.return_value = None
        mock_merge.return_value = None

        with patch.object(sys, "argv", [
            "prog", "--start", "20260101", "--end", "20260101",
            "--no-charts",
        ]):
            main()

        mock_replay.assert_called_once()
        call_kwargs = mock_replay.call_args[1]
        assert call_kwargs["no_charts"] is True
