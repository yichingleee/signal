from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tw_signal_engine.market_data.parquet_history_cache import parquet_history_cache_path


def _write_minimal_history_parquet(path: Path) -> None:
    table = pa.table(
        {
            "symbol": pa.array(["1101"], type=pa.string()),
            "time": pa.array([90000000000], type=pa.int64()),
            "matchFlag": pa.array(["Y"], type=pa.string()),
            "tradePrice": pa.array([10.0], type=pa.float64()),
            "tradeVolume": pa.array([100], type=pa.int32()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


def test_cli_dry_run_lists_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tw_signal_engine.cli import build_parquet_history_cache as cli

    root = tmp_path / "ticks"
    _write_minimal_history_parquet(root / "TWSE" / "20260320.parquet")
    _write_minimal_history_parquet(root / "TWSE" / "20260321.parquet")

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_parquet_history_cache",
            "--start",
            "20260320",
            "--end",
            "20260320",
            "--data-dir",
            str(root),
            "--market",
            "TSE",
            "--dry-run",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "Building 1 parquet history caches" in output
    assert "TSE 20260320" in output
    assert "20260321" not in output


def test_cli_builds_cache_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tw_signal_engine.cli import build_parquet_history_cache as cli

    root = tmp_path / "ticks"
    cache_root = tmp_path / "cache"
    _write_minimal_history_parquet(root / "TWSE" / "20260320.parquet")

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_parquet_history_cache",
            "--start",
            "20260320",
            "--end",
            "20260320",
            "--data-dir",
            str(root),
            "--cache-dir",
            str(cache_root),
            "--market",
            "TSE",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "status=built" in output
    assert parquet_history_cache_path(cache_root, "TSE", "20260320").exists()
