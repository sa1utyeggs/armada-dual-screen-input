"""Gate touch intents on an armed session, fresh frames and a live input target."""
from __future__ import annotations

from ei_input import InputUnavailable
from mirror_capture import CapturedFrame
from mirror_geometry import MirrorTransform, Rect
from mirrored_touch import MirroredTouch


class MirrorSession:
    def __init__(self, sender) -> None:
        self.sender = sender
        self.frame: CapturedFrame | None = None
        self.transform: MirrorTransform | None = None
        self.gesture: MirroredTouch | None = None
        self.live = False
        self.armed = False
        self.failed = False
        self.reason = 'waiting_frame'
        self.last_error: str | None = None
        self.cached_frame_current = False
        # Aggregate delivery counts only: no positions or input contents.
        self.delivered = {'down': 0, 'move': 0, 'up': 0, 'cancel': 0, 'wheel': 0}

    def update(self, frame: CapturedFrame | None, viewport: Rect, now: float,
               *, live: bool, cached_frame_current: bool = False) -> None:
        self.frame, self.live = frame, live
        self.cached_frame_current = cached_frame_current
        if frame is not None:
            transform = MirrorTransform.fit(frame.width, frame.height, viewport)
            if transform != self.transform:
                self.pause(now)
                self.transform = transform
                if self.gesture is None:
                    self.gesture = MirroredTouch(transform)
                else:
                    self.gesture.set_transform(transform, now)
        self.tick(now)

    def _available(self, now: float) -> bool:
        if not self.live or self.frame is None:
            self.reason = 'waiting_frame'
            return False
        if not self.frame.fresh(now) and not self.cached_frame_current:
            self.reason = 'stale_frame'
            return False
        if self.failed:
            self.reason = 'input_unavailable'
            return False
        try:
            self.sender.poll()
            if self.sender.ready:
                return True
        except (InputUnavailable, OSError) as error:
            self.failed = True
            self.last_error = str(error)
            self.sender.close()
        self.reason = 'input_unavailable'
        return False

    def arm(self, now: float) -> bool:
        if self.gesture is None or not self._available(now):
            return False
        self.gesture.cancel(now)
        self.armed = True
        self.reason = 'active'
        return True

    def pause(self, now: float, *, reason: str = 'paused') -> None:
        self.armed = False
        if self.gesture is not None:
            self.gesture.cancel(now)
        try:
            self.sender.release_all()
        except (InputUnavailable, OSError):
            self.failed = True
            self.sender.close()
        self.reason = reason

    def _deliver(self, events, now: float, previous: str | None = None) -> None:
        try:
            for event in events:
                self.sender.send(event)
                self.delivered[event.kind] += 1
            if previous in ('scroll-pending', 'scrolling') and self.gesture.state not in (
                    'scroll-pending', 'scrolling'):
                self.sender.release_all()  # cancel wheel continuation
        except (InputUnavailable, OSError, ValueError) as error:
            self.last_error = str(error)
            self.pause(now, reason='input_unavailable')

    def tick(self, now: float) -> None:
        if not self._available(now):
            reason = self.reason
            if self.armed:
                self.pause(now, reason=reason)
            return
        if self.armed and self.gesture is not None:
            self._deliver(self.gesture.tick(now), now)

    def touch(self, phase: str, tid: int, now: float, x: float = 0, y: float = 0) -> None:
        if not self.armed or self.gesture is None:
            return
        if not self._available(now):
            self.pause(now, reason=self.reason)
            return
        previous = self.gesture.state
        if phase == 'begin':
            events = self.gesture.begin(tid, x, y, now)
        elif phase == 'move':
            events = self.gesture.move(tid, x, y, now)
        elif phase == 'end':
            events = self.gesture.end(tid, now)
        elif phase == 'cancel':
            self.pause(now)
            return
        else:
            raise ValueError('unknown touch phase')
        self._deliver(events, now, previous)
