"""Tests for config loading and normalization."""

import tempfile

import pytest

from tw_signal_engine.config.load_legacy_ini import load_legacy_ini
from tw_signal_engine.config.normalize_strategy_config import normalize_strategy_config


class TestLoadLegacyIni:
    def test_basic_parsing(self):
        content = "[SignalA]\nenabled=1\nvwapNearRatio=1.005\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write(content)
            f.flush()
            result = load_legacy_ini(f.name)
        assert "SignalA" in result
        assert result["SignalA"]["enabled"] == "1"
        assert result["SignalA"]["vwapNearRatio"] == "1.005"

    def test_preserves_case(self):
        content = "[Order]\npositionCash=10000000\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write(content)
            f.flush()
            result = load_legacy_ini(f.name)
        assert "positionCash" in result["Order"]

    def test_missing_file(self):
        result = load_legacy_ini("/nonexistent/path.cfg")
        assert result == {}


class TestNormalizeStrategyConfig:
    def test_defaults(self):
        config = normalize_strategy_config({})
        assert config.strategy.trade_mode == "long"
        assert config.signal_a.enabled is False
        assert config.signal_a_short.enabled is False
        assert config.signal_a.short_vwap_near_ratio == 0.993
        assert config.signal_a.short_pre_condition_vwap_ratio == 1.007
        assert config.signal_a_short.vwap_near_ratio == 0.993
        assert config.signal_a_short.pre_condition_vwap_ratio == 1.007
        assert config.signal_b.enabled is False
        assert config.execution.position_cash == 10_000_000.0

    def test_signal_a_enabled(self):
        raw = {"SignalA": {"enabled": "true", "vwap_near_ratio": "1.008"}}
        config = normalize_strategy_config(raw)
        assert config.signal_a.enabled is True
        assert config.signal_a.vwap_near_ratio == 1.008

    def test_signal_a_short_enabled(self):
        raw = {"SignalAShort": {"enabled": "true", "vwap_near_ratio": "0.991"}}
        config = normalize_strategy_config(raw)
        assert config.signal_a_short.enabled is True
        assert config.signal_a_short.vwap_near_ratio == 0.991

    def test_execution_config(self):
        raw = {"Order": {"position_cash": "5000000", "stop_loss_ratio_a": "0.995"}}
        config = normalize_strategy_config(raw)
        assert config.execution.position_cash == 5_000_000.0
        assert config.execution.stop_loss_ratio_a == 0.995

    def test_trade_mode_short(self):
        raw = {"Strategy": {"trade_mode": "short"}}
        config = normalize_strategy_config(raw)
        assert config.strategy.trade_mode == "short"

    def test_invalid_trade_mode_raises(self):
        raw = {"Strategy": {"trade_mode": "invalid"}}
        try:
            normalize_strategy_config(raw)
        except ValueError as exc:
            assert "trade_mode" in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid trade_mode")

    def test_take_profit_splits_must_be_positive(self):
        raw = {"Order": {"take_profit_splits": "0"}}
        with pytest.raises(ValueError, match="take_profit_splits"):
            normalize_strategy_config(raw)

    def test_reserve_limit_up_splits_must_be_non_negative(self):
        raw = {"Order": {"take_profit_splits": "2", "reserve_limit_up_splits": "-1"}}
        with pytest.raises(ValueError, match="reserve_limit_up_splits"):
            normalize_strategy_config(raw)
