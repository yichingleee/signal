"""Entry point for chart generation."""

from __future__ import annotations

from tw_signal_engine.records.market_event_records import TradeRecord
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


def generate_daily_charts(
    trades: list[TradeRecord],
    funnel: FunnelTracker | None,
    log_dir: str,
    trade_date: str = "",
    data_dir: str = "./data/",
    prev_day_limit_up: dict[str, bool] | None = None,
) -> None:
    """Generate all per-day charts. Called from _generate_reports()."""
    traded_symbols = {trade.symbol for trade in trades if trade.symbol}
    if traded_symbols and trade_date:
        from tw_signal_engine.reporting.build_trade_day_chart_manifest import write_trade_day_chart_manifest
        from tw_signal_engine.reporting.build_trade_day_traces import build_trade_day_traces, build_trade_markers
        from tw_signal_engine.reporting.charts.trade_day_models import SymbolTradeDay
        from tw_signal_engine.reporting.charts.trade_day_timeline import plot_trade_day_timeline

        traces_by_symbol = build_trade_day_traces(
            trade_date=trade_date,
            data_dir=data_dir,
            traded_symbols=traded_symbols,
            prev_day_limit_up=prev_day_limit_up or {},
        )
        markers_by_symbol = build_trade_markers(trades)

        generated_symbols: list[str] = []
        for symbol in sorted(traded_symbols):
            points = traces_by_symbol.get(symbol, [])
            markers = markers_by_symbol.get(symbol, [])
            if not points or not markers:
                continue
            plot_trade_day_timeline(
                SymbolTradeDay(symbol=symbol, points=points, markers=markers),
                log_dir,
            )
            generated_symbols.append(symbol)

        write_trade_day_chart_manifest(log_dir, generated_symbols, markers_by_symbol)

    if len(trades) < 2:
        return

    from tw_signal_engine.reporting.charts.category_bars import plot_category_bars
    from tw_signal_engine.reporting.charts.concentration import plot_concentration
    from tw_signal_engine.reporting.charts.equity_curve import plot_equity_curve
    from tw_signal_engine.reporting.charts.funnel import plot_funnel
    from tw_signal_engine.reporting.charts.mae_mfe_scatter import plot_mae_mfe_scatter
    from tw_signal_engine.reporting.charts.pnl_distribution import plot_pnl_distribution
    from tw_signal_engine.reporting.charts.trade_scatter import plot_trade_scatter

    plot_equity_curve(trades, log_dir)
    plot_pnl_distribution(trades, log_dir)
    plot_mae_mfe_scatter(trades, log_dir)
    plot_concentration(trades, log_dir)
    plot_category_bars(trades, log_dir)
    plot_trade_scatter(trades, log_dir)

    if funnel is not None:
        plot_funnel(funnel, log_dir)


def generate_batch_charts(
    all_trades: list[TradeRecord],
    log_dir: str,
) -> None:
    """Generate batch-level charts. Called from run_batch_replay."""
    if len(all_trades) < 2:
        return

    from tw_signal_engine.reporting.charts.equity_curve import plot_equity_curve
    from tw_signal_engine.reporting.charts.pnl_distribution import plot_pnl_distribution
    from tw_signal_engine.reporting.charts.regime_heatmap import plot_regime_heatmap
    from tw_signal_engine.reporting.charts.rolling_metrics import plot_rolling_metrics

    plot_equity_curve(all_trades, log_dir)
    plot_pnl_distribution(all_trades, log_dir)
    plot_rolling_metrics(all_trades, log_dir)
    plot_regime_heatmap(all_trades, log_dir)
