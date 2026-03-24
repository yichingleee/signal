"""Generate batch-level aggregated reports across all replay dates."""

from __future__ import annotations

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.build_concentration_report import write_concentration_report
from tw_signal_engine.reporting.build_daily_equity_report import write_daily_equity_report
from tw_signal_engine.reporting.build_regime_report import write_regime_report
from tw_signal_engine.reporting.build_rolling_metrics import write_rolling_metrics_report
from tw_signal_engine.reporting.build_statistics_report import write_statistics_report


def generate_batch_reports(
    all_trades: list[TradeRecord],
    log_dir: str,
) -> None:
    """Generate all batch-level reports."""
    write_daily_equity_report(all_trades, log_dir)
    write_rolling_metrics_report(all_trades, log_dir)
    write_regime_report(all_trades, log_dir)
    write_statistics_report(all_trades, log_dir)
    write_concentration_report(all_trades, log_dir)
