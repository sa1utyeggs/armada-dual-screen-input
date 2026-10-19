"""Shared geometry for rendering a mirror and mapping its touch coordinates.

Coordinates are toolkit allocation units. The source is the captured output,
including any game letterboxing; no model-specific resolution is assumed.
"""
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


@dataclass(frozen=True)
class MirrorTransform:
    source_width: int
    source_height: int
    image: Rect
    rotation: int = 0  # clockwise image rotation, applied by the renderer too

    def __post_init__(self) -> None:
        for size in (self.source_width, self.source_height):
            if type(size) is not int or size <= 0:
                raise ValueError("source dimensions must be positive integers")
        if type(self.rotation) is not int or self.rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270")

    @classmethod
    def fit(cls, width: int, height: int, viewport: Rect,
            rotation: int = 0) -> MirrorTransform:
        # Validate before division or rotation-dependent arithmetic.
        cls(width, height, viewport, rotation)
        shown_w, shown_h = (height, width) if rotation in (90, 270) else (width, height)
        scale = min(viewport.width / shown_w, viewport.height / shown_h)
        w, h = shown_w * scale, shown_h * scale
        return cls(width, height, Rect(viewport.x + (viewport.width - w) / 2,
                                      viewport.y + (viewport.height - h) / 2,
                                      w, h), rotation)

    def to_source(self, x: float, y: float, *, clamp: bool = False
                  ) -> tuple[float, float] | None:
        """Return normalized source coordinates; reject new touches in margins."""
        finite(x, y)
        if not clamp and not self.image.contains(x, y):
            return None
        u = min(1.0, max(0.0, (x - self.image.x) / self.image.width))
        v = min(1.0, max(0.0, (y - self.image.y) / self.image.height))
        return {
            0: (u, v), 90: (v, 1 - u),
            180: (1 - u, 1 - v), 270: (1 - v, u),
        }[self.rotation]

    def to_view(self, u: float, v: float) -> tuple[float, float]:
        """Place a source-space marker using the exact inverse touch mapping."""
        finite(u, v)
        if not 0 <= u <= 1 or not 0 <= v <= 1:
            raise ValueError("normalized source coordinates must be in [0, 1]")
        u, v = {
            0: (u, v), 90: (1 - v, u),
            180: (1 - u, 1 - v), 270: (v, 1 - u),
        }[self.rotation]
        return self.image.x + u * self.image.width, self.image.y + v * self.image.height

    def to_pixel(self, u: float, v: float) -> tuple[int, int]:
        finite(u, v)
        if not 0 <= u <= 1 or not 0 <= v <= 1:
            raise ValueError("normalized source coordinates must be in [0, 1]")
        return round(u * (self.source_width - 1)), round(v * (self.source_height - 1))
