"""Continuous visual following; no prediction, device access or input output.

Each contact approaches its latest confirmed target with an 8ms time constant.
Advancing the old target before retargeting keeps the filter independent of
render frequency. A short, bounded tail ends exactly at the confirmed position.
"""
from __future__ import annotations

import math

from .marker_sample import MarkerSample


class MarkerMotion:
    TIME_CONSTANT = .008
    SETTLE_AFTER = .040
    MAX_SAMPLE_AGE = .100
    EPSILON_PIXELS = .20

    def __init__(self, canvas):
        if (len(canvas) != 2 or any(type(n) is not int or not 1 <= n <= 8192 for n in canvas)):
            raise ValueError('invalid marker canvas')
        self.canvas = tuple(canvas)
        self._points = {}
        self._targets = {}
        self._changed_at = {}
        self._order = ()
        self._mode = None
        self._at = self._received_at = self._source_at = None

    def _distance(self, a, b):
        return math.hypot((a[0]-b[0])*(self.canvas[0]-1),
                          (a[1]-b[1])*(self.canvas[1]-1))

    @property
    def rings(self):
        return tuple(self._points[tid] for tid in self._order)

    @property
    def mode(self):
        return self._mode or 'legacy'

    @property
    def animating(self):
        return any(self._points[tid] != self._targets[tid] for tid in self._order)

    def _advance(self, now):
        if not math.isfinite(now) or now < 0:
            raise ValueError('invalid visual time')
        if self._at is None:
            self._at = now
            return
        if now < self._at:
            self._points = dict(self._targets)
            self._at = now
            return
        alpha = -math.expm1(-(now-self._at)/self.TIME_CONSTANT)
        for tid in self._order:
            point, target = self._points[tid], self._targets[tid]
            if point == target:
                continue
            updated = (point[0]+alpha*(target[0]-point[0]),
                       point[1]+alpha*(target[1]-point[1]), target[2])
            if (now-self._changed_at[tid] >= self.SETTLE_AFTER
                    or self._distance(updated, target) <= self.EPSILON_PIXELS):
                updated = target
            self._points[tid] = updated
        self._at = now

    def accept(self, sample, now, *, force_snap=False):
        if not isinstance(sample, MarkerSample):
            raise ValueError('a decoded visual sample is required')
        if (sample.mode != 'legacy' and self._source_at is not None
                and sample.sampled_at < self._source_at):
            return False  # Never animate or replay a reordered sample.
        before = self.rings
        mode_changed = sample.mode != self._mode
        previous_at = self._at
        self._advance(now)
        snap = (force_snap or sample.snap or not sample.active or sample.mode != self._mode
                or previous_at is None or now < previous_at
                or self._received_at is None or now-self._received_at > self.MAX_SAMPLE_AGE
                or now-sample.sampled_at > self.MAX_SAMPLE_AGE or sample.sampled_at > now+.005)
        points, targets, changed_at = {}, {}, {}
        jump = math.hypot(*self.canvas)*.20
        for tid, target in zip(sample.ids, sample.rings):
            point = self._points.get(tid)
            old_target = self._targets.get(tid)
            if (snap or point is None or old_target[2] != target[2]
                    or self._distance(point, target) > jump):
                point = target
            points[tid], targets[tid] = point, target
            changed_at[tid] = (now if old_target != target else self._changed_at[tid])
        self._points, self._targets, self._changed_at = points, targets, changed_at
        self._order, self._mode = sample.ids, sample.mode
        self._received_at = now
        # A malformed future timestamp must not poison the ordering guard
        # and freeze all subsequent genuine samples.
        self._source_at = (sample.sampled_at if sample.mode != 'legacy'
                           and sample.sampled_at <= now+.005 else None)
        return mode_changed or self.rings != before or self.animating

    def sample(self, now):
        self._advance(now)
        return self.rings
