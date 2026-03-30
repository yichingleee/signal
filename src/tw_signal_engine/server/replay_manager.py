"""Parquet-backed time-travel replay manager."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]


class ReplayManager:
    """Loads Parquet snapshots and supports time-travel queries."""

    def __init__(self, date: str, snapshot_dir: str = "./cache/replay/") -> None:
        self.date = date
        self._snapshot_dir = snapshot_dir
        self._df: pd.DataFrame | None = None
        self._signals_df: pd.DataFrame | None = None
        self._current_idx: int = -1

    def load(self) -> bool:
        """Load Parquet files. Returns True if successful."""
        data_path = Path(self._snapshot_dir) / f"ReplayData_{self.date}.parquet"
        if not data_path.exists():
            return False
        self._df = pd.read_parquet(data_path)
        self._current_idx = 0

        signals_path = Path(self._snapshot_dir) / f"ReplaySignals_{self.date}.parquet"
        if signals_path.exists():
            self._signals_df = pd.read_parquet(signals_path)

        return True

    def is_ready(self) -> bool:
        return self._df is not None and len(self._df) > 0

    def get_time_range(self) -> dict[str, Any]:
        """Return available time range."""
        if self._df is None or len(self._df) == 0:
            return {"min_time": "", "max_time": "", "count": 0}
        return {
            "min_time": str(self._df.iloc[0]["time_str"]),
            "max_time": str(self._df.iloc[-1]["time_str"]),
            "count": len(self._df),
        }

    @staticmethod
    def _time_to_minutes(t: str) -> int:
        """Convert "HH:MM" or "H:MM" to minutes since midnight."""
        parts = t.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def jump_to_time(self, time_str: str) -> dict[str, Any] | None:
        """Jump to the nearest minute at or before the given time.

        Args:
            time_str: "HH:MM" format time string
        """
        if self._df is None or len(self._df) == 0:
            return None

        target_minutes = self._time_to_minutes(time_str)
        col_minutes = self._df["time_str"].map(self._time_to_minutes)
        mask = col_minutes <= target_minutes
        matching = self._df[mask]
        if matching.empty:
            return None

        row = matching.iloc[-1]
        self._current_idx = int(matching.index[-1])
        return self._row_to_dict(row)

    def get_current_snapshot(self) -> dict[str, Any] | None:
        """Return the current snapshot."""
        if self._df is None or self._current_idx < 0 or self._current_idx >= len(self._df):
            return None
        row = self._df.iloc[self._current_idx]
        return self._row_to_dict(row)

    def get_signals(self) -> list[dict[str, Any]]:
        """Return all signal records."""
        if self._signals_df is None or len(self._signals_df) == 0:
            return []
        return [
            {str(k): v for k, v in rec.items()}
            for rec in self._signals_df.to_dict(orient="records")
        ]

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DataFrame row to a response dict, parsing JSON fields."""
        result: dict[str, Any] = {}
        for col in row.index:
            val = row[col]
            if isinstance(val, str) and val.startswith(("[", "{")):
                try:
                    result[col] = json.loads(val)
                except json.JSONDecodeError:
                    result[col] = val
            else:
                # Convert numpy types to Python types
                if hasattr(val, "item"):
                    result[col] = val.item()
                else:
                    result[col] = val
        return result
