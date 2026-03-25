"""Generate report_statistics.csv with statistical robustness metrics."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from tw_signal_engine.records.market_event_records import TradeRecord


def _bootstrap_ci(
    values: list[float],
    stat_fn: str,
    n_resamples: int = 10_000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """Compute bootstrap confidence interval using numpy.

    stat_fn: 'mean' or 'profit_factor'
    """
    try:
        import numpy as np
    except ImportError:
        return (0.0, 0.0)

    rng = np.random.default_rng(42)
    arr = np.array(values)
    n = len(arr)
    if n == 0:
        return (0.0, 0.0)

    stats: list[float] = []
    for _ in range(n_resamples):
        sample = rng.choice(arr, size=n, replace=True)
        if stat_fn == "mean":
            stats.append(float(np.mean(sample)))
        elif stat_fn == "profit_factor":
            wins = float(np.sum(sample[sample > 0]))
            losses = float(np.sum(sample[sample < 0]))
            pf = wins / (-losses) if losses != 0 else 0.0
            stats.append(pf)

    alpha = (1 - ci) / 2
    lower = float(np.percentile(stats, alpha * 100))
    upper = float(np.percentile(stats, (1 - alpha) * 100))
    return (lower, upper)


def _skewness(values: list[float], mean: float, std: float) -> float:
    """Compute skewness (Fisher)."""
    n = len(values)
    if n < 3 or std == 0:
        return 0.0
    m3 = sum((v - mean) ** 3 for v in values) / n
    return m3 / (std ** 3)


def _kurtosis(values: list[float], mean: float, std: float) -> float:
    """Compute excess kurtosis."""
    n = len(values)
    if n < 4 or std == 0:
        return 0.0
    m4 = sum((v - mean) ** 4 for v in values) / n
    return m4 / (std ** 4) - 3.0


def write_statistics_report(completed_trades: list[TradeRecord], log_dir: str) -> None:
    """Write report_statistics.csv."""
    if not completed_trades:
        return

    path = Path(log_dir) / "report_statistics.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    pnls = [t.pnl for t in completed_trades]
    returns = [t.return_pct for t in completed_trades]
    n = len(pnls)

    total_pnl = sum(pnls)
    mean_pnl = total_pnl / n
    sorted_pnls = sorted(pnls)
    if n % 2 == 1:
        median_pnl = sorted_pnls[n // 2]
    else:
        median_pnl = (sorted_pnls[n // 2 - 1] + sorted_pnls[n // 2]) / 2

    std_pnl = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / n) if n > 0 else 0.0
    mean_return = sum(returns) / n

    # Expectancy
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / n if n > 0 else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # Payoff ratio
    payoff_ratio = avg_win / (-avg_loss) if avg_loss != 0 else 0.0

    # Skewness and kurtosis
    skew = _skewness(pnls, mean_pnl, std_pnl)
    kurt = _kurtosis(pnls, mean_pnl, std_pnl)

    # Profit factor
    gross_win = sum(wins)
    gross_loss = sum(losses)
    profit_factor = gross_win / (-gross_loss) if gross_loss != 0 else 0.0

    # Bootstrap CIs
    ci_mean = _bootstrap_ci(pnls, "mean")
    ci_pf = _bootstrap_ci(pnls, "profit_factor")

    # Expectancy in bps (relative to position cash if available)
    # Derive position_cash from first trade with non-zero return_pct
    position_cash = 0.0
    for t in completed_trades:
        if t.return_pct != 0:
            position_cash = t.pnl / t.return_pct * 100
            break
    expectancy_bps = expectancy / position_cash * 10000 if position_cash != 0 else 0.0

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Metric", "Value"])
        w.writerow(["N Trades", str(n)])
        w.writerow(["Mean PnL", f"{mean_pnl:.0f}"])
        w.writerow(["Median PnL", f"{median_pnl:.0f}"])
        w.writerow(["Std Dev PnL", f"{std_pnl:.0f}"])
        w.writerow(["Mean Return%", f"{mean_return:.2f}%"])
        w.writerow(["Expectancy", f"{expectancy:.0f}"])
        w.writerow(["Expectancy (bps)", f"{expectancy_bps:.1f}"])
        w.writerow(["Payoff Ratio", f"{payoff_ratio:.2f}"])
        w.writerow(["Skewness", f"{skew:.3f}"])
        w.writerow(["Kurtosis", f"{kurt:.3f}"])
        w.writerow(["Profit Factor", f"{profit_factor:.2f}"])
        w.writerow(["Bootstrap 95% CI Mean PnL", f"[{ci_mean[0]:.0f}, {ci_mean[1]:.0f}]"])
        w.writerow(["Bootstrap 95% CI Profit Factor", f"[{ci_pf[0]:.2f}, {ci_pf[1]:.2f}]"])
    print(f"[Report] {path}")
