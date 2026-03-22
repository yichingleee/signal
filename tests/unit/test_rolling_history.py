"""Tests for the rolling history provider."""

from __future__ import annotations

from tw_signal_engine.market_data.rolling_history import RollingHistoryProvider


def _create_data_files(tmp_path, market: str, dates: list[str]) -> str:
    """Create minimal replay files for given dates."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    for date in dates:
        (data_dir / f"{market}Quote.{date}").write_text(
            "Trade,SYM1,90000000000,0,100000,10\n",
            encoding="utf-8",
        )
    return str(data_dir)


def test_rolling_history_reuses_sessions(tmp_path) -> None:
    """Adjacent dates should share already-loaded sessions."""
    dates = ["20260120", "20260121", "20260122", "20260123", "20260124"]
    data_dir = _create_data_files(tmp_path, "OTC", dates)

    provider = RollingHistoryProvider("OTC", data_dir, use_cache=False)

    # Get history for 20260123 (should have 20260120, 21, 22 as prior)
    hw1 = provider.get_history("20260123")
    assert hw1.num_days == 3
    assert "20260122" in hw1.source_dates
    assert "20260121" in hw1.source_dates
    assert "20260120" in hw1.source_dates

    # Get history for 20260124 (should have 20260121, 22, 23 as prior)
    hw2 = provider.get_history("20260124")
    assert hw2.num_days == 4
    assert "20260123" in hw2.source_dates
    assert "20260122" in hw2.source_dates


def test_rolling_history_excludes_target(tmp_path) -> None:
    dates = ["20260120", "20260121", "20260122"]
    data_dir = _create_data_files(tmp_path, "TSE", dates)

    provider = RollingHistoryProvider("TSE", data_dir, use_cache=False)
    hw = provider.get_history("20260122")

    assert hw.num_days == 2
    assert "20260122" not in hw.source_dates


def test_rolling_history_empty_prior(tmp_path) -> None:
    """First date has no prior sessions."""
    data_dir = _create_data_files(tmp_path, "OTC", ["20260120"])

    provider = RollingHistoryProvider("OTC", data_dir, use_cache=False)
    hw = provider.get_history("20260120")

    assert hw.num_days == 0


def test_rolling_history_data_integrity(tmp_path) -> None:
    """Check that the vol_cum data is correct after rolling."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "OTCQuote.20260120").write_text(
        "Trade,SYM1,90000000000,0,100000,10\n", encoding="utf-8"
    )
    (data_dir / "OTCQuote.20260121").write_text(
        "Trade,SYM1,90000000000,0,200000,20\n", encoding="utf-8"
    )
    (data_dir / "OTCQuote.20260122").write_text("", encoding="utf-8")

    provider = RollingHistoryProvider("OTC", str(data_dir), use_cache=False)
    hw = provider.get_history("20260122")

    assert hw.num_days == 2
    # Index 0 = most recent prior (20260121), index 1 = older (20260120)
    assert hw.source_dates[0] == "20260121"
    assert hw.source_dates[1] == "20260120"
    assert hw.trading_val[0]["SYM1"] == 20 * 200000 // 10
    assert hw.trading_val[1]["SYM1"] == 10 * 100000 // 10
