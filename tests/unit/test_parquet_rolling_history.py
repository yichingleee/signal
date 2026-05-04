from __future__ import annotations

from pathlib import Path

import pytest

import tw_signal_engine.market_data.parquet_rolling_history as prh
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.market_data.parquet_rolling_history import ParquetRollingHistoryProvider


def _touch_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"parquet-placeholder")


def test_parquet_rolling_history_reuses_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twse = tmp_path / "TWSE"
    for date in ["20260319", "20260320", "20260321", "20260322", "20260323"]:
        _touch_parquet(twse / f"{date}.parquet")

    loaded_dates: list[str] = []

    def _fake_load_day(
        market_type: str,
        date: str,
        root: str,
        *,
        use_cache: bool = True,
        write_cache: bool = True,
        cache_root: str | None = None,
    ) -> tuple[LinearVolumeTracker, dict[str, int]]:
        assert market_type == "TSE"
        assert root == str(tmp_path)
        loaded_dates.append(date)
        tracker = LinearVolumeTracker()
        tracker.on_tick("1101", 32_400_000_000, int(date[-2:]))
        return tracker, {"1101": int(date)}

    monkeypatch.setattr(prh, "load_parquet_history_day", _fake_load_day)

    provider = ParquetRollingHistoryProvider("TSE", str(tmp_path), use_cache=True, write_cache=True)

    first = provider.get_history("20260322")
    assert first.source_dates == ["20260321", "20260320", "20260319"]
    assert loaded_dates == ["20260321", "20260320", "20260319"]

    second = provider.get_history("20260323")
    assert second.source_dates == ["20260322", "20260321", "20260320", "20260319"]
    # Only the newly required prior day should be loaded on second call.
    assert loaded_dates == ["20260321", "20260320", "20260319", "20260322"]
    assert second.vol_cum[1] is first.vol_cum[0]


def test_parquet_rolling_history_returns_empty_when_no_prior(tmp_path: Path) -> None:
    _touch_parquet(tmp_path / "TWSE" / "20260319.parquet")

    provider = ParquetRollingHistoryProvider("TSE", str(tmp_path), use_cache=True, write_cache=True)
    history = provider.get_history("20260319")

    assert history.num_days == 0
    assert history.source_dates == []
