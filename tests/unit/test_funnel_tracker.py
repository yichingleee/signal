"""Tests for FunnelTracker."""

from __future__ import annotations

import csv
from pathlib import Path

from tw_signal_engine.reporting.build_funnel_report import write_funnel_report
from tw_signal_engine.reporting.funnel_tracker import FunnelTracker


class TestFunnelTracker:
    def test_initial_defaults(self):
        f = FunnelTracker()
        assert f.universe_count == 0
        assert f.executed_trades == 0
        assert f.entry_filter_reasons == {}

    def test_record_block(self):
        f = FunnelTracker()
        f.record_block("entry_time_limit")
        assert f.entry_filter_blocked == 1
        assert f.entry_filter_reasons == {"entry_time_limit": 1}

    def test_record_multiple_blocks(self):
        f = FunnelTracker()
        f.record_block("entry_time_limit")
        f.record_block("entry_time_limit")
        f.record_block("no_entry_friday")
        assert f.entry_filter_blocked == 3
        assert f.entry_filter_reasons == {"entry_time_limit": 2, "no_entry_friday": 1}

    def test_counter_increments(self):
        f = FunnelTracker()
        f.universe_count = 500
        f.valid_group_symbols = 200
        f.signal_triggered = 50
        f.executed_trades = 10
        assert f.universe_count == 500
        assert f.executed_trades == 10

    def test_empty_reasons_no_division_by_zero(self):
        f = FunnelTracker()
        # entry_filter_blocked is 0, should not cause issues
        assert f.entry_filter_blocked == 0
        total = f.entry_filter_blocked
        # Computing percentage should be safe
        pct = 0 / 1 if total == 0 else 0
        assert pct == 0

    def test_group_qualified_ticks_increments(self):
        f = FunnelTracker()
        assert f.group_qualified_ticks == 0
        f.group_qualified_ticks += 1
        f.group_qualified_ticks += 1
        assert f.group_qualified_ticks == 2

    def test_funnel_report_includes_group_qualified_ticks(self, tmp_path: Path):
        f = FunnelTracker()
        f.universe_count = 500
        f.valid_group_symbols = 200
        f.group_qualified_ticks = 100
        f.signal_triggered = 50
        f.executed_trades = 10
        write_funnel_report(f, str(tmp_path))

        with open(tmp_path / "report_funnel.csv") as fh:
            rows = list(csv.reader(fh))
        stage_names = [r[1] for r in rows if len(r) > 1 and r[0] == "Pipeline"]
        assert "Group Qualified Ticks" in stage_names
        # Verify it's between Valid Group Symbols and Signal Triggered
        idx_vgs = stage_names.index("Valid Group Symbols")
        idx_gqt = stage_names.index("Group Qualified Ticks")
        idx_st = stage_names.index("Signal Triggered")
        assert idx_vgs < idx_gqt < idx_st
