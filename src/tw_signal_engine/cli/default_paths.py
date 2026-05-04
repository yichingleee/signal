"""Shared defaults for CLI paths."""

from __future__ import annotations

import os

DATA_DIR_ENV_VAR = "TW_SIGNAL_DATA_DIR"
DEFAULT_DATA_DIR = "./data/"
PARQUET_DATA_DIR_ENV_VAR = "TW_SIGNAL_PARQUET_DATA_DIR"
FILES_DIR_ENV_VAR = "TW_SIGNAL_FILES_DIR"
DEFAULT_FILES_DIR = "./files/"
GROUP_FILE_ENV_VAR = "TW_SIGNAL_GROUP_FILE"
DEFAULT_GROUP_FILE = "./files/group.csv"


def default_data_dir() -> str:
    """Resolve data directory default from environment with local fallback."""
    return os.getenv(DATA_DIR_ENV_VAR, DEFAULT_DATA_DIR)


def data_dir_help() -> str:
    """CLI help text for data directory behavior."""
    return f"Data directory (default: ${DATA_DIR_ENV_VAR} or {DEFAULT_DATA_DIR})"


def default_parquet_data_dir() -> str:
    """Resolve parquet data directory default from environment with local fallback."""
    return os.getenv(PARQUET_DATA_DIR_ENV_VAR, DEFAULT_DATA_DIR)


def resolve_replay_data_dir(data_source: str, data_dir: str | None) -> str:
    """Resolve replay data dir for the selected source, preserving env defaults."""
    if data_dir is not None:
        return data_dir
    if data_source == "parquet":
        return default_parquet_data_dir()
    return default_data_dir()


def replay_data_dir_help() -> str:
    """CLI help text for replay data directory behavior across data sources."""
    return (
        "Data directory. Default: "
        f"text=${DATA_DIR_ENV_VAR} or {DEFAULT_DATA_DIR}; "
        f"parquet=${PARQUET_DATA_DIR_ENV_VAR} or {DEFAULT_DATA_DIR}"
    )


def default_files_dir() -> str:
    """Resolve symbol-files directory default from environment with local fallback."""
    return os.getenv(FILES_DIR_ENV_VAR, DEFAULT_FILES_DIR)


def files_dir_help() -> str:
    """CLI help text for symbol-files directory behavior."""
    return f"Symbol files directory (default: ${FILES_DIR_ENV_VAR} or {DEFAULT_FILES_DIR})"


def default_group_file() -> str:
    """Resolve group membership file default from environment with local fallback."""
    return os.getenv(GROUP_FILE_ENV_VAR, DEFAULT_GROUP_FILE)


def group_file_help() -> str:
    """CLI help text for group file behavior."""
    return f"Group membership file (default: ${GROUP_FILE_ENV_VAR} or {DEFAULT_GROUP_FILE})"
