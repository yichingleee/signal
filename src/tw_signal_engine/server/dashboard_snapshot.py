"""Dashboard snapshot data models for the V1 dashboard.

These dataclasses define the canonical schema consumed by all dashboard API
endpoints.  Both live mode (via LiveState) and replay mode (via ReplayManager)
produce the same structures so the frontend is mode-agnostic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

# ── Strong Group ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class MemberSnapshot:
    """One stock within a strong group."""

    symbol: str = ""
    name: str = ""
    price: float = 0.0
    pct_chg: float = 0.0
    vwap: float = 0.0
    vwap_pct_chg: float = 0.0
    cum_vol_ratio: float = 0.0
    vol_shrink_ratio: float = 0.0
    member_rank: int = 0


@dataclass(slots=True)
class GroupSnapshot:
    """One strong group with its ranked members."""

    group_name: str = ""
    group_rank: int = 0
    avg_pct_chg: float = 0.0
    vol_ratio: float = 0.0
    avg_vol_surge: float = 0.0
    members: list[MemberSnapshot] = field(default_factory=list)


# ── Strong Single ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class SingleSnapshot:
    """One individually-strong stock (not via group)."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    price: float = 0.0
    pct_chg: float = 0.0
    vwap: float = 0.0
    vwap_pct_chg: float = 0.0
    cum_vol_ratio: float = 0.0
    vol_shrink_ratio: float = 0.0


# ── VWAP Monitor ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class VWAPMonitorEntry:
    """Per-symbol VWAP tracking row."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    price: float = 0.0
    vwap: float = 0.0
    vwap_pct: float = 0.0
    pv_ratio: float = 0.0
    signal_a_state: str = "idle"
    status: str = ""


# ── Signal A Monitor ──────────────────────────────────────────────────────


@dataclass(slots=True)
class PreparingEntry:
    """Stock qualifying for entry: screening passed + near_vwap detected."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    group_tag: str = ""
    order_price: float = 0.0
    current_price: float = 0.0
    distance_pct: float = 0.0
    vwap: float = 0.0
    day_low: float = 0.0
    stop_loss: float = 0.0
    near_vwap_pv_ratio: float = 0.0
    side: str = "long"


@dataclass(slots=True)
class ActivePosition:
    """Currently held position from Signal A entry."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    group_tag: str = ""
    entry_price: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    day_high: float = 0.0
    entry_time: str = ""
    side: str = "long"
    qty: float = 0.0


@dataclass(slots=True)
class CompletedTrade:
    """Closed trade from today's session."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    group_tag: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    exit_cause: str = ""
    side: str = "long"


@dataclass(slots=True)
class SignalCounters:
    """Summary bar counters for Signal A monitoring."""

    qualified: int = 0
    not_qualified: int = 0
    holding: int = 0
    take_profit: int = 0
    stop_loss: int = 0
    forbidden: int = 0


@dataclass(slots=True)
class SignalAMonitorSnapshot:
    """Full Signal A monitoring view."""

    preparing: list[PreparingEntry] = field(default_factory=list)
    entered: list[ActivePosition] = field(default_factory=list)
    exited: list[CompletedTrade] = field(default_factory=list)
    counters: SignalCounters = field(default_factory=SignalCounters)


# ── Other signal-family monitors ─────────────────────────────────────────


@dataclass(slots=True)
class DashboardModuleStatus:
    """Dashboard module availability for source-dashboard parity."""

    key: str = ""
    label: str = ""
    availability: Literal["available", "unavailable"] = "available"
    reason: str = ""
    source_equivalent: str = ""


@dataclass(slots=True)
class SignalBMonitorEntry:
    """Per-symbol Signal B state exposed to the dashboard."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    forbidden: bool = False
    in_buffer_zone: bool = False
    in_trade_zone: bool = False
    enter_market: bool = False
    rolling_low: float = 0.0
    rolling_sum_ratio: float = 0.0
    status: str = ""


@dataclass(slots=True)
class SignalBMonitorSnapshot:
    """Signal B dashboard summary."""

    rows: list[SignalBMonitorEntry] = field(default_factory=list)
    buffer_zone: int = 0
    trade_zone: int = 0
    triggered: int = 0
    forbidden: int = 0


SignalDayHighPhase = Literal["tracking", "pullback", "triggered", "holding", "exited"]


@dataclass(slots=True)
class SignalDayHighMonitorEntry:
    """Per-symbol SignalDayHigh pullback/breakout state."""

    symbol: str = ""
    name: str = ""
    group_name: str = ""
    triggered: bool = False
    established_high: float = 0.0
    established_high_time: str = ""
    pullback_confirmed: bool = False
    pullback_low: float = 0.0
    pullback_time: str = ""
    last_trigger_high: float = 0.0
    last_trigger_high_time: str = ""
    last_trigger_pullback_low: float = 0.0
    last_trigger_pullback_time: str = ""
    trigger_time: str = ""
    phase: SignalDayHighPhase = "tracking"
    entries: int = 0
    status: str = ""


@dataclass(slots=True)
class SignalDayHighPhaseCounts:
    """Explicit phase counts for DayHigh row population."""

    tracking: int = 0
    pullback: int = 0
    triggered: int = 0
    holding: int = 0
    exited: int = 0


@dataclass(slots=True)
class SignalDayHighMonitorSnapshot:
    """SignalDayHigh dashboard summary."""

    rows: list[SignalDayHighMonitorEntry] = field(default_factory=list)
    preparing: list[PreparingEntry] = field(default_factory=list)
    entered: list[ActivePosition] = field(default_factory=list)
    exited: list[CompletedTrade] = field(default_factory=list)
    counters: SignalCounters = field(default_factory=SignalCounters)
    phase_counts: SignalDayHighPhaseCounts = field(default_factory=SignalDayHighPhaseCounts)
    tracking: int = 0
    pullback: int = 0
    triggered: int = 0
    entries: int = 0


# ── Top-level snapshot ────────────────────────────────────────────────────


@dataclass
class DashboardSnapshot:
    """Complete dashboard state at a point in time."""

    timestamp: str = ""
    time_raw: int = 0
    tick_count: int = 0

    groups: list[GroupSnapshot] = field(default_factory=list)
    singles: list[SingleSnapshot] = field(default_factory=list)
    vwap_monitor: list[VWAPMonitorEntry] = field(default_factory=list)
    signal_a: SignalAMonitorSnapshot = field(default_factory=SignalAMonitorSnapshot)
    signal_b: SignalBMonitorSnapshot = field(default_factory=SignalBMonitorSnapshot)
    signal_day_high: SignalDayHighMonitorSnapshot = field(default_factory=SignalDayHighMonitorSnapshot)
    modules: list[DashboardModuleStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
