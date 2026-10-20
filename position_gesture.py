"""Relative aiming with one finger, one native contact gated by a second.

No mouse hover, wheel conversion, inertia, image capture, or delayed chord.
Existing fingers are never promoted to another role. A new begin may re-aim
after the old aim ended; a fresh second begin is still needed to touch.
"""
from __future__ import annotations

import math

from touch_intent import TouchIntent
from position_motion import PositionMotion


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
        self.motion = PositionMotion(min(pad.width, pad.height))

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
        if self.blocked:
            # The aim finger ended first. Orphan contacts must never be
            # promoted, but a NEW begin may start a fresh, input-free aim.
            # This also avoids deadlock if an orphan's END was not delivered.
            self.aim, self.confirm, self.blocked = tid, None, False
            self.motion.reset((x, y))
            return ()
        if self.aim is None:
            self.aim = tid
            self.motion.reset((x, y))
        elif self.confirm is None and not self.held:
            self.confirm, self.held = tid, True
            return (TouchIntent('down', self.point, contact_id=self.CONTACT),)
        return ()

    def move(self, tid, x, y, now, *, motion_interval=None):
        self._point(x, y)
        if not math.isfinite(now):
            raise ValueError('invalid time')
        previous = self.contacts.get(tid)
        if previous is None:
            return ()
        self.contacts[tid] = (x, y)
        if self.blocked or tid != self.aim:
            return ()
        delta = self.motion.delta((x, y), motion_interval)
        if delta is None:
            return ()
        self.point = self._point(
            self.point[0] + delta[0]/self.pad.width*self.sensitivity,
            self.point[1] + delta[1]/self.pad.height*self.sensitivity)
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
                self.motion.reset()
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
        self.motion.reset()
        return events

    def center(self, now):
        events = self.cancel(now)
        self.point = (.5, .5)
        return events
