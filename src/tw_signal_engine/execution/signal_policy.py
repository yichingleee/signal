"""Signal-specific execution policy switches."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import ExecutionConfig


@dataclass(frozen=True)
class ExecutionPolicy:
    enable_take_profit: bool = True
    enable_bailout: bool = True
    hold_overnight_on_limit_up: bool = False


@dataclass(frozen=True)
class DayHighExitPolicyDescription:
    """Concrete DayHigh exit policy values for dashboard explainability."""

    stop_basis: str = "entry_vwap"
    stop_anchor: float = 0.0
    stop_price: float = 0.0
    time_exit_deadline: str = ""
    take_profit_enabled: bool = False
    bailout_enabled: bool = False
    hold_overnight_on_limit_up: bool = False
    currently_limit_up_locked: bool = False
    overnight_eligible_now: bool = False


def _format_match_time(match_time_str: int) -> str:
    raw = match_time_str // 1_000_000
    sec = raw % 100
    raw //= 100
    minute = raw % 100
    hour = raw // 100
    return f"{hour:02d}:{minute:02d}:{sec:02d}"


def policy_for_signal(signal_type: str, config: ExecutionConfig) -> ExecutionPolicy:
    if signal_type == "SignalDayHigh":
        return ExecutionPolicy(
            enable_take_profit=False,
            enable_bailout=False,
            hold_overnight_on_limit_up=config.hold_overnight_on_limit_up,
        )
    return ExecutionPolicy()


def describe_day_high_exit_policy(
    config: ExecutionConfig,
    entry_vwap: float,
    currently_limit_up_locked: bool = False,
) -> DayHighExitPolicyDescription:
    """Return DayHigh exit policy details from the shared execution settings."""
    policy = policy_for_signal("SignalDayHigh", config)
    stop_anchor = entry_vwap if entry_vwap > 0 else 0.0
    stop_price = stop_anchor * config.stop_loss_ratio_day_high if stop_anchor > 0 else 0.0
    overnight_eligible_now = (
        policy.hold_overnight_on_limit_up
        and currently_limit_up_locked
    )
    return DayHighExitPolicyDescription(
        stop_basis="entry_vwap",
        stop_anchor=stop_anchor,
        stop_price=stop_price,
        time_exit_deadline=_format_match_time(config.exit_time_limit),
        take_profit_enabled=policy.enable_take_profit,
        bailout_enabled=policy.enable_bailout,
        hold_overnight_on_limit_up=policy.hold_overnight_on_limit_up,
        currently_limit_up_locked=currently_limit_up_locked,
        overnight_eligible_now=overnight_eligible_now,
    )
