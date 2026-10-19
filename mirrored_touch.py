"""Single-contact absolute touch and two-finger wheel intent state machine.

This module performs no I/O and creates no virtual devices. Call it from one
event-loop thread. Consumers must schedule tick() at deadline even if a finger
is stationary, and gate all intents on a live capture and verified target.
Positions are normalized in captured-source coordinates; wheel units use 120
per notch and retain fractions until the actual device backend accumulates them.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from mirror_geometry import MirrorTransform, finite


@dataclass(frozen=True)
class TouchIntent:
    kind: Literal["down", "move", "up", "cancel", "wheel"]
    position: tuple[float, float]
    wheel: tuple[float, float] = (0.0, 0.0)


class MirroredTouch:
    """Delay initial press briefly so a two-finger gesture cannot click first."""

    def __init__(self, transform: MirrorTransform, *, chord_delay: float = 0.06,
                 scroll_threshold: float = 4.0, wheel_notches: float = 3.0,
                 natural_scroll: bool = False) -> None:
        finite(chord_delay, scroll_threshold, wheel_notches)
        if not 0 <= chord_delay <= 0.25 or scroll_threshold < 0 or wheel_notches <= 0:
            raise ValueError("invalid gesture settings")
        self.transform = transform
        self.chord_delay = chord_delay
        self.scroll_threshold = scroll_threshold
        self.wheel_notches = wheel_notches  # per image short side, independent of resolution
        self.natural_scroll = bool(natural_scroll)
        self.enabled = True
        self.state = "idle"
        self._contacts: dict[int, tuple[float, float]] = {}
        self._primary: int | None = None
        self._origin = self._last = (0.0, 0.0)
        self._scroll_origin = self._scroll_last = (0.0, 0.0)
        self._started = self._now = 0.0
        self._pressed: tuple[float, float] | None = None
        self._events: list[TouchIntent] = []

    @property
    def deadline(self) -> float | None:
        return self._started + self.chord_delay if self.state == "pending" else None

    def _time(self, now: float) -> None:
        finite(now)
        self._now = max(self._now, now)

    def _take(self) -> tuple[TouchIntent, ...]:
        result = tuple(self._events)
        self._events.clear()
        return result

    def _position(self, point: tuple[float, float]) -> tuple[float, float]:
        result = self.transform.to_source(*point, clamp=True)
        assert result is not None
        return result

    def _press(self) -> None:
        self._pressed = self._position(self._origin)
        self._events.append(TouchIntent("down", self._pressed))
        self.state = "single"
        if self._last != self._origin:
            self._pressed = self._position(self._last)
            self._events.append(TouchIntent("move", self._pressed))

    def _expire(self) -> None:
        if self.deadline is not None and self._now >= self.deadline:
            self._press()

    def tick(self, now: float) -> tuple[TouchIntent, ...]:
        self._time(now)
        self._expire()
        return self._take()

    def begin(self, tid: int, x: float, y: float, now: float) -> tuple[TouchIntent, ...]:
        finite(x, y, now)
        if tid in self._contacts:
            raise ValueError("touch ID is already active")
        self._time(now)
        self._expire()
        self._contacts[tid] = (x, y)
        inside = self.transform.to_source(x, y) is not None
        if not self.enabled:
            self.state = "blocked"
        elif self.state == "idle":
            if inside:
                self._primary = tid
                self._origin = self._last = (x, y)
                self._started = self._now
                self.state = "pending"
                self._expire()
            else:
                self.state = "blocked"
        elif self.state == "pending":
            if inside and len(self._contacts) == 2:
                self._scroll_origin = self._scroll_last = self._centroid()
                self.state = "scroll-pending"
            else:
                self.state = "blocked"
        elif self.state in ("scroll-pending", "scrolling"):
            # A third finger cancels scrolling; all contacts must lift to rearm.
            self.state = "blocked"
        # During a committed drag, extra fingers never release or change it.
        return self._take()

    def _centroid(self) -> tuple[float, float]:
        points = tuple(self._contacts.values())
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))

    def _scroll(self) -> None:
        center = self._centroid()
        if self.state == "scroll-pending":
            dx = center[0] - self._scroll_origin[0]
            dy = center[1] - self._scroll_origin[1]
            distance = math.hypot(dx, dy)
            if distance <= self.scroll_threshold:
                return
            # Emit only travel beyond the threshold, avoiding a jump on entry.
            excess = (distance - self.scroll_threshold) / distance
            dx, dy = dx * excess, dy * excess
            self.state = "scrolling"
        else:
            dx = center[0] - self._scroll_last[0]
            dy = center[1] - self._scroll_last[1]
        self._scroll_last = center
        gain = 120.0 * self.wheel_notches / min(self.transform.image.width,
                                               self.transform.image.height)
        sign = -1 if self.natural_scroll else 1
        wheel = (dx * gain * sign, -dy * gain * sign)
        if wheel != (0.0, 0.0):
            self._events.append(TouchIntent("wheel", self._position(center), wheel))

    def move(self, tid: int, x: float, y: float, now: float) -> tuple[TouchIntent, ...]:
        finite(x, y, now)
        self._time(now)
        self._expire()
        if tid not in self._contacts:
            return self._take()
        self._contacts[tid] = (x, y)
        if self.state in ("pending", "single") and tid == self._primary:
            self._last = (x, y)
            if self.state == "single":
                point = self._position(self._last)
                if point != self._pressed:
                    self._pressed = point
                    self._events.append(TouchIntent("move", point))
        elif self.state in ("scroll-pending", "scrolling"):
            self._scroll()
        return self._take()

    def end(self, tid: int, now: float) -> tuple[TouchIntent, ...]:
        self._time(now)
        self._expire()
        if tid not in self._contacts:
            return self._take()
        if tid == self._primary and self.state in ("pending", "single"):
            if self.state == "pending":
                self._press()
            assert self._pressed is not None
            self._events.append(TouchIntent("up", self._pressed))
            self._pressed = None
            self.state = "blocked"
        elif self.state in ("scroll-pending", "scrolling"):
            self.state = "blocked"
        del self._contacts[tid]
        if not self._contacts:
            self.state = "idle"
            self._primary = None
        return self._take()

    def cancel(self, now: float) -> tuple[TouchIntent, ...]:
        """Discard pending taps; tell the backend to release existing input.

        A native backend should cancel. A mouse compatibility backend can only
        release its button, which cannot undo an already-started game action.
        The caller must also cancel its toolkit sequences and pending timer.
        """
        self._time(now)  # Do not expire a pending press while cancelling it.
        if self._pressed is not None:
            self._events.append(TouchIntent("cancel", self._pressed))
        self._pressed = None
        self._contacts.clear()
        self._primary = None
        self.state = "idle"
        return self._take()

    def set_transform(self, transform: MirrorTransform, now: float) -> tuple[TouchIntent, ...]:
        events = self.cancel(now)
        self.transform = transform
        return events

    def set_enabled(self, enabled: bool, now: float) -> tuple[TouchIntent, ...]:
        events = self.cancel(now)
        self.enabled = bool(enabled)
        return events
