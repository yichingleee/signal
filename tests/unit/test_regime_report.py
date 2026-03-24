"""Tests for regime report generation."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_regime_report import (
    _group_rank_bucket,
    _market_state_bucket,
    write_regime_report,
)


def _make_trade(
    pnl: float,
    market_chg: float = 0.5,
    hour_bucket: str = "09:15-09:30",
    group_rank: int = 3,
    return_pct: float = 0.0,
) -> TradeRecord:
    return TradeRecord(
        pnl=pnl,
        gross_pnl=pnl,
        net_pnl=pnl,
        return_pct=return_pct or pnl / 10000 * 100,
        market_entry_chg_pct=market_chg,
        entry_hour_bucket=hour_bucket,
        group_rank=group_rank,
    )


class TestBucketAssignment:
    def test_market_state_very_negative(self):
        assert _market_state_bucket(-2.0) == "<-1%"

    def test_market_state_slightly_negative(self):
        assert _market_state_bucket(-0.5) == "-1% to 0%"

    def test_market_state_slightly_positive(self):
        assert _market_state_bucket(0.5) == "0% to 1%"

    def test_market_state_very_positive(self):
        assert _market_state_bucket(1.5) == ">1%"

    def test_market_state_boundary_minus_1(self):
        assert _market_state_bucket(-1.0) == "-1% to 0%"

    def test_market_state_boundary_0(self):
        assert _market_state_bucket(0.0) == "0% to 1%"

    def test_market_state_boundary_1(self):
        assert _market_state_bucket(1.0) == ">1%"

    def test_group_rank_top(self):
        assert _group_rank_bucket(1) == "1-5"
        assert _group_rank_bucket(5) == "1-5"

    def test_group_rank_mid(self):
        assert _group_rank_bucket(6) == "6-10"
        assert _group_rank_bucket(10) == "6-10"

    def test_group_rank_low(self):
        assert _group_rank_bucket(11) == "11-20"

    def test_group_rank_none(self):
        assert _group_rank_bucket(0) == "none"


class TestRegimeReport:
    def test_basic_output(self, tmp_path: Path):
        trades = [
            _make_trade(100, market_chg=0.5, hour_bucket="09:15-09:30", group_rank=3),
            _make_trade(-50, market_chg=-0.5, hour_bucket="09:00-09:15", group_rank=8),
            _make_trade(200, market_chg=1.5, hour_bucket="10:00+", group_rank=12),
        ]
        write_regime_report(trades, str(tmp_path))

        path = tmp_path / "report_regime.csv"
        assert path.exists()
        with open(path) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should have header + 4 market + 4 hour + 4 rank = 13 rows
        assert len(rows) == 13
        dimensions = {r[0] for r in rows[1:]}
        assert "MarketState" in dimensions
        assert "EntryHour" in dimensions
        assert "GroupRank" in dimensions

    def test_empty_buckets(self, tmp_path: Path):
        # All trades in one bucket
        trades = [_make_trade(100, market_chg=0.5, hour_bucket="09:15-09:30", group_rank=3)]
        write_regime_report(trades, str(tmp_path))

        path = tmp_path / "report_regime.csv"
        assert path.exists()
        with open(path) as f:
            rows = list(csv.reader(f))
        # Empty buckets should have count=0
        empty_rows = [r for r in rows[1:] if r[2] == "0"]
        assert len(empty_rows) > 0

    def test_empty_trades(self, tmp_path: Path):
        write_regime_report([], str(tmp_path))
        assert not (tmp_path / "report_regime.csv").exists()
