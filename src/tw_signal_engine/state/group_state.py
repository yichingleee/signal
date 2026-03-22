"""Group ranking state structures."""

from __future__ import annotations


class GroupRank:
    """Rank items by a float score, maintained in descending order.

    Uses a simple dict + sorted iteration approach matching the C++ map<double, string, greater>.
    Note: C++ version has a bug where identical scores overwrite each other in the map.
    We replicate this behavior for parity.

    Optimization: caches the sorted view and invalidates on mutation.
    """

    def __init__(self) -> None:
        self._gain_to_name: dict[float, str] = {}  # gain -> name (descending)
        self._name_to_gain: dict[str, float] = {}
        self._sorted_cache: list[tuple[float, str]] | None = None

    def _invalidate(self) -> None:
        self._sorted_cache = None

    def _get_sorted(self) -> list[tuple[float, str]]:
        if self._sorted_cache is None:
            self._sorted_cache = sorted(self._gain_to_name.items(), reverse=True)
        return self._sorted_cache

    def on_tick(self, name: str, gain: float) -> None:
        old_gain = self._name_to_gain.get(name)
        if old_gain is not None:
            if old_gain in self._gain_to_name and self._gain_to_name[old_gain] == name:
                del self._gain_to_name[old_gain]
        self._name_to_gain[name] = gain
        self._gain_to_name[gain] = name
        self._invalidate()

    def erase(self, name: str) -> None:
        gain = self._name_to_gain.get(name)
        if gain is not None:
            if gain in self._gain_to_name and self._gain_to_name[gain] == name:
                del self._gain_to_name[gain]
            del self._name_to_gain[name]
            self._invalidate()

    def get_rank(self, name: str) -> int:
        """1-based rank, -1 if not found."""
        if name not in self._name_to_gain:
            return -1
        rank = 1
        for _, n in self._get_sorted():
            if n == name:
                return rank
            rank += 1
        return -1

    def is_top_n(self, name: str, n: int) -> bool:
        if name not in self._name_to_gain:
            return False
        count = 0
        for _, nm in self._get_sorted():
            if nm == name:
                return True
            count += 1
            if count >= n:
                return False
        return False

    def iter_ranked(self) -> list[tuple[float, str]]:
        """Return sorted list of (gain, name) in descending order."""
        return self._get_sorted()
