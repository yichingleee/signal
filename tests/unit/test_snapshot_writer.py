"""Tests for snapshot writer."""

from __future__ import annotations

from tw_signal_engine.reporting.snapshot_writer import (
    _minutes_to_hhmm,
    _time_str_to_hhmmss,
    _time_str_to_minutes,
)


class TestTimeConversions:
    def test_time_str_to_minutes_0900(self):
        # 90000000000 = 09:00:00.000000
        assert _time_str_to_minutes(90000000000) == 540

    def test_time_str_to_minutes_1030(self):
        # 103000000000 = 10:30:00.000000
        assert _time_str_to_minutes(103000000000) == 630

    def test_time_str_to_minutes_1330(self):
        # 133000000000 = 13:30:00.000000
        assert _time_str_to_minutes(133000000000) == 810

    def test_minutes_to_hhmm(self):
        assert _minutes_to_hhmm(540) == "09:00"
        assert _minutes_to_hhmm(630) == "10:30"
        assert _minutes_to_hhmm(810) == "13:30"

    def test_time_str_to_hhmmss(self):
        assert _time_str_to_hhmmss(90000000000) == "09:00:00"
        assert _time_str_to_hhmmss(103015000000) == "10:30:15"
        assert _time_str_to_hhmmss(133000000000) == "13:30:00"
