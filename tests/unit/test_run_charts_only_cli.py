"""Tests for charts-only CLI wiring."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from tw_signal_engine.cli.run_charts_only import main


def _write_report_trades(path: Path, trade_date: str, symbol: str) -> None:
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
                "TradeDate",
                "EntryHourBucket",
                "0050EntryChg%",
                "MAE%",
                "MFE%",
            ]
        )
        writer.writerow(
            [
                symbol,
                "long",
                "SignalA",
                "StrongGroup",
                "09:01:00",
                "09:05:00",
                "takeProfit",
                "100",
                "1.00%",
                trade_date,
                "09:00-09:15",
                "0.100",
                "-0.200",
                "1.000",
            ]
        )


def _write_funnel(path: Path) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Section", "Stage", "Count", "PassRate", "CumulativePassRate"])
        writer.writerow(["Pipeline", "Universe", "10", "100.0%", "100.0%"])
        writer.writerow(["Pipeline", "Valid Group Symbols", "3", "30.0%", "30.0%"])
        writer.writerow(["Pipeline", "Signal Triggered", "1", "33.3%", "10.0%"])
        writer.writerow(["Pipeline", "Entry Filter Blocked", "0", "0.0%", "0.0%"])
        writer.writerow(["Pipeline", "Executed Trades", "1", "100.0%", "10.0%"])


def test_run_charts_only_default_runs_daily_and_batch(tmp_path: Path, monkeypatch) -> None:
    day1 = tmp_path / "20260101"
    day2 = tmp_path / "20260102"
    day1.mkdir()
    day2.mkdir()
    _write_report_trades(day1 / "report_trades.csv", "20260101", "2330")
    _write_report_trades(day2 / "report_trades.csv", "20260102", "2317")
    _write_funnel(day1 / "report_funnel.csv")
    _write_funnel(day2 / "report_funnel.csv")

    daily_calls: list[tuple[str, int]] = []
    batch_calls: list[int] = []

    def _fake_daily(*, trades, funnel, log_dir, trade_date, data_dir, prev_day_limit_up=None) -> None:
        assert funnel is not None
        daily_calls.append((trade_date, len(trades)))

    def _fake_batch(all_trades, log_dir) -> None:
        batch_calls.append(len(all_trades))

    monkeypatch.setattr("tw_signal_engine.cli.run_charts_only.generate_daily_charts", _fake_daily)
    monkeypatch.setattr("tw_signal_engine.cli.run_charts_only.generate_batch_charts", _fake_batch)

    monkeypatch.setattr(sys, "argv", ["prog", "--log-dir", str(tmp_path)])
    main()

    # Default mode skips trade-day timeline path; trade_date is blank.
    assert daily_calls == [("", 1), ("", 1)]
    assert batch_calls == [2]


def test_run_charts_only_with_trade_day_and_date_filter(tmp_path: Path, monkeypatch) -> None:
    day1 = tmp_path / "20260101"
    day2 = tmp_path / "20260102"
    day1.mkdir()
    day2.mkdir()
    _write_report_trades(day1 / "report_trades.csv", "20260101", "2330")
    _write_report_trades(day2 / "report_trades.csv", "20260102", "2317")

    daily_calls: list[str] = []

    def _fake_daily(*, trades, funnel, log_dir, trade_date, data_dir, prev_day_limit_up=None) -> None:
        daily_calls.append(trade_date)

    monkeypatch.setattr("tw_signal_engine.cli.run_charts_only.generate_daily_charts", _fake_daily)
    monkeypatch.setattr("tw_signal_engine.cli.run_charts_only.generate_batch_charts", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--log-dir",
            str(tmp_path),
            "--date",
            "20260102",
            "--daily-only",
            "--with-trade-day",
        ],
    )
    main()

    assert daily_calls == ["20260102"]


def test_run_charts_only_rejects_conflicting_mode_flags(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "20260101").mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--log-dir", str(tmp_path), "--daily-only", "--batch-only"],
    )
    try:
        main()
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for conflicting flags")
