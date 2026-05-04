"""Signal A and Signal B mutable state."""

from __future__ import annotations

from dataclasses import dataclass, field

from tw_signal_engine.state.rolling_window import RollingLow, RollingSum


@dataclass
class SignalAState:
    """Per-symbol state for Signal A."""

    symbol: str = ""
    forbidden: bool = False
    triggered: bool = False
    near_vwap: bool = False
    low_since_near: int = 0
    high_since_near: int = 0
    near_vwap_time_us: int = 0
    near_vwap_time: int = 0
    near_vwap_pv_ratio: float = 0.0


@dataclass
class SignalBState:
    """Per-symbol state for Signal B."""

    symbol: str = ""
    forbidden: bool = False
    rolling_low: RollingLow = field(default_factory=RollingLow)
    rolling_sum_short: RollingSum = field(default_factory=RollingSum)
    rolling_sum_long: RollingSum = field(default_factory=RollingSum)
    rolling_low_val: int = 0
    rolling_sum_ratio: float = 0.0
    in_buffer_zone: bool = False
    buffer_zone_match_type: str = "None"
    buffer_zone_trigger_price: int = -1
    buffer_zone_start_time: int = -1
    in_trade_zone: bool = False
    trade_zone_match_type: str = "None"
    trade_zone_trigger_price: int = -1
    trade_zone_start_time: int = -1
    enter_market: bool = False


@dataclass
class SignalDayHighState:
    """Per-symbol state for SignalDayHigh."""

    symbol: str = ""
    triggered: bool = False
    established_high: int = 0
    established_high_time: int = 0
    pullback_confirmed: bool = False
    pullback_low: int = 0
    pullback_time: int = 0
    entries: int = 0
    last_trigger_high: int = 0
    last_trigger_high_time: int = 0
    last_trigger_pullback_low: int = 0
    last_trigger_pullback_time: int = 0
    last_trigger_time: int = 0
