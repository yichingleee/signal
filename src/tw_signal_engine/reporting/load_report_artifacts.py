"""Load persisted report artifacts into chart-generation models."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import cast

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


def list_available_replay_dates(log_dir: str | Path) -> list[str]:
    """List available replay-date directories (YYYYMMDD) under a log directory."""
    root = Path(log_dir)
    if not root.exists():
        return []
    dates = [
        p.name
        for p in root.iterdir()
        if p.is_dir() and p.name.isdigit() and len(p.name) == 8
    ]
    return sorted(dates)


def select_replay_dates(
    log_dir: str | Path,
    trade_date: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[str]:
    """Select replay dates from log_dir using either one date, a range, or all."""
    dates = list_available_replay_dates(log_dir)
    if not dates:
        return []

    if trade_date and (start or end):
        raise ValueError("Use either --date or --start/--end, not both.")
    if (start and not end) or (end and not start):
        raise ValueError("Both --start and --end are required for range selection.")

    if trade_date:
        return [d for d in dates if d == trade_date]
    if start and end:
        return [d for d in dates if start <= d <= end]
    return dates


def _to_float(value: str | None) -> float:
    raw = (value or "").strip().replace(",", "")
    if not raw:
        return 0.0
    if raw.endswith("%"):
        raw = raw[:-1]
    return float(raw)


def _to_int(value: str | None) -> int:
    raw = (value or "").strip().replace(",", "")
    if not raw:
        return 0
    return int(raw)


def _parse_hms_to_raw(value: str | None) -> int:
    raw = (value or "").strip()
    if not raw:
        return 0
    hh, mm, ss = (int(x) for x in raw.split(":"))
    return (hh * 10000 + mm * 100 + ss) * 1_000_000


def _raw_to_hms(value: int) -> str:
    hhmmss = value // 1_000_000
    hh = hhmmss // 10000
    mm = (hhmmss % 10000) // 100
    ss = hhmmss % 100
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _load_exit_prices(day_dir: Path, trade_date: str) -> dict[tuple[str, str], float]:
    """Load leave prices keyed by (symbol, HH:MM:SS) from order log."""
    path = day_dir / f"order_log_{trade_date}.csv"
    if not path.exists():
        return {}

    prices: dict[tuple[str, str], float] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw_row in reader:
            row = cast(dict[str, str], raw_row)
            if (row.get("Action") or "").strip() != "leave":
                continue
            symbol = (row.get("Symbol") or "").strip()
            raw_time = _to_int(row.get("Time"))
            raw_price = _to_int(row.get("Price"))
            if not symbol or raw_time <= 0 or raw_price <= 0:
                continue
            prices[(symbol, _raw_to_hms(raw_time))] = raw_price / 10000.0
    return prices


def load_trade_records(day_dir: str | Path, trade_date: str) -> list[TradeRecord]:
    """Load per-day trades from report_trades.csv plus order-log exit prices."""
    day_path = Path(day_dir)
    report_path = day_path / "report_trades.csv"
    if not report_path.exists():
        return []

    exit_prices = _load_exit_prices(day_path, trade_date)
    records: list[TradeRecord] = []
    with open(report_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw_row in reader:
            row = cast(dict[str, str], raw_row)
            symbol = (row.get("Symbol") or "").strip()
            if not symbol:
                continue
            entry_time = (row.get("EntryTime") or "").strip()
            exit_time = (row.get("ExitTime") or "").strip()
            records.append(
                TradeRecord(
                    symbol=symbol,
                    side=(row.get("Side") or "long").strip() or "long",
                    signal_type=(row.get("SignalType") or "").strip(),
                    enter_cause=(row.get("EnterCause") or "").strip(),
                    final_leave_cause=(row.get("LeaveCause") or "").strip(),
                    entry_time_raw=_parse_hms_to_raw(entry_time),
                    exit_time_raw=_parse_hms_to_raw(exit_time),
                    pnl=_to_float(row.get("PnL")),
                    return_pct=_to_float(row.get("Return%")),
                    group_name=(row.get("GroupName") or "").strip(),
                    group_rank=_to_int(row.get("GroupRank")),
                    member_rank=_to_int(row.get("MemberRank")),
                    raw_member_rank=_to_int(row.get("RawMemberRank")),
                    m1_symbol=(row.get("M1Symbol") or "").strip(),
                    entry_price=_to_float(row.get("EntryPrice")),
                    exit_price=exit_prices.get((symbol, exit_time), 0.0),
                    entry_vwap=_to_float(row.get("EntryVWAP")),
                    day_high_at_entry=_to_float(row.get("DayHigh")),
                    prev_close=_to_float(row.get("PrevClose")),
                    vol_ratio=_to_float(row.get("VolRatio")),
                    month_trading_val=_to_int(row.get("MonthTradingVal")),
                    is_prev_day_lu=_to_int(row.get("IsPrevDayLU")) > 0,
                    is_disposition=_to_int(row.get("IsDisposition")) > 0,
                    had_circuit_breaker=_to_int(row.get("HadCircuitBreaker")) > 0,
                    group_limit_up_count=_to_int(row.get("GroupLimitUpCount")),
                    market_entry_chg_pct=_to_float(row.get("0050EntryChg%")),
                    mae_pct=_to_float(row.get("MAE%")),
                    mfe_pct=_to_float(row.get("MFE%")),
                    mae_price=_to_float(row.get("MAEPrice")),
                    mfe_price=_to_float(row.get("MFEPrice")),
                    time_to_first_tp_sec=_to_int(row.get("TimeToFirstTP")),
                    tp_slices_filled=_to_int(row.get("TPSlicesFilled")),
                    gross_pnl=_to_float(row.get("GrossPnL")),
                    commission=_to_float(row.get("Commission")),
                    tax=_to_float(row.get("Tax")),
                    slippage=_to_float(row.get("Slippage")),
                    net_pnl=_to_float(row.get("NetPnL")),
                    tp_pnl=_to_float(row.get("TPPnL")),
                    residual_pnl=_to_float(row.get("ResidualPnL")),
                    trade_date=(row.get("TradeDate") or trade_date).strip() or trade_date,
                    entry_hour_bucket=(row.get("EntryHourBucket") or "").strip(),
                )
            )
    return records


def load_funnel_tracker(day_dir: str | Path) -> FunnelTracker | None:
    """Load FunnelTracker from report_funnel.csv, or None if missing."""
    path = Path(day_dir) / "report_funnel.csv"
    if not path.exists():
        return None

    funnel = FunnelTracker()
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if len(row) < 3:
                continue
            section = row[0].strip()
            if section == "Pipeline":
                stage = row[1].strip()
                count = _to_int(row[2])
                if stage == "Universe":
                    funnel.universe_count = count
                elif stage == "Valid Group Symbols":
                    funnel.valid_group_symbols = count
                elif stage == "Group Qualified Ticks":
                    funnel.group_qualified_ticks = count
                elif stage == "Signal Triggered":
                    funnel.signal_triggered = count
                elif stage == "Entry Filter Blocked":
                    funnel.entry_filter_blocked = count
                elif stage == "Executed Trades":
                    funnel.executed_trades = count
            elif section == "BlockReasons":
                reason = row[1].strip()
                if reason:
                    funnel.entry_filter_reasons[reason] = _to_int(row[2])
    return funnel


def load_batch_trade_records(log_dir: str | Path, dates: list[str]) -> list[TradeRecord]:
    """Load all trade records for selected dates under the batch log directory."""
    root = Path(log_dir)
    all_records: list[TradeRecord] = []
    for date in dates:
        all_records.extend(load_trade_records(root / date, date))
    return all_records
