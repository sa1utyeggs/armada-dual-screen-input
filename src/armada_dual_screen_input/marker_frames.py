"""Demand-driven marker frames, paced by the reported upper refresh rate.

Only this marker's render callback is scheduled. No GTK private frame-clock
state, compositor settings, input events or continuous idle animation.
"""
from __future__ import annotations

from .i18n import msg

import math
import time

FRAME_RATES = {'auto': msg('choice.follow_screen'), '120': '120 FPS', '60': '60 FPS', '30': '30 FPS'}


def read_frame_rate(value):
    return value if isinstance(value, str) and value in FRAME_RATES else 'auto'


class MarkerFrames:
    def __init__(self, schedule, cancel, paint, failed, *, clock=time.monotonic, frame_rate='auto'):
        if read_frame_rate(frame_rate) != frame_rate:
            raise ValueError('unsupported marker frame rate')
        self.schedule, self.cancel = schedule, cancel
        self.paint, self.failed, self.clock = paint, failed, clock
        self.frame_rate = frame_rate
        self.monitor_millihz = 60000
        self.refresh_millihz = 60000
        self.period = 1/60
        self.pending = self.closed = self.painting = False
        self.source = self.next_due = self.last_started = None

    def set_refresh(self, millihz):
        rate = millihz if type(millihz) is int and 30000 <= millihz <= 240000 else 60000
        self.monitor_millihz = rate
        if self.frame_rate != 'auto':
            rate = min(rate, int(self.frame_rate)*1000)
        if rate == self.refresh_millihz:
            return
        self.refresh_millihz, self.period = rate, 1000/rate
        self.next_due = self.last_started+self.period if self.last_started is not None else None
        self._cancel()
        self._arm()

    def request(self):
        if not self.closed:
            self.pending = True
            self._arm()

    def _arm(self):
        if self.closed or self.painting or not self.pending or self.source is not None:
            return
        wait = max(0., (self.next_due or self.clock())-self.clock())
        self.source = self.schedule(math.ceil(wait*1000), self._dispatch)

    def _cancel(self):
        if self.source is not None:
            self.cancel(self.source)
            self.source = None

    def _dispatch(self):
        self.source = None
        if self.closed or not self.pending:
            return False
        started = self.clock()
        if self.next_due is not None and started+1e-9 < self.next_due:
            self._arm()
            return False
        slot = self.next_due if self.next_due is not None else started
        # Rendering/presentation may itself wait for vblank. Budget from the
        # frame start; waiting another period after it returns halves FPS.
        # Late callbacks skip old slots, without replaying queued positions.
        passed = max(0, math.floor((started-slot)/self.period))
        self.next_due = slot+(passed+1)*self.period
        self.last_started = started
        self.pending, self.painting = False, True
        try:
            self.paint()
        except Exception as error:
            self.close()
            self.failed(error)
            return False
        finally:
            self.painting = False
        # Preserve fractional periods instead of rounding each frame to 9ms.
        self._arm()
        return False

    def close(self):
        self.closed, self.pending = True, False
        self._cancel()
