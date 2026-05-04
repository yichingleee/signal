"""Regression tests for replay CLI data-dir resolution."""

from __future__ import annotations

import sys
from unittest.mock import patch

from tw_signal_engine.cli.run_batch_replay import main as run_batch_replay_main
from tw_signal_engine.cli.run_daily_replay import main as run_daily_replay_main


def test_run_daily_replay_text_mode_uses_env_data_dir(monkeypatch) -> None:
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", "/tmp/text-data")

    with patch("tw_signal_engine.replay.replay_session.run_daily_replay", return_value=[]) as mock_replay:
        with patch.object(
            sys,
            "argv",
            ["prog", "--date", "20260101", "--data-source", "text"],
        ):
            run_daily_replay_main()

    assert mock_replay.call_args.kwargs["data_dir"] == "/tmp/text-data"


@patch("tw_signal_engine.cli.run_batch_replay._get_trading_dates", return_value=["20260101"])
@patch("tw_signal_engine.replay.replay_session.run_daily_replay", return_value=[])
@patch("tw_signal_engine.replay.replay_session._merge_history_windows", return_value=None)
@patch("tw_signal_engine.market_data.rolling_history.RollingHistoryProvider")
def test_run_batch_replay_text_mode_uses_env_data_dir(
    mock_provider_cls,
    _mock_merge,
    mock_replay,
    _mock_dates,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", "/tmp/text-data")
    mock_provider_cls.return_value.get_history.return_value = None

    with patch.object(
        sys,
        "argv",
        ["prog", "--start", "20260101", "--end", "20260101", "--data-source", "text"],
    ):
        run_batch_replay_main()

    assert mock_provider_cls.call_args_list[0].args[1] == "/tmp/text-data"
    assert mock_replay.call_args.kwargs["data_dir"] == "/tmp/text-data"
