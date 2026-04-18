"""Tests for loading chart inputs from persisted report artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.reporting.load_report_artifacts import (
    list_available_replay_dates,
    load_batch_trade_records,
    load_funnel_tracker,
    load_trade_records,
    select_replay_dates,
)


def _write_report_trades(path: Path, trade_date: str) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Symbol",
                "Side",
                "SignalType",
                "EnterCause",
                "EntryTime",
                "ExitTime",
                "LeaveCause",
                "PnL",
                "Return%",
                "GroupName",
                "GroupRank",
                "MemberRank",
                "RawMemberRank",
                "EntryPrice",
                "0050EntryChg%",
                "MAE%",
                "MFE%",
                "GrossPnL",
                "Commission",
                "Tax",
                "Slippage",
                "NetPnL",
                "TradeDate",
                "EntryHourBucket",
            ]
        )
        writer.writerow(
            [
                "2330",
                "long",
                "SignalA",
                "StrongGroup",
                "09:01:00",
                "09:06:33",
                "takeProfit",
                "300000",
                "3.00%",
                "Semis",
                "2",
                "1",
                "1",
                "100.0",
                "0.123",
                "-0.500",
                "3.000",
                "300000",
                "0",
                "0",
                "0",
                "300000",
                trade_date,
                "09:00-09:15",
            ]
        )


def _write_order_log(path: Path) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Action",
                "Symbol",
                "Time",
                "Price",
                "Cash",
                "SymbolCash",
                "SignalType",
                "EnterCause",
                "LeaveCause",
                "Side",
                "RemainingQty",
                "GroupInfo",
            ]
        )
        writer.writerow(
            [
                "leave",
                "2330",
                "90633012345",
                "1035000",
                "0",
                "0",
                "-",
                "-",
                "takeProfit",
                "long",
                "0",
                "",
            ]
        )


def _write_funnel(path: Path) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Section", "Stage", "Count", "PassRate", "CumulativePassRate"])
        writer.writerow(["Pipeline", "Universe", "100", "100.0%", "100.0%"])
        writer.writerow(["Pipeline", "Valid Group Symbols", "10", "10.0%", "10.0%"])
        writer.writerow(["Pipeline", "Group Qualified Ticks", "20", "200.0%", "20.0%"])
        writer.writerow(["Pipeline", "Signal Triggered", "3", "15.0%", "3.0%"])
        writer.writerow(["Pipeline", "Entry Filter Blocked", "1", "33.3%", "1.0%"])
        writer.writerow(["Pipeline", "Executed Trades", "2", "200.0%", "2.0%"])
        writer.writerow([])
        writer.writerow(["Section", "Reason", "Count", "Percentage"])
        writer.writerow(["BlockReasons", "max_entry_price", "1", "100.0%"])


def test_list_and_select_replay_dates(tmp_path: Path) -> None:
    (tmp_path / "20260101").mkdir()
    (tmp_path / "20260103").mkdir()
    (tmp_path / "notes").mkdir()

    assert list_available_replay_dates(tmp_path) == ["20260101", "20260103"]
    assert select_replay_dates(tmp_path, trade_date="20260101") == ["20260101"]
    assert select_replay_dates(tmp_path, start="20260101", end="20260102") == ["20260101"]


def test_load_trade_records_uses_order_log_exit_price(tmp_path: Path) -> None:
    day = tmp_path / "20260101"
    day.mkdir()
    _write_report_trades(day / "report_trades.csv", "20260101")
    _write_order_log(day / "order_log_20260101.csv")

    trades = load_trade_records(day, "20260101")
    assert len(trades) == 1
    assert trades[0].symbol == "2330"
    assert trades[0].exit_price == 103.5
    assert trades[0].trade_date == "20260101"


def test_load_funnel_tracker(tmp_path: Path) -> None:
    day = tmp_path / "20260101"
    day.mkdir()
    _write_funnel(day / "report_funnel.csv")

    funnel = load_funnel_tracker(day)
    assert funnel is not None
    assert funnel.universe_count == 100
    assert funnel.executed_trades == 2
    assert funnel.entry_filter_reasons["max_entry_price"] == 1


def test_load_batch_trade_records(tmp_path: Path) -> None:
    day1 = tmp_path / "20260101"
    day2 = tmp_path / "20260102"
    day1.mkdir()
    day2.mkdir()
    _write_report_trades(day1 / "report_trades.csv", "20260101")
    _write_report_trades(day2 / "report_trades.csv", "20260102")

    trades = load_batch_trade_records(tmp_path, ["20260101", "20260102"])
    assert len(trades) == 2
    assert [t.trade_date for t in trades] == ["20260101", "20260102"]
