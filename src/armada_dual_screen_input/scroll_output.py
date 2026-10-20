"""Scale this panel's wheel output before high-res/legacy event conversion."""
from __future__ import annotations

import math
from typing import Callable


def read_scroll_scale(value: object) -> float:
    """Keep existing installations unchanged unless a valid reduction is set."""
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    return scale if math.isfinite(scale) and 0.0 < scale <= 1.0 else 1.0


class ScaledScroll:
    def __init__(self, emit: Callable[[int, int], None], scale: float) -> None:
        self.emit = emit
        self.scale = read_scroll_scale(scale)
        self.rest_x = 0.0
        self.rest_y = 0.0

    def scroll(self, dx: int, dy: int) -> None:
        self.rest_x += dx * self.scale
        self.rest_y += dy * self.scale
        x, y = int(self.rest_x), int(self.rest_y)
        self.rest_x -= x
        self.rest_y -= y
        if x or y:
            # The original bridge derives both high-res and legacy events
            # from these same scaled units. No input device is opened here.
            self.emit(x, y)
