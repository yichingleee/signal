"""Tests for history-window loading."""

from __future__ import annotations

import pytest

from tw_signal_engine.market_data.load_history_window import load_history_window


def test_load_history_window_requires_target_day_file(tmp_path) -> None:
    (tmp_path / "OTCQuote.20260128").write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="OTCQuote\\.20260129"):
        load_history_window("OTC", "20260129", str(tmp_path))


def test_history_window_excludes_target_date(tmp_path) -> None:
    """The target replay date should NOT appear in history slots."""
    # Create target date and two prior dates
    (tmp_path / "OTCQuote.20260127").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n", encoding="utf-8"
    )
    (tmp_path / "OTCQuote.20260128").write_text(
        "Trade,SYM1,90000000000,0,110000,20\n", encoding="utf-8"
    )
    (tmp_path / "OTCQuote.20260129").write_text(
        "Trade,SYM1,90000000000,0,120000,30\n", encoding="utf-8"
    )

    hw = load_history_window("OTC", "20260129", str(tmp_path))

    # Should have 2 prior sessions, NOT 3
    assert hw.num_days == 2
    assert "20260129" not in hw.source_dates
    assert hw.source_dates[0] == "20260128"
    assert hw.source_dates[1] == "20260127"


def test_history_window_returns_named_result(tmp_path) -> None:
    (tmp_path / "TSEQuote.20260128").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n", encoding="utf-8"
    )
    (tmp_path / "TSEQuote.20260129").write_text("", encoding="utf-8")

    hw = load_history_window("TSE", "20260129", str(tmp_path))

    assert hasattr(hw, "vol_cum")
    assert hasattr(hw, "trading_val")
    assert hasattr(hw, "source_dates")
    assert hw.num_days == 1


def test_history_window_no_val_cum(tmp_path) -> None:
    """val_cum is no longer computed."""
    (tmp_path / "OTCQuote.20260128").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n", encoding="utf-8"
    )
    (tmp_path / "OTCQuote.20260129").write_text("", encoding="utf-8")

    hw = load_history_window("OTC", "20260129", str(tmp_path))
    assert not hasattr(hw, "val_cum")


def test_history_window_vol_cum_and_trading_val(tmp_path) -> None:
    """Verify vol_cum and trading_val are populated correctly."""
    (tmp_path / "OTCQuote.20260128").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n"
        "Trade,SYM1,90100000000,0,100000,20\n",
        encoding="utf-8",
    )
    (tmp_path / "OTCQuote.20260129").write_text("", encoding="utf-8")

    hw = load_history_window("OTC", "20260129", str(tmp_path))

    assert hw.num_days == 1
    # vol_cum should have cumulative volume for SYM1
    tracker = hw.vol_cum[0]
    assert "SYM1" in tracker.data_store
    # Total cumulative volume = 10 + 20 = 30
    assert tracker.data_store["SYM1"][-1].cumulative_qty == 30

    # trading_val = sum of (qty * price // 10) per trade
    # trade 1: 10 * 100000 // 10 = 100000
    # trade 2: 20 * 100000 // 10 = 200000
    assert hw.trading_val[0]["SYM1"] == 300000


def test_history_window_lightweight_parser_skips_bad_lines(tmp_path) -> None:
    """Lightweight parser handles non-trade and bad lines gracefully."""
    (tmp_path / "OTCQuote.20260128").write_text(
        "Depth,SYM1,90000000000,BID:1,100000,ASK:1,100100\n"  # depth line
        "Trade,SYM1,90000000000,0,100000,10\n"  # valid trade
        "Trade,,90000000000,0,100000,10\n"  # empty symbol
        "Trade,SYM2,bad,0,100000,10\n"  # bad time
        "Trade,SYM2,90000000000,1,100000,10\n"  # status_code != 0
        "\n",  # empty line
        encoding="utf-8",
    )
    (tmp_path / "OTCQuote.20260129").write_text("", encoding="utf-8")

    hw = load_history_window("OTC", "20260129", str(tmp_path))

    # Only SYM1 with status_code=0 should appear
    assert hw.num_days == 1
    assert "SYM1" in hw.trading_val[0]
    assert "SYM2" not in hw.trading_val[0]
