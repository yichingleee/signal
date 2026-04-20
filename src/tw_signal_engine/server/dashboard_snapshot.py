"""Dashboard snapshot data models for the V1 dashboard.

These dataclasses define the canonical schema consumed by all dashboard API
endpoints.  Both live mode (via LiveState) and replay mode (via ReplayManager)
produce the same structures so the frontend is mode-agnostic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
