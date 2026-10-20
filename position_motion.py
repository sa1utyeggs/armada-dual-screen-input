"""Quarantine discontinuous positioning samples without replaying their jump.

Coordinates stay local to the gesture. No device access, timer or input output.
Ordinary samples are immediate; only an exceptional step waits for evidence
from the next sample. A confirmed new baseline never repays unknown travel.
"""
from __future__ import annotations

import math


class PositionMotion:
    def __init__(self, extent):
        if not math.isfinite(extent) or extent <= 0:
            raise ValueError('positive finite pad extent required')
        self.floor = extent * .18
        self.near = self.floor / 3
        self.reset()

    def reset(self, point=None):
        self.point = point
        self.speed = 0.
        self.pending = None

    def delta(self, point, interval=None):
        if interval is not None and (not math.isfinite(interval) or interval < 0):
            raise ValueError('invalid motion interval')
        previous = self.point
        self.point = point
        if previous is None:
            return None
        delta = (point[0]-previous[0], point[1]-previous[1])
        # Unsourced development calls cannot establish a sampling rate.
        if interval is None:
            self.speed, self.pending = 0., None
            return delta
        if self.pending is not None:
            trusted, candidate = self.pending
            if min(math.dist(point, trusted), math.dist(point, candidate)) <= self.near:
                # Either an isolated spike returned, or a reused contact has
                # settled elsewhere. Re-anchor; never apply the large step.
                self.speed, self.pending = 0., None
                return None
            first = (candidate[0]-trusted[0], candidate[1]-trusted[1])
            second = (point[0]-candidate[0], point[1]-candidate[1])
            a, b = math.hypot(*first), math.hypot(*second)
            cosine = sum(x*y for x, y in zip(first, second))/(a*b) if a*b else -1
            if .25*a <= b <= 2*a and cosine >= .9:
                # Coherent fast motion may continue immediately. Discard
                # only the ambiguous first leap, not the whole fast stroke.
                self.pending = None
                self.speed = b/interval if interval else 0.
                return second
            self.pending = (trusted, point)
            return None
        distance = math.hypot(*delta)
        recent_speed = self.speed if 0 < interval <= .12 else 0.
        limit = max(self.floor, 2.5*recent_speed*min(interval, .05))
        if distance > limit:
            self.pending = (previous, point)
            return None
        self.speed = distance/interval if interval else 0.
        return delta
