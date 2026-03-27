"""Shared chart style constants and helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

# Color palette
WIN = "#2ecc71"
LOSS = "#e74c3c"
NEUTRAL = "#95a5a6"
PRIMARY = "#2c3e50"
ACCENT = "#3498db"

# Figure defaults
FIG_WIDTH = 12
FIG_HEIGHT = 6
DPI = 150


def new_figure(
    width: float = FIG_WIDTH,
    height: float = FIG_HEIGHT,
) -> tuple[Figure, Axes]:
    """Create a new figure with standard styling."""
    fig, ax = plt.subplots(figsize=(width, height), dpi=DPI)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig, ax


def new_figure_2axes(
    width: float = FIG_WIDTH,
    height: float = FIG_HEIGHT,
) -> tuple[Figure, Axes, Axes]:
    """Create figure with 2 vertically stacked subplots."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(width, height), dpi=DPI, sharex=True)
    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    return fig, ax1, ax2


def save_and_close(fig: Any, path: str) -> None:
    """Save figure to path and close."""
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"[Chart] {path}")


def marker_annotation_style() -> dict[str, Any]:
    """Shared annotation style for dense marker labeling."""
    return {
        "fontsize": 7,
        "bbox": {
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "#bdc3c7",
            "alpha": 0.9,
        },
    }
