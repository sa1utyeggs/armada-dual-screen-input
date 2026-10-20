"""Finite operation-area geometry, independent of any screen capture."""
from __future__ import annotations

from dataclasses import dataclass
import math


def finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("coordinates must be finite")


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        finite(self.x, self.y, self.width, self.height)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle dimensions must be positive")

    def contains(self, x: float, y: float) -> bool:
        finite(x, y)
        return (self.x <= x <= self.x + self.width
                and self.y <= y <= self.y + self.height)
