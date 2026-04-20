"""Tests for CLI default path resolution."""

from __future__ import annotations

from tw_signal_engine.cli.default_paths import (
    DEFAULT_DATA_DIR,
    DEFAULT_FILES_DIR,
    DEFAULT_GROUP_FILE,
    default_data_dir,
    default_files_dir,
    default_group_file,
)


def test_default_data_dir_falls_back_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("TW_SIGNAL_DATA_DIR", raising=False)
    assert default_data_dir() == DEFAULT_DATA_DIR


def test_default_data_dir_uses_env_override(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/tick-data"
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", custom)
    assert default_data_dir() == custom


def test_default_files_dir_falls_back_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("TW_SIGNAL_FILES_DIR", raising=False)
    assert default_files_dir() == DEFAULT_FILES_DIR


def test_default_files_dir_uses_env_override(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/symbols"
    monkeypatch.setenv("TW_SIGNAL_FILES_DIR", custom)
    assert default_files_dir() == custom


def test_default_group_file_falls_back_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("TW_SIGNAL_GROUP_FILE", raising=False)
    assert default_group_file() == DEFAULT_GROUP_FILE


def test_default_group_file_uses_env_override(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/group/group-ver20260408.csv"
    monkeypatch.setenv("TW_SIGNAL_GROUP_FILE", custom)
    assert default_group_file() == custom
