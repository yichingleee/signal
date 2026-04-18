"""Signal-specific execution policy switches."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import ExecutionConfig


@dataclass(frozen=True)
class ExecutionPolicy:
    enable_take_profit: bool = True
    enable_bailout: bool = True
    hold_overnight_on_limit_up: bool = False


def policy_for_signal(signal_type: str, config: ExecutionConfig) -> ExecutionPolicy:
    if signal_type == "SignalDayHigh":
        return ExecutionPolicy(
            enable_take_profit=False,
            enable_bailout=False,
            hold_overnight_on_limit_up=config.hold_overnight_on_limit_up,
        )
    return ExecutionPolicy()
