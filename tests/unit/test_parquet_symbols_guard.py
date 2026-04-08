from __future__ import annotations

from pathlib import Path

from tw_signal_engine.cli.run_batch_replay import _split_dates_by_symbols_file
from tw_signal_engine.replay.replay_session import _symbols_file_missing


def test_split_dates_by_symbols_file_partitions_dates(tmp_path: Path) -> None:
    (tmp_path / "Symbols_20260326.csv").write_text("symbol,name\n1101,DUMMY\n")
    (tmp_path / "Symbols_20260327.csv").write_text("symbol,name\n1101,DUMMY\n")

    ok, missing = _split_dates_by_symbols_file(
        ["20260325", "20260326", "20260327", "20260328"],
        str(tmp_path),
    )

    assert ok == ["20260326", "20260327"]
    assert missing == ["20260325", "20260328"]


def test_symbols_file_missing_detects_absent_file(tmp_path: Path) -> None:
    assert _symbols_file_missing(str(tmp_path), "20260407")
    (tmp_path / "Symbols_20260407.csv").write_text("symbol,name\n0050,DUMMY\n")
    assert not _symbols_file_missing(str(tmp_path), "20260407")
