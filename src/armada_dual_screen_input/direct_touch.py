"""Absolute, independently tracked native contacts; no mouse emulation or I/O."""
from __future__ import annotations

import math

from .touch_intent import TouchIntent

MAX_CONTACTS = 10


class DirectTouchGesture:
    def __init__(self, pad, *, max_contacts=MAX_CONTACTS):
        if type(max_contacts) is not int or not 1 <= max_contacts <= MAX_CONTACTS:
            raise ValueError('invalid contact capacity')
        self.pad, self.max_contacts = pad, max_contacts
        self.contacts = {}
        self.ignored = set()

    @property
    def held(self):
        return bool(self.contacts)

    @property
    def rings(self):
        return tuple((*point, True) for point in self.contacts.values())

    def _point(self, x, y, now):
        if not all(math.isfinite(value) for value in (x, y, now)):
            raise ValueError('finite touch coordinates and time required')
        return (min(1., max(0., (x-self.pad.x)/self.pad.width)),
                min(1., max(0., (y-self.pad.y)/self.pad.height)))

    def begin(self, tid, x, y, now):
        point = self._point(x, y, now)
        if tid in self.contacts or tid in self.ignored:
            raise ValueError('duplicate contact')
        if not self.pad.contains(x, y) or len(self.contacts) >= self.max_contacts:
            self.ignored.add(tid)
            return ()
        self.contacts[tid] = point
        return (TouchIntent('down', point, contact_id=tid),)

    def move(self, tid, x, y, now, *, motion_interval=None):
        point = self._point(x, y, now)
        if tid not in self.contacts:
            return ()
        if point == self.contacts[tid]:
            return ()
        self.contacts[tid] = point
        return (TouchIntent('move', point, contact_id=tid),)

    def end(self, tid, now):
        if not math.isfinite(now):
            raise ValueError('finite time required')
        self.ignored.discard(tid)
        point = self.contacts.pop(tid, None)
        return () if point is None else (TouchIntent('up', point, contact_id=tid),)

    def cancel(self, now):
        if not math.isfinite(now):
            raise ValueError('finite time required')
        events = tuple(TouchIntent('up', point, contact_id=tid)
                       for tid, point in self.contacts.items())
        self.contacts.clear()
        self.ignored.clear()
        return events
