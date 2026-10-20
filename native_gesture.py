"""Direct mirrored native contacts: no mouse chord delay or wheel conversion."""
from __future__ import annotations

from mirror_geometry import finite
from mirrored_touch import TouchIntent


class NativeMirroredTouch:
    def __init__(self, transform):
        self.transform = transform
        self.contacts = {}
        self.ignored = set()
        self.enabled = True

    @property
    def state(self):
        if self.contacts:
            return 'single' if len(self.contacts) == 1 else 'multi'
        return 'blocked' if self.ignored else 'idle'

    def tick(self, now):
        finite(now)
        return ()

    def begin(self, tid, x, y, now):
        finite(x, y, now)
        if tid in self.contacts or tid in self.ignored:
            raise ValueError('touch ID is already active')
        point = self.transform.to_source(x, y)
        if not self.enabled or point is None or len(self.contacts) >= 2:
            self.ignored.add(tid)
            return ()
        self.contacts[tid] = point
        return (TouchIntent('down', point, contact_id=tid),)

    def move(self, tid, x, y, now):
        finite(x, y, now)
        if tid not in self.contacts:
            return ()
        point = self.transform.to_source(x, y, clamp=True)
        if point == self.contacts[tid]:
            return ()
        self.contacts[tid] = point
        return (TouchIntent('move', point, contact_id=tid),)

    def end(self, tid, now):
        finite(now)
        self.ignored.discard(tid)
        point = self.contacts.pop(tid, None)
        return () if point is None else (TouchIntent('up', point, contact_id=tid),)

    def cancel(self, now):
        finite(now)
        events = tuple(TouchIntent('cancel', point, contact_id=tid)
                       for tid, point in self.contacts.items())
        self.contacts.clear()
        self.ignored.clear()
        return events

    def set_transform(self, transform, now):
        events = self.cancel(now)
        self.transform = transform
        return events

    def set_enabled(self, enabled, now):
        events = self.cancel(now)
        self.enabled = bool(enabled)
        return events
