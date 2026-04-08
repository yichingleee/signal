"""Day-bar loader for the parquet market-data root.

The parquet tick-data feed omits all ``00*`` symbols (notably ``0050``), so the
replay's :class:`MarketGate` cannot observe its open or 09:15 prints. This
helper backfills 0050's open price from the sibling ``day-ohlcv-and-chip``
parquet root so the gate's open-drop and rally checks still fire.

Layout assumed::

    market-data/
      tick-data/
      day-ohlcv-and-chip/
        day_adj_<startYYYYMMDD>_<endYYYYMMDD>/
          open.parquet
          close.parquet
          high.parquet
          ...

Each ``open.parquet`` file is a wide table indexed by ``date`` (a pandas
``DatetimeIndex``) with one column per symbol.
"""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow.parquet as pq

_DATASET_RE = re.compile(r"day_adj_(\d{8})_(\d{8})$")


def _list_day_bar_datasets(day_bar_root: Path) -> list[tuple[str, str, Path]]:
    """Return ``(start, end, path)`` for every dataset under ``day_bar_root``.

    Sorted by ``end`` descending so the freshest dataset is first.
    """
    if not day_bar_root.exists():
        return []
    out: list[tuple[str, str, Path]] = []
    for entry in day_bar_root.iterdir():
        if not entry.is_dir():
            continue
        m = _DATASET_RE.match(entry.name)
        if m is None:
            continue
        out.append((m.group(1), m.group(2), entry))
    out.sort(key=lambda triple: triple[1], reverse=True)
    return out


def _pick_dataset_for_date(day_bar_root: Path, date: str) -> Path | None:
    """Pick the freshest dataset whose date range covers ``date``."""
    for start, end, path in _list_day_bar_datasets(day_bar_root):
        if start <= date <= end:
            return path
    return None


def load_0050_open(date: str, day_bar_root: Path | str) -> float | None:
    """Return ``0050``'s open price for ``date`` (YYYYMMDD), or ``None``.

    Returns ``None`` if no dataset covers the date or 0050 is missing from the
    column list.
    """
    root = Path(day_bar_root)
    dataset = _pick_dataset_for_date(root, date)
    if dataset is None:
        return None
    open_path = dataset / "open.parquet"
    if not open_path.exists():
        return None
    # The parquet file's pandas metadata declares ``date`` as the index
    # column, so projecting just ``["0050"]`` would lose the row labels and
    # leave a default RangeIndex. Reading ``date`` alongside lets pandas
    # reconstitute the DatetimeIndex on its own.
    table = pq.read_table(str(open_path), columns=["date", "0050"])
    df = table.to_pandas()
    df.index = df.index.strftime("%Y%m%d")
    if date not in df.index:
        return None
    val = df.loc[date, "0050"]
    if val is None or (isinstance(val, float) and val != val):  # NaN check
        return None
    return float(val)
