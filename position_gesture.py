"""Relative aiming with one finger, one native contact gated by a second.

No mouse hover, wheel conversion, inertia, image capture, or delayed chord.
Finger roles never swap while either member of the current group is down.
"""
from __future__ import annotations

import math

from mirrored_touch import TouchIntent


class PositionGesture:
    CONTACT = 0

    def __init__(self, pad, *, point=(.5, .5), sensitivity=1.0):
        if not math.isfinite(sensitivity) or not .1 <= sensitivity <= 4:
            raise ValueError('invalid positioning sensitivity')
        if pad.width <= 0 or pad.height <= 0:
            raise ValueError('a positive pad area is required')
        self.pad, self.sensitivity = pad, sensitivity
        self.point = self._point(*point)
        self.contacts = {}
        self.aim = self.confirm = None
        self.held = self.blocked = False

    @staticmethod
    def _point(x, y):
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError('finite coordinates required')
        return min(1., max(0., x)), min(1., max(0., y))

    def begin(self, tid, x, y, now):
        self._point(x, y)
        if not math.isfinite(now) or tid in self.contacts:
            raise ValueError('invalid or duplicate contact')
        self.contacts[tid] = (x, y)
        if self.blocked or len(self.contacts) > 2:
            return ()
        if self.aim is None:
            self.aim = tid
        elif self.confirm is None and not self.held:
            self.confirm, self.held = tid, True
            return (TouchIntent('down', self.point, contact_id=self.CONTACT),)
        return ()

    def move(self, tid, x, y, now):
        self._point(x, y)
        if not math.isfinite(now):
            raise ValueError('invalid time')
        previous = self.contacts.get(tid)
        if previous is None:
            return ()
        self.contacts[tid] = (x, y)
        if self.blocked or tid != self.aim:
            return ()
        self.point = self._point(
            self.point[0] + (x-previous[0])/self.pad.width*self.sensitivity,
            self.point[1] + (y-previous[1])/self.pad.height*self.sensitivity)
        if self.held:
            return (TouchIntent('move', self.point, contact_id=self.CONTACT),)
        return ()

    def end(self, tid, now):
        if not math.isfinite(now):
            raise ValueError('invalid time')
        if tid not in self.contacts:
            return ()
        self.contacts.pop(tid)
        events = ()
        if tid in (self.aim, self.confirm):
            if self.held:
                events = (TouchIntent('up', self.point, contact_id=self.CONTACT),)
                self.held = False
            if tid == self.aim:
                self.aim = None
                # Do not promote the confirm finger (or a third finger).
                self.blocked = bool(self.contacts)
            if tid == self.confirm:
                self.confirm = None
        if not self.contacts:
            self.aim = self.confirm = None
            self.blocked = False
        return events

    def cancel(self, now):
        if not math.isfinite(now):
            raise ValueError('invalid time')
        events = ((TouchIntent('cancel', self.point, contact_id=self.CONTACT),)
                  if self.held else ())
        self.contacts.clear()
        self.aim = self.confirm = None
        self.held = self.blocked = False
        return events

    def center(self, now):
        events = self.cancel(now)
        self.point = (.5, .5)
        return events
