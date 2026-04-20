"""Shared defaults for CLI paths."""

from __future__ import annotations

import os

DATA_DIR_ENV_VAR = "TW_SIGNAL_DATA_DIR"
DEFAULT_DATA_DIR = "./data/"
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
