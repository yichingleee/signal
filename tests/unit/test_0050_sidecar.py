from __future__ import annotations

import json
from pathlib import Path

import pytest

from tw_signal_engine.config.strategy_config import NormalizedStrategyConfig
from tw_signal_engine.market_data.history_window import HistoryWindow
from tw_signal_engine.market_data.proxy_0050_sidecar import (
    SIDECAR_SYMBOL,
    build_0050_sidecar,
    is_sidecar_fresh,
    load_0050_sidecar,
    sidecar_meta_path,
    sidecar_path,
)
from tw_signal_engine.records.market_event_records import MarketTick, QuotePair
from tw_signal_engine.records.reference_records import ReferenceSymbol


def _write_text_fixture(path: Path) -> None:
    lines = [
        "Trade,2330,90000000000,0,1000000,10",
        "Trade,0050,90001000000,0,1234500,20",
        "Trade,0050,90002000000,0,1234600,30",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ref(symbol: str, previous_close: float = 100.0) -> ReferenceSymbol:
    return ReferenceSymbol(
        symbol=symbol,
        name=symbol,
        market="TSE",
        previous_close=previous_close,
        limit_up_price=110.0,
        limit_down_price=90.0,
        industry="",
        security="",
        error_code="0",
    )


def _tick(symbol: str, time_str: int, price: int) -> MarketTick:
    tick = MarketTick(
        symbol=symbol,
        market="TSE",
        match_time_str=time_str,
        match_time_us=time_str // 1000,
        status_code=0,
        trade_code=1,
        match=QuotePair(price=price, qty=1),
    )
    tick.bid[0].price = price
    return tick


def test_build_sidecar_writes_parquet_and_metadata(tmp_path: Path) -> None:
    text_root = tmp_path / "text"
    text_root.mkdir(parents=True)
    date = "20260129"
    _write_text_fixture(text_root / f"TSEQuote.{date}")

    sidecar_root = tmp_path / "sidecars"
    result = build_0050_sidecar(date, text_root, sidecar_root)

    assert result.status == "built"
    assert result.row_count == 2
    assert sidecar_path(sidecar_root, date).exists()
    assert sidecar_meta_path(sidecar_root, date).exists()

    metadata = json.loads(sidecar_meta_path(sidecar_root, date).read_text(encoding="utf-8"))
    assert metadata["date"] == date
    assert metadata["row_count"] == 2
    assert metadata["schema_version"] == 1


def test_load_sidecar_round_trips_market_gate_fields(tmp_path: Path) -> None:
    text_root = tmp_path / "text"
    text_root.mkdir(parents=True)
    date = "20260129"
    _write_text_fixture(text_root / f"TSEQuote.{date}")

    sidecar_root = tmp_path / "sidecars"
    build_0050_sidecar(date, text_root, sidecar_root)

    ticks = list(load_0050_sidecar(date, sidecar_root))
    assert [tick.symbol for tick in ticks] == [SIDECAR_SYMBOL, SIDECAR_SYMBOL]
    assert [tick.match_time_str for tick in ticks] == [90001000000, 90002000000]
    assert [tick.match.price for tick in ticks] == [1234500, 1234600]
    assert [tick.match.qty for tick in ticks] == [20, 30]
    assert [tick.status_code for tick in ticks] == [0, 0]
    assert [tick.trade_code for tick in ticks] == [1, 1]
    assert [tick.trade_at for tick in ticks] == [0, 0]


def test_fresh_sidecar_is_skipped(tmp_path: Path) -> None:
    text_root = tmp_path / "text"
    text_root.mkdir(parents=True)
    date = "20260129"
    _write_text_fixture(text_root / f"TSEQuote.{date}")

    sidecar_root = tmp_path / "sidecars"
    first = build_0050_sidecar(date, text_root, sidecar_root)
    second = build_0050_sidecar(date, text_root, sidecar_root)

    assert first.status == "built"
    assert is_sidecar_fresh(date, text_root, sidecar_root)
    assert second.status == "skipped_fresh"
    assert second.row_count == 2


def test_force_rebuild_ignores_fresh_metadata(tmp_path: Path) -> None:
    text_root = tmp_path / "text"
    text_root.mkdir(parents=True)
    date = "20260129"
    _write_text_fixture(text_root / f"TSEQuote.{date}")

    sidecar_root = tmp_path / "sidecars"
    build_0050_sidecar(date, text_root, sidecar_root)
    forced = build_0050_sidecar(date, text_root, sidecar_root, force=True)

    assert forced.status == "built"
    assert forced.row_count == 2


def test_cli_dry_run_discovers_dates_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tw_signal_engine.cli import build_0050_sidecar as cli

    text_root = tmp_path / "text"
    text_root.mkdir(parents=True)
    _write_text_fixture(text_root / "TSEQuote.20260129")
    _write_text_fixture(text_root / "TSEQuote.20260130")
    _write_text_fixture(text_root / "TSEQuote.20260203")

    sidecar_root = tmp_path / "sidecars"
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_0050_sidecar",
            "--start",
            "20260129",
            "--end",
            "20260131",
            "--text-data-dir",
            str(text_root),
            "--sidecar-dir",
            str(sidecar_root),
            "--dry-run",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert not sidecar_root.exists()

    output = capsys.readouterr().out
    assert "Building 2 0050 sidecars" in output
    assert "20260129" in output
    assert "20260130" in output
    assert "20260203" not in output


def test_run_daily_replay_prefers_sidecar_over_text_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tw_signal_engine.replay import replay_session as rs

    class _Provider:
        def iterate_ticks(self):
            yield _tick("2330", 93000000000, 5_000_000)

    date = "20260129"
    (tmp_path / f"Symbols_{date}.csv").write_text("symbol,name\n0050,ETF\n2330,TSMC\n", encoding="utf-8")
    sidecar_file = tmp_path / "0050" / f"{date}.parquet"
    sidecar_file.parent.mkdir(parents=True, exist_ok=True)
    sidecar_file.write_bytes(b"placeholder")

    monkeypatch.setattr(rs, "load_legacy_ini", lambda _: {})
    monkeypatch.setattr(rs, "normalize_strategy_config", lambda _: NormalizedStrategyConfig())
    monkeypatch.setattr(rs, "load_symbol_reference", lambda *_: {"0050": _ref("0050"), "2330": _ref("2330")})
    monkeypatch.setattr(rs, "derive_prev_day_limit_up", lambda *_: {})
    monkeypatch.setattr(rs, "load_group_membership", lambda *_: ([], {}, {}))
    monkeypatch.setattr(rs, "default_sidecar_root", lambda _: tmp_path)
    monkeypatch.setattr(rs, "load_0050_sidecar", lambda *_: iter([_tick("0050", 90001000000, 1_000_000)]))
    monkeypatch.setattr(
        rs,
        "_find_0050_proxy_text_dir",
        lambda *_: (_ for _ in ()).throw(AssertionError("text proxy should not be used")),
    )

    trades = rs.run_daily_replay(
        trade_date=date,
        history=HistoryWindow(vol_cum=[], trading_val=[], source_dates=[]),
        provider=_Provider(),
        data_source="parquet",
        data_dir=str(tmp_path),
        files_dir=str(tmp_path),
        group_file=str(tmp_path / "group.csv"),
        no_charts=True,
        write_outputs=False,
    )

    assert trades == []
    output = capsys.readouterr().out
    assert "[GATE] 0050 sidecar:" in output
    assert "[GATE] 0050 proxy stream:" not in output
