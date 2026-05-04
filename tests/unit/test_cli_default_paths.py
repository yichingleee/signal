"""Tests for CLI default path resolution."""

from __future__ import annotations

from tw_signal_engine.cli.default_paths import (
    DEFAULT_DATA_DIR,
    DEFAULT_FILES_DIR,
    DEFAULT_GROUP_FILE,
    PARQUET_DATA_DIR_ENV_VAR,
    default_data_dir,
    default_files_dir,
    default_group_file,
    default_parquet_data_dir,
    resolve_replay_data_dir,
)


def test_default_data_dir_falls_back_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("TW_SIGNAL_DATA_DIR", raising=False)
    assert default_data_dir() == DEFAULT_DATA_DIR


def test_default_data_dir_uses_env_override(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/tick-data"
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", custom)
    assert default_data_dir() == custom


def test_default_parquet_data_dir_falls_back_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv(PARQUET_DATA_DIR_ENV_VAR, raising=False)
    assert default_parquet_data_dir() == DEFAULT_DATA_DIR


def test_default_parquet_data_dir_uses_env_override(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/parquet-ticks"
    monkeypatch.setenv(PARQUET_DATA_DIR_ENV_VAR, custom)
    assert default_parquet_data_dir() == custom


def test_resolve_replay_data_dir_prefers_explicit_arg(monkeypatch) -> None:
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", "/tmp/text-env")
    monkeypatch.setenv(PARQUET_DATA_DIR_ENV_VAR, "/tmp/parquet-env")
    assert resolve_replay_data_dir("text", "/tmp/explicit") == "/tmp/explicit"
    assert resolve_replay_data_dir("parquet", "/tmp/explicit") == "/tmp/explicit"


def test_resolve_replay_data_dir_uses_text_env(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/text-ticks"
    monkeypatch.setenv("TW_SIGNAL_DATA_DIR", custom)
    assert resolve_replay_data_dir("text", None) == custom


def test_resolve_replay_data_dir_uses_parquet_env(monkeypatch) -> None:
    custom = "/Users/liyijing/Projects/Trading/market-data/parquet-ticks"
    monkeypatch.setenv(PARQUET_DATA_DIR_ENV_VAR, custom)
    assert resolve_replay_data_dir("parquet", None) == custom


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
