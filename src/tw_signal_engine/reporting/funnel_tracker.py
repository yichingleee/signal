"""Decision funnel tracking for the replay pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FunnelTracker:
    """Tracks counts at each pipeline stage for funnel analysis."""

    universe_count: int = 0
    valid_group_symbols: int = 0
    group_qualified_ticks: int = 0
    signal_triggered: int = 0
    entry_filter_blocked: int = 0
    entry_filter_reasons: dict[str, int] = field(default_factory=dict)
    executed_trades: int = 0

    def record_block(self, reason: str) -> None:
        """Record a blocked entry with the given reason."""
        self.entry_filter_blocked += 1
        self.entry_filter_reasons[reason] = self.entry_filter_reasons.get(reason, 0) + 1
